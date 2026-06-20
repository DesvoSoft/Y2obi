import sys
import os
import tkinter as tk
from tkinter import messagebox
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


class FFmpegSplash:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Y2obi")
        self.root.geometry("420x160")
        self.root.resizable(False, False)
        self.root.configure(bg="#1a1a2e")

        self._center()

        title = tk.Label(self.root, text="Y2obi", font=("Segoe UI", 20, "bold"),
                         bg="#1a1a2e", fg="#e0e0e0")
        title.pack(pady=(20, 4))

        self.msg = tk.Label(self.root, text="Preparing...", font=("Segoe UI", 11),
                            bg="#1a1a2e", fg="#a0a0a0")
        self.msg.pack(pady=(0, 10))

        self.progress = tk.Canvas(self.root, width=320, height=6, bg="#2a2a3e",
                                  highlightthickness=0)
        self.progress.pack(pady=(0, 4))
        self._bar = self.progress.create_rectangle(0, 0, 0, 6, fill="#4fc3f7", width=0)

        self.pct_label = tk.Label(self.root, text="", font=("Segoe UI", 10),
                                  bg="#1a1a2e", fg="#707070")
        self.pct_label.pack()

        self._pct = 0
        self._error = None

    def _center(self):
        self.root.update_idletasks()
        w = self.root.winfo_width()
        h = self.root.winfo_height()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = (sw - w) // 2
        y = (sh - h) // 2
        self.root.geometry(f"{w}x{h}+{x}+{y}")

    def update(self, msg, pct=None):
        self.msg.config(text=msg)
        if pct is not None:
            self._pct = pct
            bw = int(320 * pct / 100)
            self.progress.coords(self._bar, 0, 0, bw, 6)
            self.pct_label.config(text=f"{pct:.0f}%")

    def set_error(self, msg):
        self._error = msg

    def close(self):
        self.root.destroy()


def main():
    splash = FFmpegSplash()
    result = {"path": None, "error": None}

    def _check():
        try:
            from app.binaries import ensure_ffmpeg
            path = ensure_ffmpeg(progress_cb=lambda m: splash.root.after(0, lambda: splash.update(m)))
            result["path"] = path
        except Exception as e:
            result["error"] = str(e)

    threading.Thread(target=_check, daemon=True).start()

    def _poll():
        if result["path"]:
            splash.close()
            _launch_app(result["path"])
            return
        if result["error"]:
            splash.close()
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror(
                "FFmpeg Error",
                f"Could not download FFmpeg:\n{result['error']}\n\n"
                "Install FFmpeg manually and add to PATH, or "
                "place ffmpeg.exe in the 'core' folder.",
            )
            root.destroy()
            sys.exit(1)
        splash.root.after(100, _poll)

    def _launch_app(ffmpeg_path):
        from app.downloader import Downloader
        from app.ui import App
        cookie_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cookies.txt")
        dl = Downloader(ffmpeg_path, cookies=cookie_path if os.path.exists(cookie_path) else None)
        app = App(dl)
        app.mainloop()

    splash.root.after(100, _poll)
    splash.root.mainloop()


if __name__ == "__main__":
    main()
