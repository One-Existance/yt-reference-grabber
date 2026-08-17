# YT Reference Grabber

A small Windows desktop app for downloading YouTube videos and audio to use
as local reference material (e.g. clips to tag/reference in your own YouTube
videos).

## Using the app

Just double-click **`dist\YT Reference Grabber.exe`** (or the desktop
shortcut). No Python install needed on this PC — everything is bundled.

1. Paste a YouTube video (or playlist) URL and click **Fetch**.
2. Choose **video** (MP4, pick a quality) or **audio** (MP3, pick a bitrate).
3. If it's a playlist, check "Download entire playlist" to grab all of it.
4. Pick an output folder (defaults to `Videos\YT Reference Downloads`).
5. Click **Download** and watch progress in the status bar / activity log.

## Requirements

- FFmpeg must be installed and on PATH (already set up on this machine via
  `winget install Gyan.FFmpeg`) — it's used to merge video+audio streams and
  to convert audio to MP3.
- Node.js must be installed and on PATH (already set up via
  `winget install OpenJS.NodeJS`, or was present already) — yt-dlp uses it
  to solve YouTube's JavaScript "n challenge" that gates download URLs.

## Troubleshooting: downloads fail with 403 Forbidden / "DRM protected"

YouTube periodically changes how it gates video URLs, and `yt-dlp` has to
keep up. If downloads start failing:

1. Update to the latest `yt-dlp` nightly build (fixes for YouTube breakage
   usually land here first, days before a stable PyPI release):
   ```
   venv\Scripts\python.exe -m pip install -U --pre yt-dlp
   ```
2. Make sure Node.js is installed (see Requirements above) — `downloader.py`
   passes `js_runtimes: {"deno": {}, "node": {}}` and
   `remote_components: ["ejs:github"]` to yt-dlp so it can fetch and run the
   JS challenge solver it needs against current YouTube pages.
3. Rebuild the exe (see below) so the fix is baked into the packaged app.

## Developing / rebuilding

Source lives in `app/main.py` (GUI) and `app/downloader.py` (yt-dlp wrapper).

```
venv\Scripts\python.exe app\main.py          # run from source
venv\Scripts\python.exe -m pip install -r requirements.txt   # deps
```

To rebuild the standalone exe after code changes:

```
venv\Scripts\python.exe -m PyInstaller --noconfirm --onefile --windowed --name "YT Reference Grabber" --collect-all customtkinter --paths app app/main.py
```

The output lands in `dist\YT Reference Grabber.exe`.

## A note on usage

This tool downloads from YouTube using `yt-dlp`. Downloading is subject to
YouTube's Terms of Service and applicable copyright law — use it for
personal, fair-use reference purposes (like this project's intent: pulling
clips to reference/tag in your own original videos), not for redistributing
others' content.
