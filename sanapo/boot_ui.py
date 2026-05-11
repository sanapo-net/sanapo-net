# sanapo/boot_ui.py
import sys

class BaseBootUI:
    def update(self, percent: float, text: str): pass
    def close(self): pass

class CUIBootDriver(BaseBootUI):
    """Console progress bar"""
    def update(self, percent: float, text: str):
        length = 25
        filled = int(length * percent / 100)
        bar = "█" * filled + "-" * (length - filled)
        sys.stdout.write(f"\rBOOT: [{bar}] {int(percent)}% | {text:<40}")
        sys.stdout.flush()

    def close(self):
        print("\n")

class GUIBootDriver(BaseBootUI):
    """Tkinter splash screen"""
    def __init__(self):
        import tkinter as tk
        from tkinter import ttk
        self.root = tk.Tk()
        self.root.title("sanapo")
        self.root.geometry("400x120")
        self.root.attributes("-topmost", True)
        self.lbl = tk.Label(self.root, text="Initializing...", font=("Arial", 10))
        self.lbl.pack(pady=10)
        self.bar = ttk.Progressbar(self.root, length=300, mode='determinate')
        self.bar.pack(pady=5)
        self.root.update()

    def update(self, percent: float, text: str):
        self.lbl.config(text=text)
        self.bar['value'] = percent
        self.root.update()

    def close(self):
        self.root.destroy()
