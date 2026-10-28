"""
比賽資料（session）：賽事、場館、主客隊、球員名單、每台相機的攝影師、圖說範本。

放在 worker/games/（或 .env 的 GAMES_DIR）。一台伺服器 = 一個拍攝計劃 = 一本相簿，所以通常只有一份：
  games/default.toml     拍攝計劃（一般攝影見 games/general.toml，體育賽事格式見 games/example.toml）
  games/default.csv      體育名單：team,jersey,name,position（team = home / away）
（舊模式 SNAPPIPE_SINGLE_ALBUM=0 時，也可以用 games/<相簿名稱>.toml 替個別相簿設定）
比賽中改檔案會自動重新載入（看修改時間），不用重開 worker。

名單的用途是「防止 AI 編造人名」：模型只能回報看到的球衣號碼，姓名一律由這裡查表填入。

三種模式（自動判斷）：
  - 體育：有寫賽事（event）、主客隊（home / away）或名單 → 用體育新聞的標準選片，並寫圖說
  - 一般攝影：都沒寫（例如 default.toml 只有署名）→ 依對焦、表情、構圖選片、評星等，不寫圖說
    [game] subject 可以描述拍攝題材給 AI 參考（例 "cosplay portrait"）
  有拍攝計劃（體育的賽事 / 名單，或一般攝影的 notes / [[people]]）才寫圖說；沒有就只給標籤與星等

拍攝計劃（一般攝影寫圖說時用）：
  [game] notes = "道具：紅色油紙傘…；地點：中式庭園、室內攝影棚"   ← 只當參考，畫面看得到才會寫
  [[people]]  name = "Saki"  character = "角色名"  look = "藍色短髮、黑底紅邊中式服裝、紅色圓形墨鏡"
  模型只回報「畫面裡的人符合第幾個人的外觀」，名字由這裡填入（同名單查表的原則，模型不寫人名）
"""

import csv
import datetime as dt
import re
import threading
from pathlib import Path

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib

DEFAULT_TEMPLATE = {
    "zh": "{CITY}，{DATE_LONG} — {ACTION}。此為{EVENT}{HOME}與{AWAY}之戰，地點為{VENUE}。（攝影：{CREATOR}／{CREDIT}）",
    "en": "{CITY_UPPER}, {COUNTRY} — {ACTION} during the {EVENT} game between {HOME} and {AWAY} at {VENUE} "
          "on {DATE_AP}. ({CREATOR}/{CREDIT})",
}
AP_MONTHS = ["Jan.", "Feb.", "March", "April", "May", "June", "July", "Aug.", "Sept.", "Oct.", "Nov.", "Dec."]


class Game:
    def __init__(self, album: str, info: dict, roster: list, cameras: dict, people: list | None = None):
        self.album = album
        self.people = people or []      # 拍攝計劃裡的人：[{"name", "character", "look"}]
        self.info = info
        self.roster = roster            # [{"team", "jersey", "name", "position"}]
        self.cameras = cameras          # 機身序號（或末幾碼）→ 攝影師
        self.lang = info.get("lang", "zh")

    def get(self, k, d=""):
        return str(self.info.get(k, d) or d)

    @property
    def sport(self):
        return self.get("sport", "sports")

    @property
    def is_sports(self) -> bool:
        return bool(self.get("event") or self.get("home") or self.get("away") or self.roster)

    @property
    def has_plan(self) -> bool:
        """有拍攝計劃：體育的賽事 / 主客隊 / 名單，或一般攝影的 notes / [[people]]。"""
        return self.is_sports or bool(self.people or self.get("notes"))

    @property
    def captions(self) -> bool:
        """有拍攝計劃才寫圖說；沒有就只給標籤與星等。[game] captions = false 可以在有計劃時也關掉。"""
        return self.has_plan and self.info.get("captions") is not False

    @property
    def subject(self) -> str:
        """給 AI 的題材描述。"""
        if self.is_sports:
            return f"Sport: {self.sport}"
        return f"Subject: {self.get('subject') or self.get('sport') or 'general photography (people, events, portraits)'}"

    def team_name(self, team: str) -> str:
        return self.get("home" if team == "home" else "away") if team in ("home", "away") else ""

    def person(self) -> str:
        """認不出名字的人怎麼稱呼。[game] person 可以自訂（例 "一名 Coser"）；沒寫時有主客隊就叫球員，否則叫人物。"""
        if self.get("person"):
            return self.get("person")
        team_sport = bool(self.get("home") or self.get("away") or self.roster)
        if self.lang == "zh":
            return "一名球員" if team_sport else "一名人物"
        return "a player" if team_sport else "a person"

    def lookup(self, team: str, jersey) -> dict | None:
        """(隊伍, 號碼) → 名單上的球員；隊伍不確定時只要號碼在名單上唯一也算。"""
        if jersey is None:
            return None
        hits = [p for p in self.roster if p["jersey"] == int(jersey) and (team not in ("home", "away") or p["team"] == team)]
        return hits[0] if len(hits) == 1 else None

    def creator(self, camera: str | None) -> str:
        """這台相機本場的攝影師：先比完整序號，再比末幾碼（設定檔可以只寫 …5530 的 5530）。"""
        if camera:
            if camera in self.cameras:
                return self.cameras[camera]
            for k, v in self.cameras.items():
                if k and camera.endswith(k.lstrip("…").lstrip(".")):
                    return v
        return self.get("creator")

    def roster_text(self) -> str:
        if not self.roster:
            return "(no roster provided: do not name anyone)"
        lines = []
        for team in ("home", "away"):
            ps = [p for p in self.roster if p["team"] == team]
            if ps:
                lines.append(f"{team} = {self.team_name(team)}: " +
                             ", ".join(f"#{p['jersey']} {p['name']}" + (f" ({p['position']})" if p["position"] else "")
                                       for p in ps))
        return "\n".join(lines)

    def plan_text(self) -> str:
        """給模型的拍攝計劃：人只給角色與外觀（不給本名，避免模型直接寫出來）。"""
        lines = []
        if self.get("notes"):
            lines.append("notes: " + self.get("notes"))
        for i, p in enumerate(self.people):
            bits = [f"character: {p['character']}" if p.get("character") else "", f"look: {p['look']}" if p.get("look") else ""]
            lines.append(f"person {i}: " + "; ".join(b for b in bits if b))
        return "\n".join(lines) or "(no shoot plan)"

    def plan_ref(self, i: int, lang: str) -> str | None:
        """計劃裡第 i 個人在圖說裡的寫法：名字（飾 角色）。"""
        if not isinstance(i, int) or not 0 <= i < len(self.people):
            return None
        p = self.people[i]
        name, ch = p.get("name", ""), p.get("character", "")
        if lang == "zh":
            return f"{name}（飾{ch}）" if name and ch else (name or ch or None)
        return f"{name} as {ch}" if name and ch else (name or ch or None)

    def context_text(self) -> str:
        keys = ("sport", "event", "venue", "city", "country", "date", "home", "away", "home_color", "away_color")
        return "\n".join(f"{k}: {self.info[k]}" for k in keys if self.info.get(k))

    def caption(self, action: str, taken_at: str | None, camera: str | None) -> str:
        """圖說 = 範本（日期、地點、賽事、署名都由系統填）+ AI 只寫的那一句動作描述。"""
        date = parse_date(taken_at) or parse_date(self.get("date"))
        tpl = self.get("caption_template") or DEFAULT_TEMPLATE.get(self.lang, DEFAULT_TEMPLATE["zh"])
        if not (self.get("event") and self.get("home") and self.get("away")):
            tpl = "{ACTION}。（攝影：{CREATOR}／{CREDIT}）" if self.lang == "zh" else "{ACTION}. ({CREATOR}/{CREDIT})"
        action = action.strip().rstrip("。.")
        fields = {
            "ACTION": action, "CITY": self.get("city"), "CITY_UPPER": self.get("city").upper(),
            "COUNTRY": self.get("country"), "EVENT": self.get("event"), "HOME": self.get("home"),
            "AWAY": self.get("away"), "VENUE": self.get("venue"), "CREATOR": self.creator(camera),
            "CREDIT": self.get("credit", "SnapPipe"),
            "DATE_LONG": f"{date.year} 年 {date.month} 月 {date.day} 日" if date else "",
            "DATE_AP": f"{AP_MONTHS[date.month - 1]} {date.day}, {date.year}" if date else "",
        }
        out = tpl
        for k, v in fields.items():
            out = out.replace("{" + k + "}", v)
        # 沒填的欄位留下的空殼清掉：「（攝影：／SnapPipe）」→「（SnapPipe）」、開頭的「，」
        out = re.sub(r"（攝影：／", "（", out).replace("：／", "：")
        out = re.sub(r"^[，,\s—-]+", "", out)
        return re.sub(r"\s{2,}", " ", out).strip()


def parse_date(v):
    if not v:
        return None
    try:
        return dt.date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def read_roster(path: Path) -> list:
    out = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            team = (row.get("team") or "").strip().lower()
            jersey = (row.get("jersey") or "").strip()
            name = (row.get("name") or "").strip()
            if team in ("home", "away") and jersey.isdigit() and name:
                out.append({"team": team, "jersey": int(jersey), "name": name,
                            "position": (row.get("position") or "").strip()})
    return out


class Games:
    """依相簿名稱找比賽資料，檔案改了就重新讀。"""

    def __init__(self, folder: Path, log=print):
        self.folder = folder
        self.log = log
        self._cache = {}
        self._lock = threading.Lock()   # 幾組連拍平行分析時只讀一次

    def files_for(self, album: str):
        for stem in (album, "default"):
            toml = self.folder / f"{stem}.toml"
            if toml.exists():
                return toml, self.folder / f"{stem}.csv"
        return None, self.folder / f"{album}.csv"

    def get(self, album: str) -> Game:
        with self._lock:
            return self._get(album)

    def _get(self, album: str) -> Game:
        toml, csv_path = self.files_for(album)
        sig = tuple((p, p.stat().st_mtime) for p in (toml, csv_path) if p and p.exists())
        hit = self._cache.get(album)
        if hit and hit[0] == sig:
            return hit[1]
        info, cameras, roster, people = {}, {}, [], []
        try:
            if toml:
                with open(toml, "rb") as f:
                    d = tomllib.load(f)
                info = dict(d.get("game", {}))
                cameras = {str(k): str(v) for k, v in d.get("cameras", {}).items()}
                roster = [{"team": str(p.get("team", "")).lower(), "jersey": int(p["jersey"]), "name": str(p["name"]),
                           "position": str(p.get("position", ""))} for p in d.get("roster", [])
                          if str(p.get("jersey", "")).isdigit() and p.get("name")]
                people = [{k: str(p.get(k, "")) for k in ("name", "character", "look")}
                          for p in d.get("people", []) if isinstance(p, dict) and (p.get("name") or p.get("character"))]
            if csv_path.exists():
                roster = read_roster(csv_path)
        except (OSError, ValueError, KeyError, tomllib.TOMLDecodeError) as e:
            self.log(f"  ⚠ 比賽資料 {toml or csv_path} 讀取失敗：{e}（先用空白資料）")
        g = Game(album, info, roster, cameras, people)
        if sig and (not hit or hit[0] != sig):
            self.log(f"  比賽資料 {album}：{g.get('event') or '（無賽事名稱）'}  名單 {len(roster)} 人  "
                     f"相機 {len(cameras)} 台" + ("" if toml is None or toml.stem == album else "（用 default）"))
        self._cache[album] = (sig, g)
        return g
