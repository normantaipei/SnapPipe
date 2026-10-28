"""模擬 Meta Model API 的 /v1/chat/completions，檢查請求格式並回傳固定答案。"""
import base64, io, json, sys, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from PIL import Image

LOG = sys.argv[2]
lock = threading.Lock()
state = {"n": 0}

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def send(self, code, obj, headers=()):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        for k, v in headers: self.send_header(k, v)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers(); self.wfile.write(b)
    def do_POST(self):
        with lock:
            state["n"] += 1; n = state["n"]
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        problems = []
        if self.path != "/v1/chat/completions": problems.append("path " + self.path)
        if self.headers.get("Authorization") != "Bearer test-key": problems.append("auth")
        if body.get("model") != "muse-spark-1.3": problems.append("model")
        rf = body.get("response_format", {})
        if rf.get("type") != "json_schema" or "schema" not in rf.get("json_schema", {}): problems.append("response_format")
        msgs = body["messages"]
        if [m["role"] for m in msgs] != ["system", "user"]: problems.append("roles")
        imgs = [c for c in msgs[1]["content"] if c["type"] == "image_url"]
        sizes = []
        for c in imgs:
            url = c["image_url"]["url"]
            assert url.startswith("data:image/jpeg;base64,")
            im = Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1])))
            sizes.append(max(im.size))
        name = rf["json_schema"]["name"]
        with lock, open(LOG, "a") as f:
            f.write(json.dumps({"n": n, "name": name, "images": len(imgs), "max_edge": max(sizes or [0]),
                                "reasoning": body.get("reasoning_effort"), "problems": problems}) + "\n")
        if len(sys.argv) > 3 and sys.argv[3] == "badjson":   # 模型一直回壞掉的 JSON：測降級
            return self.send(200, {"choices": [{"message": {"content": "sorry, I cannot"}}], "usage": {}})
        if n == 1:   # 第一次故意回 429，測重試
            return self.send(429, {"error": {"message": "rate limited"}}, [("Retry-After", "1")])
        if problems:
            return self.send(400, {"error": {"message": ", ".join(problems)}})
        if name == "burst_selection":
            N = len(imgs)
            best = [N // 2] if N < 4 else [N // 2, N - 1]
            out = {"best": best, "moment": "peak_action",
                   "frames": [{"index": i, "overall": 8.5 if i in best else 6, "peak": 9 if i == N // 2 else 5,
                               "focus": 8, "composition": 7,
                               "issues": ["motion_blur_subject"] if i == 0 and N > 1 else []} for i in range(N)]}
            content = json.dumps(out)
        else:
            out = {"players": [
                       {"team": "home", "jersey": 23, "confidence": 0.93, "role_in_frame": "primary", "box": [0.3, 0.1, 0.25, 0.4]},
                       {"team": "away", "jersey": 11, "confidence": 0.62, "role_in_frame": "secondary", "box": [0.6, 0.2, 0.2, 0.3]},
                       {"team": "away", "jersey": 99, "confidence": 0.9, "role_in_frame": "primary", "box": [0.1, 0.5, 0.1, 0.2]}],
                   "action_sentence": "{P0} 在 {P1} 防守下灌籃得分",
                   "headline": "{P0} 灌籃", "keywords": ["籃球", "灌籃"], "needs_review": False, "review_reasons": []}
            content = "```json\n" + json.dumps(out, ensure_ascii=False) + "\n```"   # 測 strip_fence
        self.send(200, {"choices": [{"message": {"role": "assistant", "content": content}}],
                        "usage": {"prompt_tokens": 1000 * max(1, len(imgs)), "completion_tokens": 300}})

ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
