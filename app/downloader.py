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


class Downloader:
    """Handles metadata fetch and download for a single item, reporting
    progress dict events onto self.events (a queue.Queue)."""

    def __init__(self):
        self.events = queue.Queue()
        self._cancel_flag = threading.Event()

    def cancel(self):
        self._cancel_flag.set()

    def fetch_info(self, url):
        opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "extract_flat": "in_playlist",
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
        return info

    def _progress_hook(self, d):
        if self._cancel_flag.is_set():
            raise DownloadCancelled()
        status = d.get("status")
        if status == "downloading":
            self.events.put({
                "type": "progress",
                "percent_str": d.get("_percent_str", "").strip(),
                "downloaded": d.get("downloaded_bytes", 0),
                "total": d.get("total_bytes") or d.get("total_bytes_estimate") or 0,
                "speed": d.get("speed"),
                "eta": d.get("eta"),
                "filename": d.get("filename", ""),
            })
        elif status == "finished":
            self.events.put({"type": "converting", "filename": d.get("filename", "")})

    def download(self, url, output_dir, mode, quality, is_playlist):
        """mode: 'video' or 'audio'. quality: e.g. '1080', '720', 'best'
        for video, or '320', '192', '128' for audio (kbps)."""
        self._cancel_flag.clear()
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
            "quiet": True,
            "no_warnings": True,
            "restrictfilenames": False,
            "windowsfilenames": True,
            "ignoreerrors": is_playlist,
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
            self.events.put({"type": "done"})
        except DownloadCancelled:
            self.events.put({"type": "cancelled"})
        except Exception as exc:  # noqa: BLE001 - surface any yt-dlp error to the UI
            self.events.put({"type": "error", "message": str(exc)})
