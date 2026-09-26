import json
import sys
import urllib.error
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from audio_proxy import AudioProxyError, AudioUnavailableError, copy_audio_headers, open_audio  # noqa: E402
from godic_scraper import extract, fetch  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def _json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _audio_error(self, status, message):
        body = message.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _proxy_audio(self):
        query = parse_qs(urlparse(self.path).query)
        target = query.get("url", [""])[0].strip()
        referer = query.get("referer", [""])[0].strip()
        if not target:
            self._audio_error(400, "缺少音频 URL")
            return

        response = None
        try:
            response = open_audio(target, referer, self.headers.get("Range", ""))
            self.send_response(getattr(response, "status", 200))
            copy_audio_headers(self, response)
            self.end_headers()
            while True:
                chunk = response.read(64 * 1024)
                if not chunk:
                    break
                self.wfile.write(chunk)
        except AudioUnavailableError as exc:
            self._audio_error(exc.status_code, str(exc))
        except AudioProxyError as exc:
            self._audio_error(400, str(exc))
        except urllib.error.HTTPError as exc:
            self._audio_error(exc.code, f"音频服务器返回 HTTP {exc.code}")
        except (OSError, TimeoutError) as exc:
            self._audio_error(502, f"音频无法读取：{exc}")
        finally:
            if response is not None:
                response.close()

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Range")
        self.end_headers()

    def do_GET(self):
        if urlparse(self.path).path == "/api/audio":
            self._proxy_audio()
            return
        self._audio_error(404, "Not found")

    def do_POST(self):
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if size > 20_000:
                raise ValueError("请求过大")
            payload = json.loads(self.rfile.read(size))
            url = str(payload.get("url", "")).strip()
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                raise ValueError("请输入有效的 http(s) 听力网址")
            self._json(200, extract(fetch(url), url))
        except ValueError as exc:
            self._json(400, {"error": str(exc)})
        except Exception:
            self._json(502, {"error": "无法连接或解析目标网站，请检查网址后重试。"})
