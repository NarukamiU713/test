# Godic Transcript Extractor

Paste a Godic listening URL to extract the complete German transcript from the page's embedded `translate.subtitles` payload.

## Audio playback

When the target page publicly exposes an audio URL, the app displays an HTML5 player and streams it through `/api/audio`. The proxy forwards `Range`, `Referer`, and the upstream media headers so seeking and playback work more reliably when the original host blocks cross-origin requests or direct browser requests. The original URL is still available as a fallback link.

The Godic desktop player commonly stores the media endpoint in `Webting_play.initPlayPage(...)` instead of an `<audio src>` attribute. The parser recognizes that extensionless `api.frdic.com` URL and infers its MP3 type from the query string.

If the server response contains no public audio URL, the app reports that clearly instead of inventing a playable link. It does not bypass login, payment, client-only playback, or dynamic access controls.

## Render

This repository includes `render.yaml`. In Render, create a Blueprint from this repository. The service runs `python app.py`, binds to `0.0.0.0`, and reads Render's `PORT` environment variable.

The app only parses data publicly returned by the target page. It does not bypass login, payment, or access controls.
