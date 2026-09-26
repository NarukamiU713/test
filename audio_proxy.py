"""Safe streaming proxy helpers for publicly exposed audio URLs."""

from __future__ import annotations

import ipaddress
import re
import socket
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener


class AudioProxyError(ValueError):
    """Raised when an audio URL is not safe or cannot be reached."""


class AudioUnavailableError(AudioProxyError):
    """Raised when the upstream returns a known non-content placeholder."""

    status_code = 403


def _assert_public_host(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise AudioProxyError("音频地址必须是有效的 http(s) URL")
    if parsed.username or parsed.password:
        raise AudioProxyError("音频地址不能包含用户名或密码")

    host = parsed.hostname.rstrip(".")
    if host.lower() in {"localhost", "localhost.localdomain"}:
        raise AudioProxyError("不允许代理本机地址")

    try:
        addresses = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            addresses = [ipaddress.ip_address(item[4][0]) for item in socket.getaddrinfo(host, None)]
        except OSError as exc:
            raise AudioProxyError("无法解析音频服务器地址") from exc

    if not addresses or any(not address.is_global for address in addresses):
        raise AudioProxyError("不允许代理内网或本机地址")


class _SafeRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _assert_public_host(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def open_audio(url: str, referer: str = "", range_header: str = ""):
    """Open an audio URL while preserving browser range requests and referer."""
    _assert_public_host(url)
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; transcript-extractor/1.0)",
        "Accept": "audio/*,video/*;q=0.9,*/*;q=0.1",
    }
    if referer:
        parsed_referer = urlparse(referer)
        if parsed_referer.scheme in {"http", "https"} and parsed_referer.netloc:
            headers["Referer"] = referer
            headers["Origin"] = f"{parsed_referer.scheme}://{parsed_referer.netloc}"
    if range_header and range_header.lower().startswith("bytes=") and "," not in range_header:
        headers["Range"] = range_header

    request = Request(url, headers=headers, method="GET")
    opener = build_opener(_SafeRedirectHandler())
    response = opener.open(request, timeout=30)
    if is_upgrade_placeholder(response):
        response.close()
        raise AudioUnavailableError(
            "Godic 音频接口返回的是 upgrade_info.mp3（约 24 秒的升级/试听提示），"
            "不是这篇听力的完整音频。当前公开请求没有获得完整音频；请在 Godic 页面"
            "登录或购买后使用页面提供的原始播放，工具不会绕过访问限制。"
        )
    return response


def is_upgrade_placeholder(response) -> bool:
    """Recognize Godic's short upgrade prompt before streaming it as article audio."""
    final_url = (response.geturl() or "").lower()
    disposition = (response.headers.get("Content-Disposition") or "").lower()
    filename = re.search(r"filename\s*=\s*[\"']?([^\"';]+)", disposition)
    filename = filename.group(1).strip() if filename else ""
    return "upgrade_info" in final_url or "upgrade_info" in filename


def copy_audio_headers(handler, response) -> None:
    """Copy only response headers that are useful and safe for media playback."""
    for name in (
        "Content-Type",
        "Content-Length",
        "Content-Range",
        "Accept-Ranges",
        "Content-Disposition",
        "ETag",
        "Last-Modified",
    ):
        value = response.headers.get(name)
        if value:
            handler.send_header(name, value)
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Cache-Control", "no-store")


