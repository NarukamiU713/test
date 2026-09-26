# Godic Transcript Extractor

Paste a Godic listening URL to extract the complete German transcript from the page's embedded `translate.subtitles` payload.

## Render

This repository includes `render.yaml`. In Render, create a Blueprint from this repository. The service runs `python app.py`, binds to `0.0.0.0`, and reads Render's `PORT` environment variable.

The app only parses data publicly returned by the target page. It does not bypass login, payment, or access controls.
