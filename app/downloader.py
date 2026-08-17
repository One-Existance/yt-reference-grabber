"""Download engine wrapping yt-dlp. Runs in a worker thread and reports
progress back to the GUI through a thread-safe queue."""

import os
import queue
import shutil
import threading

import yt_dlp


class DownloadCancelled(Exception):
    pass


def find_ffmpeg():
    """Return a directory containing ffmpeg.exe, or None if not found on PATH."""
    path = shutil.which("ffmpeg")
    if path:
        return os.path.dirname(path)
    return None


def find_node():
    """Return True if a node.js runtime is available on PATH.

    YouTube requires solving a JS "n challenge" to get working download
    URLs; yt-dlp needs a JS runtime (node) for this, plus permission to
    fetch its challenge-solver script (see remote_components below)."""
    return shutil.which("node") is not None


POSTPROCESSOR_LABELS = {
    "Merger": "Merging video and audio...",
    "FFmpegExtractAudio": "Converting to MP3...",
    "FFmpegVideoConvertor": "Converting video...",
    "MoveFiles": "Finalizing...",
}


def _stream_label(info_dict):
    vcodec = info_dict.get("vcodec")
    acodec = info_dict.get("acodec")
    has_video = vcodec and vcodec != "none"
    has_audio = acodec and acodec != "none"
    if has_video and not has_audio:
        return "video stream"
    if has_audio and not has_video:
        return "audio stream"
    return "file"


class Downloader:
    """Handles metadata fetch and download for a single item, reporting
    progress dict events onto self.events (a queue.Queue)."""

    def __init__(self):
        self.events = queue.Queue()
        self._cancel_flag = threading.Event()
        self._last_filepath = None

    def cancel(self):
        self._cancel_flag.set()

    def fetch_info(self, url):
        opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "extract_flat": "in_playlist",
            "js_runtimes": {"deno": {}, "node": {}},
            "remote_components": ["ejs:github"],
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
        return info

    def _progress_hook(self, d):
        if self._cancel_flag.is_set():
            raise DownloadCancelled()
        status = d.get("status")
        info = d.get("info_dict") or {}
        if status == "downloading":
            self.events.put({
                "type": "progress",
                "stream": _stream_label(info),
                "percent_str": d.get("_percent_str", "").strip(),
                "downloaded": d.get("downloaded_bytes", 0),
                "total": d.get("total_bytes") or d.get("total_bytes_estimate") or 0,
                "speed": d.get("speed"),
                "eta": d.get("eta"),
            })
        elif status == "finished":
            self._last_filepath = d.get("filename") or self._last_filepath
            self.events.put({"type": "stage", "message": "Processing..."})

    def _postprocessor_hook(self, d):
        status = d.get("status")
        pp = d.get("postprocessor", "")
        if status == "started":
            label = POSTPROCESSOR_LABELS.get(pp, f"Running {pp}...")
            self.events.put({"type": "stage", "message": label})
        elif status == "finished":
            info = d.get("info_dict") or {}
            filepath = info.get("filepath")
            if filepath:
                self._last_filepath = filepath

    def download(self, url, output_dir, mode, quality, is_playlist):
        """mode: 'video' or 'audio'. quality: e.g. '1080', '720', 'best'
        for video, or '320', '192', '128' for audio (kbps)."""
        self._cancel_flag.clear()
        self._last_filepath = None
        os.makedirs(output_dir, exist_ok=True)

        if is_playlist:
            outtmpl = os.path.join(output_dir, "%(playlist_title)s",
                                    "%(playlist_index)s - %(title)s.%(ext)s")
        else:
            outtmpl = os.path.join(output_dir, "%(title)s.%(ext)s")

        ffmpeg_dir = find_ffmpeg()

        opts = {
            "outtmpl": outtmpl,
            "noplaylist": not is_playlist,
            "progress_hooks": [self._progress_hook],
            "postprocessor_hooks": [self._postprocessor_hook],
            "quiet": True,
            "no_warnings": True,
            "restrictfilenames": False,
            "windowsfilenames": True,
            "ignoreerrors": is_playlist,
            "js_runtimes": {"deno": {}, "node": {}},
            "remote_components": ["ejs:github"],
        }
        if ffmpeg_dir:
            opts["ffmpeg_location"] = ffmpeg_dir

        if mode == "audio":
            opts["format"] = "bestaudio/best"
            opts["postprocessors"] = [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": quality,
            }]
        else:
            if quality == "best":
                opts["format"] = "bestvideo+bestaudio/best"
            else:
                opts["format"] = (
                    f"bestvideo[height<={quality}]+bestaudio/best[height<={quality}]"
                )
            opts["merge_output_format"] = "mp4"

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
            self.events.put({
                "type": "done",
                "filepath": self._last_filepath,
                "output_dir": output_dir,
                "is_playlist": is_playlist,
            })
        except DownloadCancelled:
            self.events.put({"type": "cancelled"})
        except Exception as exc:  # noqa: BLE001 - surface any yt-dlp error to the UI
            self.events.put({"type": "error", "message": str(exc)})
