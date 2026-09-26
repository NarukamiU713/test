#!/usr/bin/env python3
"""Extract publicly delivered transcript and audio references from a Godic webting page.

The script only parses data present in the page response. It does not bypass
the site's client/app gate or any authentication/paid access requirement.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urljoin, urlparse
from urllib.request import Request, urlopen

DEFAULT_URL = (
    "https://www.godic.net/webting/play?"
    "id=48001a07-89fa-11f1-816b-a50b30fa16fb&app=Ting"
)


def fetch(url: str) -> str:
    # On Windows, the bundled Python socket can be blocked by local policy
    # while the system curl client is allowed through the configured network.
    curl = shutil.which("curl.exe") or shutil.which("curl")
    if os.name == "nt" and Path(r"C:\Windows\System32\curl.exe").exists():
        curl = r"C:\Windows\System32\curl.exe"
    if curl:
        try:
            completed = subprocess.run(
                [curl, "--location", "--fail", "--silent", "--show-error", "--compressed",
                 "--max-time", "60", "--user-agent", "Mozilla/5.0 (compatible; transcript-extractor/1.0)",
                 "--header", "Accept-Language: zh-CN,zh;q=0.9,en;q=0.8", "--output", "-", url],
                capture_output=True,
                timeout=75,
                check=True,
            )
            return completed.stdout.decode("utf-8", errors="replace")
        except (OSError, subprocess.SubprocessError):
            pass

    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; transcript-extractor/1.0)",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        },
    )
    with urlopen(request, timeout=30) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


AUDIO_EXTENSIONS = re.compile(r"\.(?:mp3|m4a|aac|wav|ogg|oga|opus|webm)(?:[?#]|$)", re.I)
AUDIO_ATTRIBUTE_NAMES = {
    "audio",
    "audio-src",
    "audio-url",
    "audio_url",
    "data-audio",
    "data-audio-src",
    "data-audio-url",
    "data-src",
    "data-url",
    "media-src",
    "media-url",
    "media_url",
    "sound-url",
    "sound_url",
}


def _decode_url(value: str) -> str:
    """Undo the common HTML/JSON escaping used for URLs in inline scripts."""
    value = value.strip().strip("'\"")
    value = value.replace("\\/", "/")
    value = re.sub(r"\\u002f", "/", value, flags=re.I)
    value = re.sub(r"\\u003a", ":", value, flags=re.I)
    value = value.replace("&amp;", "&")
    return unquote(value)


class AudioParser(HTMLParser):
    """Collect audio-like URLs from HTML tags and data attributes."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.candidates = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        tag = tag.lower()
        for name, value in attrs.items():
            if not value:
                continue
            name = name.lower()
            if tag in {"audio", "source", "video"} and name in {"src", "data-src", "data-url"}:
                self.candidates.append((value, attrs.get("type", ""), f"<{tag} {name}>"))
            elif name in AUDIO_ATTRIBUTE_NAMES:
                self.candidates.append((value, attrs.get("type", ""), f"attribute {name}"))
            elif name in {"src", "href"} and AUDIO_EXTENSIONS.search(value):
                self.candidates.append((value, attrs.get("type", ""), f"<{tag} {name}>"))


def extract_audio(html: str, page_url: str) -> list[dict]:
    """Return publicly referenced audio files without executing page scripts."""
    parser = AudioParser()
    parser.feed(html)
    candidates = list(parser.candidates)

    # Some Godic pages assign the media URL inside a JavaScript object instead
    # of rendering an <audio> tag. Keep this deliberately narrow: only known
    # media keys and URLs with a conventional audio extension are accepted.
    for match in re.finditer(
        r"(?<![\w$])(?:audio(?:Url|URL|_url|Src|_src)?|sound(?:Url|URL|_url|Src|_src)?|media(?:Url|URL|_url|Src|_src)?)"
        r"\s*[:=]\s*[\"']([^\"']+)[\"']",
        html,
        flags=re.I,
    ):
        candidates.append((match.group(1), "", "inline script"))
    for match in re.finditer(
        r"[\"']((?:https?:)?//[^\"'<>\s]+?\.(?:mp3|m4a|aac|wav|ogg|oga|opus|webm)(?:\?[^\"'<>\s]*)?)[\"']",
        html,
        flags=re.I,
    ):
        candidates.append((match.group(1), "", "inline script"))

    result = []
    seen = set()
    for raw, mime, source in candidates:
        value = _decode_url(raw)
        if value.startswith("//"):
            value = f"{urlparse(page_url).scheme or 'https'}:{value}"
        absolute = urljoin(page_url, value)
        parsed = urlparse(absolute)
        if parsed.scheme not in {"http", "https"}:
            continue
        if not AUDIO_EXTENSIONS.search(absolute) and not source.startswith("inline") and "audio" not in source:
            continue
        if absolute in seen:
            continue
        seen.add(absolute)
        filename = Path(unquote(parsed.path)).name or "web-audio"
        result.append({
            "url": absolute,
            "filename": filename,
            "mime": mime or "",
            "source": source,
        })
    return result


class TranscriptParser(HTMLParser):
    """Small dependency-free parser for the page's paragraph/sentence markup."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []
        self.paragraph = None
        self.sentence = None
        self.in_translation = False
        self.body_text = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = set(attrs.get("class", "").split())
        if tag == "p" and "paragraph" in classes:
            self.paragraph = {"sentences": [], "translation": []}
        elif self.paragraph is not None and "sentence" in classes:
            self.sentence = {
                "start": attrs.get("data-starttime", ""),
                "end": attrs.get("data-endtime", ""),
                "text": [],
            }
            self.paragraph["sentences"].append(self.sentence)
        elif self.paragraph is not None and "trans" in classes:
            self.in_translation = True

    def handle_endtag(self, tag):
        if tag == "p" and self.paragraph is not None:
            sentences = self.paragraph["sentences"]
            translation = clean_text("".join(self.paragraph["translation"]))
            for sentence in sentences:
                self.rows.append({
                    "order": len(self.rows) + 1,
                    "start": sentence["start"],
                    "end": sentence["end"],
                    "german": clean_text("".join(sentence["text"])),
                    "translation": translation,
                })
            self.paragraph = None
            self.sentence = None
            self.in_translation = False
        elif tag == "span" and self.in_translation:
            self.in_translation = False

    def handle_data(self, data):
        self.body_text.append(data)
        if self.paragraph is None:
            return
        if self.in_translation:
            self.paragraph["translation"].append(data)
        elif self.sentence is not None:
            self.sentence["text"].append(data)


def extract(html: str, url: str) -> dict:
    # The page's visible article is only a preview. The complete transcript is
    # embedded in the page as `var translate = {...}`.
    audio = extract_audio(html, url)
    embedded = re.search(r"var\s+translate\s*=\s*(\{[\s\S]*?\})\s*;", html)
    if embedded:
        try:
            payload = json.loads(embedded.group(1))
            subtitles = payload.get("subtitles") or []
            if subtitles:
                rows = []
                for index, item in enumerate(subtitles, 1):
                    timestamps = item.get("timestamps") or []
                    rows.append(
                        {
                            "order": index,
                            "start": timestamps[0].strip("[]") if timestamps else "",
                            "end": timestamps[-1].strip("[]") if timestamps else "",
                            "german": (item.get("origintext") or "").strip(),
                            "translation": (item.get("translation") or "").strip(),
                        }
                    )
                return {
                    "url": url,
                    "title": "",
                    "count": len(rows),
                    "source": "embedded_translate.subtitles",
                    "embedded_subtitle_count": len(subtitles),
                    "embedded_paragraph_count": len(payload.get("paragraphs") or []),
                    "show_paywall": payload.get("show_paywall"),
                    "audition_time": payload.get("audition_time"),
                    "content_update_time": payload.get("content_update_time"),
                    "empty_origintext_count": sum(not (item.get("origintext") or "").strip() for item in subtitles),
                    "timestamp_count": sum(bool(item.get("timestamps")) for item in subtitles),
                    "first_text": rows[0]["german"],
                    "last_text": rows[-1]["german"],
                    "complete_transcript_in_response": True,
                    "audio": audio,
                    "items": rows,
                }
        except json.JSONDecodeError:
            pass

    # Fallback for pages that do not expose the embedded object.
    parser = TranscriptParser()
    parser.feed(html)
    body_text = clean_text(" ".join(parser.body_text))
    gated = bool(re.search(r"查看完整内容|查看全文|下载.*客户端", body_text))
    starts = [row["start"] for row in parser.rows]
    ordered = all(a <= b for a, b in zip(starts, starts[1:]))
    return {
        "url": url,
        "title": "",
        "count": len(parser.rows),
        "gated_by_site": gated,
        "complete_transcript_in_response": not gated,
        "items": parser.rows,
        "source_sentence_count": len(parser.rows),
        "source": "html.sentence",
        "timestamps_monotonic": ordered,
        "audio": audio,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", nargs="?", default=DEFAULT_URL)
    parser.add_argument("-o", "--output", type=Path, default=Path("godic_transcript"))
    parser.add_argument("--save-html", action="store_true", help="同时保存服务器返回的原始 HTML")
    parser.add_argument("--input-html", type=Path, help="直接解析已保存的 view-source HTML，不联网")
    args = parser.parse_args()

    try:
        html = args.input_html.read_text(encoding="utf-8") if args.input_html else fetch(args.url)
        result = extract(html, args.url)
    except (HTTPError, URLError, TimeoutError) as exc:
        print(f"抓取失败: {exc}", file=sys.stderr)
        return 1

    json_path = args.output.with_suffix(".json")
    txt_path = args.output.with_suffix(".txt")
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = []
    for item in result["items"]:
        stamp = f"[{item['start']}] " if item["start"] else ""
        lines.append(f"{stamp}{item['german']}")
        if item["translation"]:
            lines.append(f"中文：{item['translation']}")
        lines.append("")
    txt_path.write_text("\n".join(lines), encoding="utf-8")
    if args.save_html:
        args.output.with_suffix(".html").write_text(html, encoding="utf-8")

    print(f"提取 {result['count']} 段")
    if result.get("audio"):
        print("音频:")
        for audio in result["audio"]:
            print(f"  {audio['url']}")
    else:
        print("音频: 未在网页响应中发现公开音频地址")
    print(f"JSON: {json_path}")
    print(f"TXT:  {txt_path}")
    if args.save_html:
        print(f"HTML: {args.output.with_suffix('.html')}")
    if result.get("gated_by_site"):
        print("注意：页面检测到‘查看完整内容/客户端’限制；结果仅包含服务器公开下发的内容。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
