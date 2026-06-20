import sys
import os
import tkinter as tk
from tkinter import messagebox
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DESKTOP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "desktop")


class FFmpegSplash:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Y2obi")
        self.root.geometry("420x160")
        self.root.resizable(False, False)
        self.root.configure(bg="#1a1a2e")
        self._center()

        tk.Label(self.root, text="Y2obi", font=("Segoe UI", 20, "bold"),
                 bg="#1a1a2e", fg="#e0e0e0").pack(pady=(20, 4))

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

        self._error = None

    def _center(self):
        self.root.update_idletasks()
        w, h = self.root.winfo_width(), self.root.winfo_height()
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        self.root.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")

    def update(self, msg, pct=None):
        self.msg.config(text=msg)
        if pct is not None:
            bw = int(320 * pct / 100)
            self.progress.coords(self._bar, 0, 0, bw, 6)
            self.pct_label.config(text=f"{pct:.0f}%")

    def close(self):
        self.root.destroy()


def main():
    splash = FFmpegSplash()
    result = {"path": None, "error": None}

    def _check():
        try:
            from app.binaries import ensure_ffmpeg
            path = ensure_ffmpeg(progress_cb=lambda m: splash.root.after(0, lambda msg=m: splash.update(msg)))
            result["path"] = path
        except Exception as e:
            result["error"] = str(e)

    threading.Thread(target=_check, daemon=True).start()

    def _poll():
        if result["path"]:
            splash.close()
            _launch(result["path"])
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

    def _launch(ffmpeg_path):
        from app.server import start_server
        splash_root = tk.Tk()
        splash_root.withdraw()

        # Show a brief "Starting..." window while Flask boots
        loading = tk.Toplevel(splash_root)
        loading.title("Y2obi")
        loading.geometry("300x80")
        loading.resizable(False, False)
        loading.configure(bg="#1a1a2e")
        loading.update_idletasks()
        sw, sh = loading.winfo_screenwidth(), loading.winfo_screenheight()
        loading.geometry(f"300x80+{(sw-300)//2}+{(sh-80)//2}")
        tk.Label(loading, text="Starting Y2obi...", font=("Segoe UI", 12),
                 bg="#1a1a2e", fg="#e0e0e0").pack(expand=True)
        loading.update()

        port = start_server(ffmpeg_path, DESKTOP_DIR)
        url = f"http://127.0.0.1:{port}"

        loading.destroy()
        splash_root.destroy()

        import webview
        webview.create_window(
            "Y2obi",
            url,
            width=740,
            height=640,
            min_size=(620, 520),
            resizable=True,
        )
        webview.start()

    splash.root.after(100, _poll)
    splash.root.mainloop()


if __name__ == "__main__":
    main()
