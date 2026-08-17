"""YT Reference Grabber - a small desktop app for downloading YouTube
videos and audio for use as personal reference/tagging material."""

import os
import queue
import subprocess
import threading
import urllib.request
from io import BytesIO

import customtkinter as ctk
from tkinter import filedialog, messagebox

from downloader import Downloader, find_ffmpeg, find_node
from settings import load_settings, save_settings

try:
    from PIL import Image
except ImportError:
    Image = None

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

DEFAULT_OUTPUT_DIR = os.path.join(os.path.expanduser("~"), "Videos", "YT Reference Downloads")

VIDEO_QUALITIES = [("Best available", "best"), ("1080p", "1080"), ("720p", "720"),
                    ("480p", "480"), ("360p", "360")]
AUDIO_QUALITIES = [("320 kbps", "320"), ("192 kbps", "192"), ("128 kbps", "128")]


def format_bytes(n):
    if not n:
        return "?"
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def format_eta(seconds):
    if seconds is None:
        return "?"
    seconds = int(seconds)
    m, s = divmod(seconds, 60)
    return f"{m:02d}:{s:02d}"


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("YT Reference Grabber")
        self.geometry("760x680")
        self.minsize(680, 580)

        self.downloader = Downloader()
        self.current_info = None
        self.thumb_image = None
        self.settings = load_settings()
        self.output_dir = self.settings.get("output_dir") or DEFAULT_OUTPUT_DIR
        self.is_downloading = False
        self.progress_bar_mode = "determinate"

        self.last_filepath = None
        self.last_output_dir = None
        self.last_is_playlist = False

        self._build_ui()
        self._poll_events()

        if not find_ffmpeg() or not find_node():
            self.after(300, self._warn_missing_deps)

    # ---------- UI construction ----------

    def _build_ui(self):
        pad = {"padx": 16, "pady": 8}

        header = ctk.CTkLabel(self, text="YT Reference Grabber",
                               font=ctk.CTkFont(size=22, weight="bold"))
        header.pack(anchor="w", padx=16, pady=(16, 0))

        sub = ctk.CTkLabel(self, text="Download YouTube videos or audio for reference material",
                            text_color="gray60")
        sub.pack(anchor="w", padx=16, pady=(0, 12))

        # URL row
        url_frame = ctk.CTkFrame(self, fg_color="transparent")
        url_frame.pack(fill="x", **pad)
        self.url_entry = ctk.CTkEntry(url_frame, placeholder_text="Paste a YouTube video or playlist URL...")
        self.url_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.fetch_btn = ctk.CTkButton(url_frame, text="Fetch", width=90, command=self.on_fetch)
        self.fetch_btn.pack(side="left")

        # Info panel
        info_frame = ctk.CTkFrame(self)
        info_frame.pack(fill="x", **pad)
        self.thumb_label = ctk.CTkLabel(info_frame, text="", width=160, height=90)
        self.thumb_label.grid(row=0, column=0, rowspan=3, padx=12, pady=12)

        self.title_label = ctk.CTkLabel(info_frame, text="No video loaded yet",
                                         font=ctk.CTkFont(size=15, weight="bold"),
                                         anchor="w", justify="left", wraplength=520)
        self.title_label.grid(row=0, column=1, sticky="w", padx=8, pady=(12, 0))

        self.meta_label = ctk.CTkLabel(info_frame, text="", text_color="gray60", anchor="w")
        self.meta_label.grid(row=1, column=1, sticky="w", padx=8)

        self.playlist_var = ctk.BooleanVar(value=False)
        self.playlist_check = ctk.CTkCheckBox(info_frame, text="Download entire playlist",
                                               variable=self.playlist_var, state="disabled")
        self.playlist_check.grid(row=2, column=1, sticky="w", padx=8, pady=(4, 12))

        info_frame.grid_columnconfigure(1, weight=1)

        # Options row
        opts_frame = ctk.CTkFrame(self, fg_color="transparent")
        opts_frame.pack(fill="x", **pad)

        self.mode_var = ctk.StringVar(value="video")
        mode_seg = ctk.CTkSegmentedButton(opts_frame, values=["video", "audio"],
                                           variable=self.mode_var, command=self.on_mode_change)
        mode_seg.pack(side="left")

        self.quality_var = ctk.StringVar(value=VIDEO_QUALITIES[0][0])
        self.quality_menu = ctk.CTkOptionMenu(opts_frame, variable=self.quality_var,
                                               values=[q[0] for q in VIDEO_QUALITIES])
        self.quality_menu.pack(side="left", padx=12)

        # Output folder row
        out_frame = ctk.CTkFrame(self, fg_color="transparent")
        out_frame.pack(fill="x", **pad)
        ctk.CTkLabel(out_frame, text="Default save folder:", text_color="gray60").pack(anchor="w")
        out_row = ctk.CTkFrame(out_frame, fg_color="transparent")
        out_row.pack(fill="x", pady=(2, 0))
        self.out_label = ctk.CTkLabel(out_row, text=self.output_dir, text_color="gray60", anchor="w")
        self.out_label.pack(side="left", fill="x", expand=True)
        browse_btn = ctk.CTkButton(out_row, text="Change folder", width=120, command=self.on_browse)
        browse_btn.pack(side="right")

        # Download button + progress
        action_frame = ctk.CTkFrame(self, fg_color="transparent")
        action_frame.pack(fill="x", **pad)
        self.download_btn = ctk.CTkButton(action_frame, text="Download", height=40,
                                           font=ctk.CTkFont(size=14, weight="bold"),
                                           command=self.on_download)
        self.download_btn.pack(side="left", fill="x", expand=True, padx=(0, 8))

        self.open_location_btn = ctk.CTkButton(action_frame, text="Open File Location", height=40,
                                                width=160, state="disabled",
                                                fg_color="gray30", hover_color="gray25",
                                                command=self.on_open_location)
        self.open_location_btn.pack(side="right")

        self.progress_bar = ctk.CTkProgressBar(self)
        self.progress_bar.set(0)
        self.progress_bar.pack(fill="x", padx=16, pady=(8, 4))

        self.stage_label = ctk.CTkLabel(self, text="Ready.", anchor="w",
                                         font=ctk.CTkFont(size=13, weight="bold"))
        self.stage_label.pack(fill="x", padx=16)

        self.detail_label = ctk.CTkLabel(self, text="", text_color="gray60", anchor="w")
        self.detail_label.pack(fill="x", padx=16, pady=(0, 4))

        # Log box
        log_frame = ctk.CTkFrame(self)
        log_frame.pack(fill="both", expand=True, padx=16, pady=(12, 16))
        ctk.CTkLabel(log_frame, text="Activity", anchor="w").pack(anchor="w", padx=8, pady=(6, 0))
        self.log_box = ctk.CTkTextbox(log_frame, height=140, state="disabled")
        self.log_box.pack(fill="both", expand=True, padx=8, pady=8)

    # ---------- helpers ----------

    def log(self, message):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", message + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def on_mode_change(self, mode):
        values = VIDEO_QUALITIES if mode == "video" else AUDIO_QUALITIES
        self.quality_menu.configure(values=[q[0] for q in values])
        self.quality_var.set(values[0][0])

    def on_browse(self):
        chosen = filedialog.askdirectory(initialdir=self.output_dir)
        if chosen:
            self.output_dir = chosen
            self.out_label.configure(text=self.output_dir)
            self.settings["output_dir"] = self.output_dir
            save_settings(self.settings)
            self.log(f"Default save folder set to {self.output_dir}")

    def _warn_missing_deps(self):
        missing = []
        if not find_ffmpeg():
            missing.append("FFmpeg (needed to merge video/audio and convert to MP3)")
        if not find_node():
            missing.append("Node.js (needed to solve YouTube's JS challenge)")
        messagebox.showwarning(
            "Missing dependency",
            "Not found on your PATH:\n\n- " + "\n- ".join(missing) +
            "\n\nDownloads will likely fail without these. If you just "
            "installed one, restart this app so the updated PATH takes effect."
        )

    def _set_progress_determinate(self, fraction):
        if self.progress_bar_mode != "determinate":
            self.progress_bar.stop()
            self.progress_bar.configure(mode="determinate")
            self.progress_bar_mode = "determinate"
        self.progress_bar.set(fraction)

    def _set_progress_indeterminate(self):
        if self.progress_bar_mode != "indeterminate":
            self.progress_bar.configure(mode="indeterminate")
            self.progress_bar.start()
            self.progress_bar_mode = "indeterminate"

    # ---------- fetch info ----------

    def on_fetch(self):
        url = self.url_entry.get().strip()
        if not url:
            return
        self.fetch_btn.configure(state="disabled", text="Loading...")
        self.stage_label.configure(text="Fetching video info...")
        self.detail_label.configure(text="")
        threading.Thread(target=self._fetch_worker, args=(url,), daemon=True).start()

    def _fetch_worker(self, url):
        try:
            info = self.downloader.fetch_info(url)
        except Exception as exc:  # noqa: BLE001
            self.after(0, lambda: self._fetch_failed(str(exc)))
            return
        self.after(0, lambda: self._fetch_done(info))

    def _fetch_failed(self, message):
        self.fetch_btn.configure(state="normal", text="Fetch")
        self.stage_label.configure(text="Failed to fetch info.")
        self.log(f"Error: {message}")
        messagebox.showerror("Couldn't load video", message)

    def _fetch_done(self, info):
        self.current_info = info
        self.fetch_btn.configure(state="normal", text="Fetch")
        self.stage_label.configure(text="Ready.")

        is_playlist = info.get("_type") == "playlist" or "entries" in info
        if is_playlist:
            entries = list(info.get("entries") or [])
            count = len(entries)
            title = info.get("title") or "Playlist"
            self.title_label.configure(text=title)
            self.meta_label.configure(text=f"Playlist - {count} videos")
            self.playlist_check.configure(state="normal")
            self.playlist_var.set(True)
            self._set_thumbnail(None)
        else:
            title = info.get("title") or "Untitled"
            uploader = info.get("uploader") or ""
            duration = info.get("duration")
            duration_str = self._format_duration(duration) if duration else ""
            self.title_label.configure(text=title)
            self.meta_label.configure(text=" | ".join(x for x in [uploader, duration_str] if x))
            self.playlist_check.configure(state="disabled")
            self.playlist_var.set(False)
            self._set_thumbnail(info.get("thumbnail"))

        self.log(f"Loaded: {title}")

    def _format_duration(self, seconds):
        seconds = int(seconds)
        h, rem = divmod(seconds, 3600)
        m, s = divmod(rem, 60)
        if h:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m}:{s:02d}"

    def _set_thumbnail(self, url):
        self.thumb_image = None
        self.thumb_label.configure(image=None, text="")
        if not url or Image is None:
            return

        def worker():
            try:
                with urllib.request.urlopen(url, timeout=10) as resp:
                    data = resp.read()
                img = Image.open(BytesIO(data)).convert("RGB")
                img.thumbnail((160, 90))
                ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=img.size)
                self.after(0, lambda: self._apply_thumbnail(ctk_img))
            except Exception:
                pass

        threading.Thread(target=worker, daemon=True).start()

    def _apply_thumbnail(self, ctk_img):
        self.thumb_image = ctk_img
        self.thumb_label.configure(image=ctk_img, text="")

    # ---------- download ----------

    def on_download(self):
        if self.is_downloading:
            return
        url = self.url_entry.get().strip()
        if not url:
            messagebox.showinfo("No URL", "Paste a YouTube URL first.")
            return
        if not find_ffmpeg() or not find_node():
            self._warn_missing_deps()
            return

        mode = self.mode_var.get()
        quality_label = self.quality_var.get()
        table = VIDEO_QUALITIES if mode == "video" else AUDIO_QUALITIES
        quality = dict((label, val) for label, val in table)[quality_label]
        is_playlist = self.playlist_var.get()

        self.is_downloading = True
        self.open_location_btn.configure(state="disabled")
        self.download_btn.configure(state="disabled", text="Downloading...")
        self._set_progress_determinate(0)
        self.stage_label.configure(text="Starting download...")
        self.detail_label.configure(text="")
        self.log(f"Downloading ({mode}, {quality_label})...")

        threading.Thread(
            target=self.downloader.download,
            args=(url, self.output_dir, mode, quality, is_playlist),
            daemon=True,
        ).start()

    def on_open_location(self):
        if self.last_filepath and os.path.isfile(self.last_filepath):
            subprocess.run(["explorer", f"/select,{self.last_filepath}"])
        elif self.last_output_dir and os.path.isdir(self.last_output_dir):
            os.startfile(self.last_output_dir)
        else:
            messagebox.showinfo("Not available", "No completed download to show yet.")

    def _poll_events(self):
        try:
            while True:
                event = self.downloader.events.get_nowait()
                self._handle_event(event)
        except queue.Empty:
            pass
        self.after(150, self._poll_events)

    def _handle_event(self, event):
        etype = event["type"]
        if etype == "progress":
            total = event.get("total") or 0
            downloaded = event.get("downloaded") or 0
            stream = event.get("stream", "file")
            pct = event.get("percent_str") or ""
            speed = event.get("speed")
            speed_str = f"{format_bytes(speed)}/s" if speed else "?/s"
            eta_str = format_eta(event.get("eta"))

            if total:
                self._set_progress_determinate(min(downloaded / total, 1.0))
            else:
                self._set_progress_indeterminate()

            self.stage_label.configure(text=f"Downloading {stream}... {pct}".strip())
            self.detail_label.configure(
                text=f"{format_bytes(downloaded)} / {format_bytes(total)}  •  {speed_str}  •  ETA {eta_str}"
            )
        elif etype == "stage":
            self._set_progress_indeterminate()
            self.stage_label.configure(text=event.get("message", "Processing..."))
            self.detail_label.configure(text="")
        elif etype == "done":
            self.is_downloading = False
            self.download_btn.configure(state="normal", text="Download")
            self._set_progress_determinate(1.0)
            self.stage_label.configure(text="Done.")

            self.last_filepath = event.get("filepath")
            self.last_output_dir = event.get("output_dir")
            self.last_is_playlist = event.get("is_playlist", False)
            self.open_location_btn.configure(state="normal")

            if self.last_filepath:
                self.detail_label.configure(text=os.path.basename(self.last_filepath))
                self.log(f"Saved: {self.last_filepath}")
            else:
                self.detail_label.configure(text=self.last_output_dir or "")
                self.log(f"Saved to {self.last_output_dir}")
        elif etype == "cancelled":
            self.is_downloading = False
            self.download_btn.configure(state="normal", text="Download")
            self._set_progress_determinate(0)
            self.stage_label.configure(text="Cancelled.")
            self.detail_label.configure(text="")
        elif etype == "error":
            self.is_downloading = False
            self.download_btn.configure(state="normal", text="Download")
            self._set_progress_determinate(0)
            self.stage_label.configure(text="Error.")
            self.detail_label.configure(text="")
            self.log(f"Error: {event.get('message')}")
            messagebox.showerror("Download failed", event.get("message", "Unknown error"))


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
