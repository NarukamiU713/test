#!/usr/bin/env python3
"""Local web UI for extracting the public Godic transcript payload."""

import json
import os
import sys
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from audio_proxy import AudioProxyError, copy_audio_headers, open_audio  # noqa: E402
from godic_scraper import extract, fetch  # noqa: E402


class Handler(BaseHTTPRequestHandler):
    def _send(self, status, content_type, body):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _proxy_audio(self):
        query = parse_qs(urlparse(self.path).query)
        target = query.get("url", [""])[0].strip()
        referer = query.get("referer", [""])[0].strip()
        if not target:
            self._send(400, "text/plain; charset=utf-8", "缺少音频 URL")
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
        except AudioProxyError as exc:
            self._send(400, "text/plain; charset=utf-8", str(exc))
        except urllib.error.HTTPError as exc:
            self._send(exc.code, "text/plain; charset=utf-8", f"音频服务器返回 HTTP {exc.code}")
        except (OSError, TimeoutError) as exc:
            self._send(502, "text/plain; charset=utf-8", f"音频无法读取：{exc}")
        finally:
            if response is not None:
                response.close()

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/audio":
            self._proxy_audio()
            return
        if parsed.path in ("/", "/index.html"):
            self._send(200, "text/html; charset=utf-8", (HERE / "index.html").read_text(encoding="utf-8"))
            return
        self._send(404, "application/json; charset=utf-8", json.dumps({"error": "Not found"}))

    def do_POST(self):
        if urlparse(self.path).path != "/api/parse":
            self._send(404, "application/json; charset=utf-8", json.dumps({"error": "Not found"}))
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if size > 20_000:
                raise ValueError("请求过大")
            payload = json.loads(self.rfile.read(size))
            url = str(payload.get("url", "")).strip()
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                raise ValueError("请输入有效的 http(s) 听力网址")
            result = extract(fetch(url), url)
            self._send(200, "application/json; charset=utf-8", json.dumps(result, ensure_ascii=False))
        except urllib.error.HTTPError as exc:
            self._send(502, "application/json; charset=utf-8", json.dumps({"error": f"目标网站返回 HTTP {exc.code}，请检查网址或稍后重试。"}, ensure_ascii=False))
        except (TimeoutError, OSError) as exc:
            self._send(502, "application/json; charset=utf-8", json.dumps({"error": "无法连接目标网站。请确认电脑已联网，或稍后重试。"}, ensure_ascii=False))
        except ValueError as exc:
            self._send(400, "application/json; charset=utf-8", json.dumps({"error": str(exc)}, ensure_ascii=False))
        except Exception:
            self._send(500, "application/json; charset=utf-8", json.dumps({"error": "解析失败，请检查网址后重试。"}, ensure_ascii=False))

    def log_message(self, fmt, *args):
        print("[%s] %s" % (self.log_date_time_string(), fmt % args))


def main():
    port = int(os.environ.get("PORT", "8765"))
    host = os.environ.get("HOST", "0.0.0.0")
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Godic Transcript UI listening on {host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
