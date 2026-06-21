import customtkinter as ctk
from PIL import Image
import io
import urllib.request
import threading
import os
import traceback

from app.downloader import DownloadError, PlaylistError

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

FONT = ("Segoe UI", 13)
FONT_BOLD = ("Segoe UI", 14, "bold")
FONT_SMALL = ("Segoe UI", 11)
FONT_TINY = ("Segoe UI", 10)
PADX = 20
PADY = 10
BTN_W = 140


def _fmt_count(n):
    if not n:
        return ""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}K"
    return str(n)


def _fmt_speed(speed):
    if not speed:
        return ""
    if speed > 1048576:
        return f"{speed / 1048576:.1f} MB/s"
    if speed > 1024:
        return f"{speed / 1024:.0f} KB/s"
    return f"{speed:.0f} B/s"


def _fmt_eta(eta):
    if not eta:
        return ""
    if eta > 3600:
        return f"{eta // 3600}h {eta % 3600 // 60}m"
    if eta > 60:
        return f"{eta // 60}m {eta % 60}s"
    return f"{eta}s"


QUALITY_OPTIONS = ["Best", "1080p", "720p", "480p", "360p"]


class App(ctk.CTk):
    def __init__(self, downloader):
        super().__init__()
        self.downloader = downloader
        self.video_info = None
        self._current_url = None
        self._downloading = False
        self._last_error_details = None

        self.title("Y2obi")
        self.geometry("700x580")
        self.minsize(640, 500)
        self._center()

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self._build_url_row()
        self._build_info_panel()
        self._build_action_row()
        self._build_progress_panel()
        self._build_footer()

        self.url_entry.focus()
        self._update_btn_states()

    def _center(self):
        self.update_idletasks()
        w = self.winfo_width()
        h = self.winfo_height()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        x = (sw - w) // 2
        y = (sh - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")

    def _build_url_row(self):
        frame = ctk.CTkFrame(self, fg_color="transparent")
        frame.grid(row=0, column=0, padx=PADX, pady=(PADY, 0), sticky="ew")
        frame.grid_columnconfigure(0, weight=1)

        self.url_entry = ctk.CTkEntry(frame, placeholder_text="Paste YouTube URL here...", font=FONT, height=40)
        self.url_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.url_entry.bind("<Return>", lambda e: self.on_analyze())

        self.analyze_btn = ctk.CTkButton(frame, text="Analyze", font=FONT, height=40, width=110,
                                         command=self.on_analyze)
        self.analyze_btn.grid(row=0, column=1)

    def _build_info_panel(self):
        self.info_frame = ctk.CTkFrame(self)
        self.info_frame.grid(row=1, column=0, padx=PADX, pady=PADY, sticky="nsew")
        self.info_frame.grid_columnconfigure(1, weight=1)
        self.info_frame.grid_rowconfigure(3, weight=1)

        self.thumb_label = ctk.CTkLabel(self.info_frame, text="", width=160, height=90)
        self.thumb_label.grid(row=0, column=0, rowspan=4, padx=(10, 8), pady=10, sticky="n")

        self.title_label = ctk.CTkLabel(self.info_frame, text="No video analyzed", font=FONT_BOLD,
                                        wraplength=420, justify="left")
        self.title_label.grid(row=0, column=1, padx=(0, 10), pady=(10, 0), sticky="nw")

        self.channel_label = ctk.CTkLabel(self.info_frame, text="", font=FONT_SMALL,
                                          wraplength=420, justify="left")
        self.channel_label.grid(row=1, column=1, padx=(0, 10), pady=(2, 0), sticky="nw")

        self.meta_label = ctk.CTkLabel(self.info_frame, text="", font=FONT_SMALL,
                                       wraplength=420, justify="left")
        self.meta_label.grid(row=2, column=1, padx=(0, 10), pady=(2, 0), sticky="nw")

        qframe = ctk.CTkFrame(self.info_frame, fg_color="transparent")
        qframe.grid(row=3, column=1, padx=(0, 10), pady=(4, 10), sticky="nw")

        ctk.CTkLabel(qframe, text="Quality:", font=FONT_SMALL).pack(side="left", padx=(0, 6))

        self.quality_var = ctk.StringVar(value="Best")
        self.quality_combo = ctk.CTkComboBox(qframe, values=QUALITY_OPTIONS, variable=self.quality_var,
                                              width=100, font=FONT_TINY, state="readonly")
        self.quality_combo.pack(side="left")

        self.info_frame.grid_remove()

    def _build_action_row(self):
        frame = ctk.CTkFrame(self, fg_color="transparent")
        frame.grid(row=2, column=0, padx=PADX, pady=(0, PADY), sticky="ew")
        frame.grid_columnconfigure((0, 1), weight=1)

        self.mp4_btn = ctk.CTkButton(frame, text="Video HD", font=FONT, height=42,
                                     command=lambda: self._start_download("mp4"))
        self.mp4_btn.grid(row=0, column=0, padx=(0, 6), sticky="ew")

        self.mp3_btn = ctk.CTkButton(frame, text="MP3 Audio", font=FONT, height=42,
                                     command=lambda: self._start_download("mp3"))
        self.mp3_btn.grid(row=0, column=1, padx=(6, 6), sticky="ew")

        self.cancel_btn = ctk.CTkButton(frame, text="Cancel", font=FONT, height=42, width=100,
                                        fg_color="#5a2d2d", hover_color="#7a3d3d",
                                        command=self._cancel_download)
        self.cancel_btn.grid(row=0, column=2, padx=(6, 0))

    def _build_progress_panel(self):
        frame = ctk.CTkFrame(self)
        frame.grid(row=3, column=0, padx=PADX, pady=(0, PADY), sticky="ew")
        frame.grid_columnconfigure(0, weight=1)

        self.progress_bar = ctk.CTkProgressBar(frame, height=14, corner_radius=4)
        self.progress_bar.grid(row=0, column=0, padx=10, pady=(8, 2), sticky="ew")
        self.progress_bar.set(0)

        row1 = ctk.CTkFrame(frame, fg_color="transparent")
        row1.grid(row=1, column=0, padx=10, pady=(0, 2), sticky="ew")
        row1.grid_columnconfigure(1, weight=1)

        self.pct_label = ctk.CTkLabel(row1, text="", font=FONT_SMALL, anchor="w", width=45)
        self.pct_label.grid(row=0, column=0, sticky="w")

        self.status_label = ctk.CTkLabel(row1, text="Ready", font=FONT_SMALL, anchor="w")
        self.status_label.grid(row=0, column=1, sticky="w")

        self.speed_label = ctk.CTkLabel(row1, text="", font=FONT_TINY, anchor="e")
        self.speed_label.grid(row=0, column=2, sticky="e")

    def _build_footer(self):
        frame = ctk.CTkFrame(self, fg_color="transparent", height=10)
        frame.grid(row=4, column=0, padx=PADX, pady=(0, 4), sticky="ew")

        self.details_btn = ctk.CTkButton(frame, text="Details", font=FONT_TINY, width=70, height=22,
                                         fg_color="#3a3a4a", hover_color="#4a4a5a",
                                         command=self._show_error_details)
        self.details_btn.pack(side="left", padx=(0, 6))

        self.ontop_var = ctk.BooleanVar(value=False)
        self.ontop_chk = ctk.CTkCheckBox(frame, text="Always on Top", variable=self.ontop_var,
                                          font=FONT_TINY, command=self._toggle_ontop,
                                          checkbox_width=16, checkbox_height=16)
        self.ontop_chk.pack(side="right")

        self.details_btn.pack_forget()

    def _toggle_ontop(self):
        self.attributes("-topmost", self.ontop_var.get())

    def _show_error_details(self):
        if not self._last_error_details:
            return
        dlg = ctk.CTkToplevel(self)
        dlg.title("Error Details")
        dlg.geometry("600x400")
        dlg.transient(self)
        dlg.grab_set()

        txt = ctk.CTkTextbox(dlg, wrap="word", font=("Consolas", 11))
        txt.pack(fill="both", expand=True, padx=10, pady=10)
        txt.insert("1.0", self._last_error_details)
        txt.configure(state="disabled")

        ctk.CTkButton(dlg, text="Copy to Clipboard", font=FONT_SMALL,
                       command=lambda: self._copy_to_clip(self._last_error_details)).pack(pady=(0, 10))

    def _copy_to_clip(self, text):
        self.clipboard_clear()
        self.clipboard_append(text)
        self.status_label.configure(text="Copied to clipboard")

    def on_analyze(self):
        url = self.url_entry.get().strip()
        if not url:
            return
        self._last_error_details = None
        self.details_btn.pack_forget()
        self._current_url = url
        self._set_analyzing(True)
        threading.Thread(target=self._analyze, args=(url,), daemon=True).start()

    def _analyze(self, url):
        try:
            info = self.downloader.get_info(url)
            self.after(0, lambda: self._show_info(info))
        except PlaylistError as e:
            self._last_error_details = f"Type: PlaylistError\nURL: {url}\n\n{e}"
            self.after(0, lambda: self._show_error(str(e)))
        except DownloadError as e:
            self._last_error_details = f"Type: DownloadError\nURL: {url}\n\n{e}\n\n{traceback.format_exc()}"
            self.after(0, lambda: self._show_error(str(e)))
        except Exception as e:
            self._last_error_details = f"Type: {type(e).__name__}\nURL: {url}\n\n{e}\n\n{traceback.format_exc()}"
            self.after(0, lambda: self._show_error(str(e)))

    def _show_info(self, info):
        self.video_info = info
        self.title_label.configure(text=info.get("title", "Unknown"))
        self.channel_label.configure(text=info.get("channel", info.get("uploader", "")))

        parts = []
        dur = info.get("duration", 0)
        if dur:
            h, r = divmod(int(dur), 3600)
            m, s = divmod(r, 60)
            d = f"{h}h " if h else ""
            d += f"{m}m {s:02d}s"
            parts.append(d)

        views = info.get("view_count")
        if views:
            parts.append(f"{_fmt_count(views)} views")

        likes = info.get("like_count")
        if likes:
            parts.append(f"{_fmt_count(likes)} likes")

        self.meta_label.configure(text="  |  ".join(parts))

        thumb_url = info.get("thumbnail")
        if thumb_url:
            threading.Thread(target=self._load_thumb, args=(thumb_url,), daemon=True).start()

        self.info_frame.grid()
        self._update_btn_states()
        self._set_analyzing(False)
        self.status_label.configure(text="Ready to download")
        self.pct_label.configure(text="")
        self.speed_label.configure(text="")
        self.progress_bar.set(0)

    def _load_thumb(self, url):
        try:
            data = urllib.request.urlopen(url, timeout=10).read()
            img = Image.open(io.BytesIO(data))
            img.thumbnail((160, 90))
            photo = ctk.CTkImage(light_image=img, dark_image=img, size=(160, 90))
            self.after(0, lambda: self.thumb_label.configure(image=photo, text=""))
        except Exception:
            pass

    def _show_error(self, msg):
        self._set_analyzing(False)
        self.video_info = None
        self.info_frame.grid_remove()
        self.status_label.configure(text=f"Error: {msg}")
        self.thumb_label.configure(image="", text="")
        if self._last_error_details:
            self.details_btn.pack(side="left", padx=(0, 6))
        self._update_btn_states()

    def _set_analyzing(self, busy):
        if busy:
            self.analyze_btn.configure(state="disabled", text="Analyzing...")
            self.status_label.configure(text="Fetching video info...")
        else:
            self.analyze_btn.configure(state="normal", text="Analyze")

    def _start_download(self, fmt):
        if not self.video_info or not self._current_url or self._downloading:
            return
        self._last_error_details = None
        self.details_btn.pack_forget()
        self._downloading = True
        self._update_btn_states()

        output_dir = os.path.join(os.path.expanduser("~"), "Videos", "Y2obi")
        os.makedirs(output_dir, exist_ok=True)

        quality = self.quality_var.get() if fmt == "mp4" else "Best"

        self.downloader.set_callbacks(
            progress=self._on_progress,
            status=self._on_status,
            complete=lambda p: self.after(0, lambda: self._on_complete(p, fmt)),
        )
        threading.Thread(target=self._download, args=(fmt, quality, self._current_url, output_dir), daemon=True).start()

    def _download(self, fmt, quality, url, output_dir):
        try:
            if fmt == "mp4":
                path = self.downloader.download_mp4(url, output_dir, quality)
            else:
                path = self.downloader.download_mp3(url, output_dir)
            if self.downloader._complete_cb:
                self.downloader._complete_cb(path)
        except DownloadError as e:
            self._last_error_details = f"Type: {type(e).__name__}\nFormat: {fmt}\nQuality: {quality}\nURL: {url}\n\n{e}\n\n{traceback.format_exc()}"
            self.after(0, lambda: self._show_dl_error(str(e)))
        except Exception as e:
            self._last_error_details = f"Type: {type(e).__name__}\nFormat: {fmt}\nQuality: {quality}\nURL: {url}\n\n{e}\n\n{traceback.format_exc()}"
            self.after(0, lambda: self._show_dl_error(str(e)))

    def _cancel_download(self):
        self.downloader.cancel()
        self._on_status("Cancelling...")

    def _on_progress(self, pct, speed, eta):
        self.after(0, lambda: self.progress_bar.set(pct / 100))
        self.after(0, lambda: self.pct_label.configure(text=f"{pct:.0f}%"))
        spd = _fmt_speed(speed)
        et = _fmt_eta(eta)
        self.after(0, lambda: self.speed_label.configure(text=f"{spd}  {et}" if spd and et else spd or et or ""))

    def _on_status(self, msg):
        self.after(0, lambda: self.status_label.configure(text=msg))

    def _on_complete(self, path, fmt):
        self.progress_bar.set(1.0)
        self.pct_label.configure(text="100%")
        label = "Video" if fmt == "mp4" else "Audio"
        self.status_label.configure(text=f"{label} saved to ~/Videos/Y2obi/")
        self.speed_label.configure(text="Done")
        self._downloading = False
        self._update_btn_states()
        try:
            os.startfile(os.path.dirname(path))
        except Exception:
            pass

    def _show_dl_error(self, msg):
        is_cancel = "Cancelled" in msg
        self.status_label.configure(text="Cancelled" if is_cancel else f"Download error: {msg}")
        self.speed_label.configure(text="")
        self.pct_label.configure(text="")
        self.progress_bar.set(0)
        self._downloading = False
        if not is_cancel and self._last_error_details:
            self.details_btn.pack(side="left", padx=(0, 6))
        self._update_btn_states()

    def _update_btn_states(self):
        has_info = self.video_info is not None
        if self._downloading:
            self.mp4_btn.configure(state="disabled")
            self.mp3_btn.configure(state="disabled")
            self.analyze_btn.configure(state="disabled")
            self.cancel_btn.configure(state="normal")
            self.quality_combo.configure(state="disabled")
        else:
            self.mp4_btn.configure(state="normal" if has_info else "disabled")
            self.mp3_btn.configure(state="normal" if has_info else "disabled")
            self.analyze_btn.configure(state="normal")
            self.cancel_btn.configure(state="disabled")
            self.quality_combo.configure(state="readonly" if has_info else "normal")
