"""
Meta AI 分析器：用 Meta Model API（Muse Spark）做體育新聞的選片、球員辨識與圖說草稿。

兩階段（docs/DESIGN.md §9）：
  階段一  整組連拍（同一台相機、間隔很短，最多 40 張）的 512px 縮圖一次送出，
          模型互相比較，選出決定性瞬間 1~3 張、每張評分、判斷動作類型（moment）與問題（失焦、擋臉…）
  階段二  只送選中的那幾張（1536px）+ 比賽資料與名單：讀球衣號碼與隊伍、寫一句動作描述、標題、關鍵字

防呆（§9.5）：
  - 模型不寫人名。描述裡用 {P0}、{P1} 代表 players 陣列裡的人，系統用名單查到的姓名替換；
    號碼對不上名單就寫「台北雄鷹隊 #23 球員」，並標記需要人工確認
  - 日期、地點、賽事、署名由範本填入，AI 只負責「誰在做什麼」那一句
  - 階段一失敗（輸出格式錯）時退回本機銳利度排序，照片照常進編輯檯；網路或 429 才整組重試

設定（worker/.env）：META_API_KEY、META_MODEL、META_API_BASE、META_REASONING、META_TIMEOUT、GAMES_DIR、
BURST_THUMB_EDGE、CAPTION_EDGE、CAPTION、MAX_PICKS、STAR_THRESHOLDS、REVIEW_CONF、PLAYER_MIN_CONF、
SCORE_WEIGHTS、WRITE_IPTC、RATING_OVERWRITE
"""

import concurrent.futures as cf
import datetime as dt
import re
import time
from pathlib import Path

from PIL import ImageFilter, ImageStat

import iptc
from games import Game, Games
from meta_api import DEFAULT_BASE, DEFAULT_MODEL, MetaApiError, MetaClient, data_url, load_rgb

from .base import Analysis, Analyzer, Player

HERE = Path(__file__).resolve().parent.parent      # worker/
PROMPT_VERSION = "v1"

MOMENTS = ["peak_action", "goal_score", "celebration", "dejection", "contested_ball", "foul_injury",
           "coach_bench", "crowd", "portrait", "other"]
MOMENT_LABEL = {
    "zh": {"peak_action": "關鍵動作", "goal_score": "得分", "celebration": "慶祝", "dejection": "懊惱",
           "contested_ball": "爭球", "foul_injury": "犯規受傷", "coach_bench": "教練席", "crowd": "觀眾",
           "portrait": "人像", "other": "其他"},
    "en": {"peak_action": "peak action", "goal_score": "score", "celebration": "celebration", "dejection": "dejection",
           "contested_ball": "contested ball", "foul_injury": "foul / injury", "coach_bench": "bench",
           "crowd": "crowd", "portrait": "portrait", "other": "other"},
}
ISSUES = ["out_of_focus", "motion_blur_subject", "face_blocked", "subject_cropped", "ball_missing", "eyes_closed",
          "over_exposed", "under_exposed"]
PENALTY = {"out_of_focus": 2.5, "motion_blur_subject": 1.5, "face_blocked": 1.5, "subject_cropped": 1.0,
           "eyes_closed": 1.0, "ball_missing": 0.5, "over_exposed": 0.5, "under_exposed": 0.5}
PICK_LABEL = {"zh": "AI 精選", "en": "AI pick"}

# ---------- 階段一：連拍比較選片 ----------

SELECT_SYSTEM = """You are a senior picture editor at a sports wire agency.
You receive N frames from ONE burst shot by ONE camera, in time order, numbered 0..N-1.
Compare them against each other and pick the 1-3 most newsworthy frames.

Selection criteria, most important first:
1. Decisive moment: ball contact with hand/foot/racket, peak of the action, emotion at its fullest (celebration, dejection).
2. Subject focus: the main player's face or eyes are sharp; motion blur must not hide the subject.
3. Storytelling: ball, main player and opponent related in one frame; reactions of fans or coaches.
4. Composition: subject not cut off, nothing blocking the face.

Score every frame from 1 to 10 (overall, peak, focus, composition) and list its problems.
"local sharpness" is a pixel-level hint from the server (0-1, higher is sharper), not a judgement of content.
Output only JSON that matches the schema."""

SELECT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["best", "frames", "moment"],
    "properties": {
        "best": {"type": "array", "items": {"type": "integer"}, "minItems": 1, "maxItems": 3},
        "moment": {"type": "string", "enum": MOMENTS},
        "frames": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["index", "overall", "peak", "focus", "composition", "issues"],
                "properties": {
                    "index": {"type": "integer"},
                    "overall": {"type": "number", "minimum": 1, "maximum": 10},
                    "peak": {"type": "number", "minimum": 1, "maximum": 10},
                    "focus": {"type": "number", "minimum": 1, "maximum": 10},
                    "composition": {"type": "number", "minimum": 1, "maximum": 10},
                    "issues": {"type": "array", "items": {"type": "string", "enum": ISSUES}},
                },
            },
        },
    },
}

# ---------- 階段二：球員辨識與圖說 ----------

DESCRIBE_SYSTEM = """You are a sports news caption editor. Describe what happens in the photo for a wire-agency caption.

Strict rules:
- Report players by what is visible: team (home/away from the uniform colours given) and jersey number.
  If a number is not clearly readable, set jersey to null. Never guess.
- NEVER write a person's name anywhere. In action_sentence and headline refer to people only with placeholders
  {P0}, {P1}, ... where the number is the index in your players array. The system fills in names from the roster.
- Do not state facts that are not visible (score, result, quarter) unless the game data provides them.
- action_sentence is ONE sentence describing who does what, e.g. "{P0} dunks over {P1} in the third quarter".
- box is the player's head and upper body: [x, y, width, height], fractions 0-1 of the image as shown, origin top-left.
- keywords: sport terms and actions only, no names. Up to 10.
- Set needs_review when you are unsure about anything a caption editor must check.
Write action_sentence, headline and keywords in {LANG}.
Output only JSON that matches the schema."""

DESCRIBE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["players", "action_sentence", "headline", "keywords", "needs_review", "review_reasons"],
    "properties": {
        "players": {
            "type": "array",
            "maxItems": 6,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["team", "jersey", "confidence", "role_in_frame", "box"],
                "properties": {
                    "team": {"type": "string", "enum": ["home", "away", "unknown"]},
                    "jersey": {"type": ["integer", "null"]},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "role_in_frame": {"type": "string", "enum": ["primary", "secondary", "background"]},
                    "box": {"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4},
                },
            },
        },
        "action_sentence": {"type": "string", "maxLength": 200},
        "headline": {"type": "string", "maxLength": 80},
        "keywords": {"type": "array", "items": {"type": "string"}, "maxItems": 10},
        "needs_review": {"type": "boolean"},
        "review_reasons": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
    },
}
LANG_NAME = {"zh": "Traditional Chinese as used in Taiwan", "en": "English (AP style)", "ja": "Japanese"}
PLACEHOLDER = re.compile(r"\{P(\d+)\}")


def sharpness(img) -> float:
    """本機銳利度：灰階縮圖的拉普拉斯變異數（越大越銳利）。不需要 OpenCV。"""
    edges = img.convert("L").filter(ImageFilter.Kernel((3, 3), [0, 1, 0, 1, -4, 1, 0, 1, 0], scale=1, offset=128))
    return ImageStat.Stat(edges).var[0]


def seconds(iso):
    try:
        return dt.datetime.fromisoformat(iso).timestamp() if iso else None
    except ValueError:
        return None


class MetaAIAnalyzer(Analyzer):
    name = "meta-ai"
    wants_bursts = True

    def __init__(self, cfg, log=print):
        super().__init__(cfg, log)
        c = cfg.get
        self.client = MetaClient(c("META_API_KEY") or c("MODEL_API_KEY"), c("META_API_BASE") or DEFAULT_BASE,
                                 c("META_MODEL") or DEFAULT_MODEL, c("META_REASONING", "low"),
                                 float(c("META_TIMEOUT", "120")), log=log)
        self.games = Games(Path(c("GAMES_DIR") or HERE / "games").expanduser(), log)
        self.thumb_edge = int(c("BURST_THUMB_EDGE", "512"))
        self.detail_edge = int(c("CAPTION_EDGE", "1536"))
        self.caption_on = c("CAPTION", "1") == "1"
        self.max_picks = max(1, min(int(c("MAX_PICKS", "3")), 3))
        self.pick_min = float(c("PICK_MIN_SCORE", "4"))
        self.thresholds = sorted(float(x) for x in c("STAR_THRESHOLDS", "4,5.5,7,8.5").split(","))
        self.review_conf = float(c("REVIEW_CONF", "0.8"))
        self.player_min_conf = float(c("PLAYER_MIN_CONF", "0.7"))
        w = [float(x) for x in c("SCORE_WEIGHTS", "0.65,0.25,0.10").split(",")]
        self.w_overall, self.w_peak, self.w_sharp = (w + [0.65, 0.25, 0.10][len(w):])[:3]
        self.overwrite = c("RATING_OVERWRITE", "0") == "1"
        self.write_iptc = c("WRITE_IPTC", "1") == "1"
        if self.write_iptc and not iptc.have_exiftool():
            log("  ⚠ 找不到 exiftool：照片不會寫入 IPTC（圖說、星等仍會送到伺服器）。安裝：brew install exiftool"
                " / apt install libimage-exiftool-perl")
            self.write_iptc = False
        self.name = f"meta-ai:{self.client.model}"
        self._account_warned = set()

    # ---- 主流程 ----

    def analyze_burst(self, items: list) -> list:
        items = sorted(items, key=lambda it: (it[1].get("taken_at") or "", it[1]["filename"]))
        game = self.games.get(items[0][1]["album"])
        lang = game.lang if game.lang in MOMENT_LABEL else "zh"
        t0 = time.time()
        thumbs = [load_rgb(p, self.thumb_edge) for p, _ in items]
        sharp = [sharpness(im) for im in thumbs]
        top = max(sharp) or 1.0
        sharp_n = [s / top for s in sharp]
        usage = {"input_tokens": 0, "output_tokens": 0}

        try:
            sel, u = self.select(thumbs, items, sharp_n, game)
            add_usage(usage, u)
            ai_failed = None
        except MetaApiError as e:
            if e.retry:
                raise                         # 網路 / 429 / 5xx：整組晚點重試
            self.warn_failure(e)
            sel, ai_failed = {"best": [], "frames": [], "moment": "other"}, str(e)[:200]

        frames = {f.get("index"): f for f in sel.get("frames", []) if isinstance(f, dict)}
        finals = [self.final_score(frames.get(i), sharp_n[i]) for i in range(len(items))]
        best = []
        for i in sel.get("best", []):
            if isinstance(i, int) and 0 <= i < len(items) and i not in best:
                best.append(i)
        if not best:
            best = [max(range(len(items)), key=lambda i: finals[i])]
        best = best[:self.max_picks]
        # 第一名一定留；第二、三名分數太低（整組都糊）就不算精選，免得編輯檯塞滿爛片、也省下階段二的費用
        best = best[:1] + [i for i in best[1:] if finals[i] >= self.pick_min]
        moment = sel.get("moment") if sel.get("moment") in MOMENTS else "other"

        # 階段二：只做選中的幾張，同時送出
        described = {}
        if self.caption_on and not ai_failed:
            with cf.ThreadPoolExecutor(max_workers=len(best)) as ex:
                futs = {ex.submit(self.describe, items[i][0], items[i][1], game, moment): i for i in best}
                for fut in cf.as_completed(futs):
                    i = futs[fut]
                    try:
                        described[i], u = fut.result()
                        add_usage(usage, u)
                    except MetaApiError as e:
                        self.log(f"  ⚠ 圖說失敗 {items[i][1]['filename']}：{e}（照片照常進編輯檯，圖說請手動補）")
                        described[i] = {"error": str(e)[:200]}

        burst_id = items[0][1]["photo_id"][:12]
        elapsed = round(time.time() - t0, 2)
        out = []
        for i, (path, job) in enumerate(items):
            out.append(self.build(path, job, game, lang, i, len(items), burst_id, best, moment, frames.get(i),
                                  finals[i], sharp_n[i], described.get(i), ai_failed,
                                  {"model": self.client.model, "prompt": PROMPT_VERSION, "burst_sec": elapsed,
                                   **({"usage": usage} if i == 0 else {})}))
        return out

    def analyze(self, path: Path, job: dict) -> Analysis:
        return self.analyze_burst([(path, job)])[0]

    def warn_failure(self, e: MetaApiError):
        """帳號類錯誤（金鑰、付款、權限）每組都會遇到：完整說明只印第一次，之後一行帶過。"""
        if e.status in (401, 402, 403):
            if e.status in self._account_warned:
                self.log(f"  ⚠ Meta {e.status}：AI 沒有作用，照片照常進相簿（星等用本機銳利度估計）")
                return
            self._account_warned.add(e.status)
            self.log(f"  ⚠ {e}\n    處理好之前照片照常進相簿，星等與精選改用本機銳利度估計、不寫圖說；"
                     "修好後下一組就會恢復，不用重開 worker")
            return
        self.log(f"  ⚠ 階段一失敗，改用本機銳利度排序：{e}")

    # ---- 階段一 ----

    def select(self, thumbs, items, sharp_n, game: Game):
        t_first = seconds(items[0][1].get("taken_at"))
        content = [{"type": "text", "text": f"Sport: {game.sport}. {len(items)} frame(s) from one burst, in time order."}]
        for i, (img, (_, job)) in enumerate(zip(thumbs, items)):
            t = seconds(job.get("taken_at"))
            offset = f"+{t - t_first:.2f}s" if t is not None and t_first is not None else "time unknown"
            content.append({"type": "text", "text": f"Frame {i}: {offset}, local sharpness {sharp_n[i]:.2f}"})
            content.append({"type": "image_url", "image_url": {"url": data_url(img, 80)}})
        return self.client.chat_json(SELECT_SYSTEM, content, SELECT_SCHEMA, "burst_selection", max_tokens=3000)

    def final_score(self, f, sharp_n: float) -> float:
        """§9.6：final = 0.65 × overall + 0.25 × peak + 0.10 × 銳利度 − 問題扣分（AI 沒給分時只看銳利度）。"""
        if not f:
            return round(1 + 6 * sharp_n, 2)
        try:
            overall, peak = float(f.get("overall", 5)), float(f.get("peak", 5))
        except (TypeError, ValueError):
            overall = peak = 5.0
        score = self.w_overall * overall + self.w_peak * peak + self.w_sharp * 10 * sharp_n
        score -= sum(PENALTY.get(x, 0) for x in set(f.get("issues") or []))
        return round(max(1.0, min(score, 10.0)), 2)

    def stars_of(self, score: float) -> int:
        return 1 + sum(score >= t for t in self.thresholds)

    # ---- 階段二 ----

    def describe(self, path: Path, job: dict, game: Game, moment: str):
        img = load_rgb(path, self.detail_edge)
        lang = LANG_NAME.get(game.lang, LANG_NAME["zh"])
        facts = [game.context_text() or f"sport: {game.sport}", f"captured at: {job.get('taken_at') or 'unknown'}",
                 f"moment type from burst selection: {moment}", "roster:", game.roster_text()]
        content = [{"type": "text", "text": "Game data:\n" + "\n".join(facts)},
                   {"type": "image_url", "image_url": {"url": data_url(img, 88)}}]
        return self.client.chat_json(DESCRIBE_SYSTEM.replace("{LANG}", lang), content, DESCRIBE_SCHEMA,
                                     "photo_caption", max_tokens=2500)

    def resolve_players(self, d: dict, game: Game, lang: str):
        """模型回報的 (隊伍, 號碼) → 名單上的姓名。回傳 (顯示用的稱呼, 球員清單, 需人工確認的原因)。"""
        refs, players, reasons = [], [], []
        for n, p in enumerate(d.get("players") or []):
            if not isinstance(p, dict):
                refs.append(None)
                continue
            team, jersey = p.get("team", "unknown"), p.get("jersey")
            conf = float(p.get("confidence") or 0)
            hit = game.lookup(team, jersey)
            if hit:
                team = hit["team"]
            tname = game.team_name(team)
            if hit:
                if lang == "zh":
                    ref = f"{tname}{'' if not tname or tname.endswith('隊') else '隊'}{hit['name']}（#{jersey}）"
                else:
                    ref = f"{tname + ' ' if tname else ''}{hit['name']} (#{jersey})"
            elif jersey is not None:
                ref = (f"{tname}{'' if not tname or tname.endswith('隊') else '隊'} #{jersey} 球員" if lang == "zh"
                       else f"{'No. ' + str(jersey)}{' of ' + tname if tname else ''}")
                if p.get("role_in_frame") == "primary" and game.roster:
                    reasons.append(f"#{jersey} 不在名單上" if lang == "zh" else f"#{jersey} is not on the roster")
            else:
                ref = game.person()
            if hit and conf < self.review_conf and p.get("role_in_frame") != "background":
                reasons.append(f"#{jersey} {hit['name']} 信心 {conf:.2f}" if lang == "zh"
                               else f"#{jersey} {hit['name']} confidence {conf:.2f}")
            box = p.get("box")
            box = tuple(min(max(float(v), 0.0), 1.0) for v in box[:4]) if isinstance(box, list) and len(box) >= 4 else None
            refs.append(ref)
            players.append({"n": n, "team": team, "jersey": jersey, "name": hit["name"] if hit else None,
                            "confidence": round(conf, 2), "role": p.get("role_in_frame"), "box": box,
                            "verified": bool(hit)})
        return refs, players, reasons

    def fill(self, text: str, refs: list, lang: str, short: dict | None = None, person: str | None = None) -> str:
        def sub(m):
            i = int(m.group(1))
            if short is not None and i in short:
                return short[i]
            return refs[i] if i < len(refs) and refs[i] else (person or ("一名人物" if lang == "zh" else "a person"))
        return PLACEHOLDER.sub(sub, text or "").strip()

    # ---- 組合結果 ----

    def build(self, path, job, game: Game, lang, i, n, burst_id, best, moment, frame, final, sharp_n, desc,
              ai_failed, extra) -> Analysis:
        pick = i in best
        moment_label = MOMENT_LABEL[lang][moment]
        ai = {"pick": pick, "rank": best.index(i) + 1 if pick else None, "moment": moment,
              "moment_label": moment_label, "score": final,
              "burst": {"id": burst_id, "n": n, "index": i}, "sharpness": round(sharp_n, 2)}
        if frame:
            ai["scores"] = {k: frame.get(k) for k in ("overall", "peak", "focus", "composition")}
            ai["issues"] = [x for x in frame.get("issues") or [] if x in ISSUES]
        if ai_failed:
            ai["ai_failed"] = ai_failed
        tags = [moment_label] if moment != "other" else []
        if pick:
            tags.insert(0, PICK_LABEL[lang])
        # 機身序號：伺服器入庫時讀過就用；沒有就自己從 EXIF 讀（署名要靠它對到攝影師）
        exif = iptc.read_exif(path) if iptc.have_exiftool() else {}
        camera = job.get("camera") or str(exif.get("BodySerialNumber") or exif.get("SerialNumber") or "") or None
        headline = caption = None
        players, people_names, reasons = [], [], []
        if desc and "error" not in desc:
            refs, plist, reasons = self.resolve_players(desc, game, lang)
            short = {p["n"]: p["name"] for p in plist if p["name"]}
            action = self.fill(desc.get("action_sentence", ""), refs, lang, person=game.person())
            # 模型違規直接寫了名單上的人名（沒用 {P0} 佔位）→ 要人工確認
            leaked = [r["name"] for r in game.roster if r["name"] in (desc.get("action_sentence") or "")]
            if leaked:
                reasons.append(("描述裡出現未經號碼確認的人名：" if lang == "zh" else "name written without jersey check: ")
                               + "、".join(leaked))
            if action:
                caption = game.caption(tidy(action, lang), job.get("taken_at"), camera)
            headline = tidy(self.fill(desc.get("headline", ""), refs, lang, short, game.person()), lang) or None
            people_names = [p["name"] for p in plist if p["name"]]
            for p in plist:
                if p["name"] and p["confidence"] >= self.player_min_conf:
                    players.append(Player(f"{p['team']}:{p['jersey']}", f"#{p['jersey']} {p['name']}", p["box"],
                                          p["confidence"]))
            tags += people_names + [str(k) for k in desc.get("keywords") or []][:8]
            reasons += [str(r) for r in desc.get("review_reasons") or []]
            needs_review = bool(desc.get("needs_review")) or bool(reasons)
            ai.update({"players": [{k: v for k, v in p.items() if k != "n"} for p in plist],
                       "needs_review": needs_review, "review_reasons": reasons[:6]})
        elif desc:
            ai.update({"caption_failed": desc["error"], "needs_review": True})

        # 相機內評過的星等優先（攝影師在場邊按的鎖定 / 星等），除非 RATING_OVERWRITE=1
        stars = self.stars_of(final)
        cam_rating = exif.get("Rating")
        if str(cam_rating or "").isdigit() and int(cam_rating) > 0 and not self.overwrite:
            stars = int(cam_rating)
        urgency = 1 if final >= 9 else 3 if final >= 7 else 5
        ai["urgency"] = urgency

        modified = False
        if self.write_iptc:
            year = (job.get("taken_at") or "")[:4] or str(dt.date.today().year)
            creator = game.creator(camera)
            event = " ".join(x for x in (game.get("event"), f"{game.get('home')} vs {game.get('away')}"
                                         if game.get("home") and game.get("away") else "") if x)
            modified = iptc.write(
                path, stars=stars, urgency=urgency, pick=pick, headline=headline or "", caption=caption or "",
                keywords=tags + [game.sport] * bool(game.get("sport")), people=people_names, event=event,
                city=game.get("city"), sublocation=game.get("venue"), country=game.get("country"),
                creator=creator, credit=game.get("credit"),
                copyright=game.get("copyright") or (f"© {year} {creator}" if creator else ""))
        return Analysis(stars=stars, aesthetic=final, tags=dedupe(tags)[:12], camera=camera, headline=headline,
                        caption=caption, ai=ai, players=players, file_modified=modified, extra=extra)


CJK = r"[\u3000-\u303f\u3400-\u9fff\uff00-\uffef]"


def tidy(text: str, lang: str) -> str:
    """中文：拿掉中文字與全形標點旁邊多出來的空白（模型常在 {P0} 兩邊加空格）。"""
    text = re.sub(r"\s+", " ", text or "").strip()
    if lang in ("zh", "ja"):
        text = re.sub(rf"(?<={CJK}) +| +(?={CJK})", "", text)
    return text


def add_usage(total: dict, u: dict):
    for k in total:
        total[k] += int(u.get(k) or 0)


def dedupe(xs):
    seen, out = set(), []
    for x in xs:
        k = str(x).strip()
        if k and k.lower() not in seen:
            seen.add(k.lower())
            out.append(k)
    return out
