import sys
import time

class BaseBootUI:
    def update_global(self, percent: float, text: str): pass
    def update_local(self, percent: float, text: str): pass
    def close(self): pass

class CUIBootDriver(BaseBootUI):
    """Console dual-bar driver"""
    def __init__(self):
        self._bar_len = 50
        self._data: dict[str, dict[str, any]] = {"APP":{"p":0, "t":""}, "Tier":{"p":0, "t":""}}
        sys.stdout.write("\n\n")
        sys.stdout.flush()

    def _make_bar(self, percent):
        filled = int(self._bar_len * percent / 100)
        return "█" * filled + "-" * (self._bar_len - filled)

    def update_global(self, percent, text):
        self._data["APP"]["p"] = percent
        self._data["APP"]["t"] = text

    def update_local(self, percent, text):
        self._data["TIER"]["p"] = percent
        self._data["TIER"]["t"] = text

    def render(self) -> None:
        sys.stdout.write(f"\033[4F\r")
        for k, v in self._data.items():
            k = (k+":").ljust(5)
            sys.stdout.write(f"{k} [{self._make_bar(v["p"])}] {int(v["p"])}%\n")
            sys.stdout.write(f"      {v["t"]:<50}\n")
            sys.stdout.flush()

    def close(self):
        sys.stdout.write("\n\n--- Done ---\n")
        sys.stdout.flush()


class GUIBootDriver(BaseBootUI):
    """Tkinter dual-bar splash screen"""
    def __init__(self):
        import tkinter as tk
        from tkinter import ttk
        self.root = tk.Tk()
        self.root.title("sanapo System Control")
        self.root.geometry("450x160")
        self.root.attributes("-topmost", True)
        self.root.resizable(False, False)

        # Signature UI
        style = ttk.Style()
        style.theme_use('default')
        style.configure("sanapo.Horizontal.TProgressbar", thickness=15)

        # Global progress bar
        self.lbl_global = tk.Label(self.root, text="System Boot...", font=("Arial", 10, "bold"))
        self.lbl_global.pack(pady=(10, 0), padx=20, anchor="w")
        self.bar_global = ttk.Progressbar(self.root, length=400, mode='determinate',
                                          style="sanapo.Horizontal.TProgressbar")
        self.bar_global.pack(pady=5, padx=20)

        # Local proress bar
        self.lbl_local = tk.Label(self.root, text="Preparing units...", font=("Arial", 9))
        self.lbl_local.pack(pady=(5, 0), padx=20, anchor="w")
        self.bar_local = ttk.Progressbar(self.root, length=400, mode='determinate')
        self.bar_local.pack(pady=5, padx=20)
        
        self.root.update()

    def update_global(self, percent, text):
        self.lbl_global.config(text=text)
        self.bar_global['value'] = percent
        self.root.update()

    def update_local(self, percent, text):
        self.lbl_local.config(text=text)
        self.bar_local['value'] = percent
        self.root.update()

    def close(self):
        time.sleep(0.5)
        self.root.destroy()
