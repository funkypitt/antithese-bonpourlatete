#!/usr/bin/env python3
"""
antithese_gui.py — GUI launcher for Antithèse Interactive Edition Builder

Embeds a VT100 terminal emulator (pyte) in a tkinter window so that
the interactive script runs without a system terminal.
Works on Linux and macOS.
"""

import fcntl
import os
import pty
import select
import signal
import struct
import subprocess
import sys
import termios
import tkinter as tk
from tkinter import font as tkfont

import pyte


def _inherit_login_env():
    """Source login-shell environment so GUI-launched children see
    variables like ANTITHESE_USER / ANTITHESE_PASS from .bashrc/.zshrc."""
    try:
        shell = os.environ.get("SHELL", "/bin/bash")
        out = subprocess.run(
            [shell, "-lc", "env"],
            capture_output=True, text=True, timeout=5,
        ).stdout
        for line in out.splitlines():
            k, sep, v = line.partition("=")
            if sep and k not in os.environ:
                os.environ[k] = v
    except Exception:
        pass


_inherit_login_env()

# -- ANSI color palette ----------------------------------------------------

_COLORS = {
    "black": "#000000", "red": "#cd0000", "green": "#00cd00",
    "brown": "#cdcd00", "blue": "#0000ee", "magenta": "#cd00cd",
    "cyan": "#00cdcd", "white": "#e5e5e5",
    "brightblack": "#7f7f7f", "brightred": "#ff0000",
    "brightgreen": "#00ff00", "brightyellow": "#ffff00",
    "brightblue": "#5c5cff", "brightmagenta": "#ff00ff",
    "brightcyan": "#00ffff", "brightwhite": "#ffffff",
}
_ANSI_NAMES = (
    "black", "red", "green", "brown", "blue", "magenta", "cyan", "white")
_FG = "#d4d4d4"
_BG = "#0a0a14"


def _color_hex(c, bright=False):
    """Resolve a pyte color value to a hex string."""
    if isinstance(c, str) and c != "default":
        key = ("bright" + c) if bright else c
        return _COLORS.get(key, _COLORS.get(c))
    if isinstance(c, int):
        if c < 8:
            return _COLORS.get(
                ("bright" + _ANSI_NAMES[c]) if bright else _ANSI_NAMES[c])
        if c < 16:
            return _COLORS.get("bright" + _ANSI_NAMES[c - 8])
        if c < 232:  # 216-color cube
            i = c - 16
            return (f"#{(i // 36) * 51:02x}"
                    f"{((i % 36) // 6) * 51:02x}"
                    f"{(i % 6) * 51:02x}")
        g = 8 + (c - 232) * 10  # grayscale
        return f"#{g:02x}{g:02x}{g:02x}"
    return None


# -- Terminal emulator widget ----------------------------------------------

class TerminalApp:
    COLS, ROWS = 110, 42
    _KEYMAP = {
        "Up": "\033[A", "Down": "\033[B",
        "Right": "\033[C", "Left": "\033[D",
        "Delete": "\033[3~", "Prior": "\033[5~", "Next": "\033[6~",
        "Home": "\033[H", "End": "\033[F",
        "BackSpace": "\x7f", "Escape": "\x1b", "Tab": "\t",
    }

    def __init__(self, command):
        self.command = command
        self.master_fd = None
        self.child_pid = None
        self.mouse_tracking = False
        self._tags: dict[tuple, str] = {}

        # -- Tk root --
        self.root = tk.Tk()
        self.root.title("Antithèse — Bon pour la tête")
        self.root.configure(bg=_BG)

        # -- Font (pick first available monospace) --
        for fam in ("Menlo", "Consolas", "DejaVu Sans Mono", "Courier"):
            self.font = tkfont.Font(family=fam, size=11)
            if self.font.metrics("fixed"):
                break
        self.font_bold = tkfont.Font(
            family=self.font.actual("family"), size=11, weight="bold",
        )

        # -- Text widget --
        self.text = tk.Text(
            self.root, wrap=tk.NONE, font=self.font,
            bg=_BG, fg=_FG, insertbackground=_FG,
            padx=6, pady=6, width=self.COLS, height=self.ROWS,
            state=tk.DISABLED, cursor="xterm",
        )
        self.text.pack(fill=tk.BOTH, expand=True)

        # -- pyte VT100 screen --
        self.screen = pyte.Screen(self.COLS, self.ROWS)
        self.stream = pyte.Stream(self.screen)

        # -- Bindings --
        self.text.bind("<Key>", self._on_key)
        self.text.bind("<Button-1>", self._on_click)
        self.text.bind("<Button-4>", lambda _: self._on_scroll(-1))
        self.text.bind("<Button-5>", lambda _: self._on_scroll(1))
        self.text.bind("<MouseWheel>",
                       lambda e: self._on_scroll(-1 if e.delta > 0 else 1))
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        self.text.focus_set()

        # -- Fork child in a pty --
        pid, fd = pty.fork()
        if pid == 0:
            os.environ["TERM"] = "xterm-256color"
            os.environ["COLUMNS"] = str(self.COLS)
            os.environ["LINES"] = str(self.ROWS)
            os.execvp(self.command[0], self.command)
        self.child_pid, self.master_fd = pid, fd
        fcntl.ioctl(fd, termios.TIOCSWINSZ,
                     struct.pack("HHHH", self.ROWS, self.COLS, 0, 0))
        self._poll()

    # -- I/O loop --

    def _poll(self):
        if self.master_fd is None:
            return
        try:
            if select.select([self.master_fd], [], [], 0)[0]:
                data = os.read(self.master_fd, 65536)
                if not data:
                    raise OSError
                text = data.decode("utf-8", errors="replace")
                # Respond to cursor-position queries (DSR)
                if "\033[6n" in text:
                    r = self.screen.cursor.y + 1
                    c = self.screen.cursor.x + 1
                    os.write(self.master_fd, f"\033[{r};{c}R".encode())
                    text = text.replace("\033[6n", "")
                # Track mouse-mode toggles
                if "\033[?1000h" in text:
                    self.mouse_tracking = True
                if "\033[?1000l" in text:
                    self.mouse_tracking = False
                self.stream.feed(text)
                self._render()
        except OSError:
            self.master_fd = None
            self.root.after(1500, self.root.quit)
            return
        self.root.after(16, self._poll)

    def _write(self, data: bytes):
        if self.master_fd:
            try:
                os.write(self.master_fd, data)
            except OSError:
                pass

    # -- Rendering --

    def _tag_for(self, char):
        fg, bg = char.fg, char.bg
        bold, rev = char.bold, char.reverse
        if rev:
            fg, bg = bg, fg
        key = (fg, bg, bold)
        if key not in self._tags:
            name = f"t{len(self._tags)}"
            kw = {}
            fc = _color_hex(fg, bright=bold and bg in ("default", None))
            if fc:
                kw["foreground"] = fc
            elif bold and fg in ("default", None):
                kw["foreground"] = "#ffffff"
            bc = _color_hex(bg)
            if bc:
                kw["background"] = bc
            if bold:
                kw["font"] = self.font_bold
            self.text.tag_configure(name, **kw)
            self._tags[key] = name
        return self._tags[key]

    def _render(self):
        self.text.configure(state=tk.NORMAL)
        self.text.delete("1.0", tk.END)
        buf = self.screen.buffer
        for y in range(self.ROWS):
            line = buf[y]
            for x in range(self.COLS):
                ch = line[x]
                self.text.insert(tk.END, ch.data, self._tag_for(ch))
            if y < self.ROWS - 1:
                self.text.insert(tk.END, "\n")
        self.text.configure(state=tk.DISABLED)

    # -- Keyboard --

    def _on_key(self, ev):
        if ev.keysym == "Return":
            self._write(b"\r")
        elif ev.keysym in self._KEYMAP:
            self._write(self._KEYMAP[ev.keysym].encode())
        elif ev.char and ord(ev.char[0]) > 0:
            self._write(ev.char.encode("utf-8"))
        return "break"

    # -- Mouse --

    def _on_click(self, ev):
        self.text.focus_set()
        if self.mouse_tracking:
            idx = self.text.index(f"@{ev.x},{ev.y}")
            row, col = (int(x) for x in idx.split("."))
            self._write(f"\033[<0;{col + 1};{row}M".encode())
            self._write(f"\033[<0;{col + 1};{row}m".encode())
        return "break"

    def _on_scroll(self, direction):
        if self.mouse_tracking:
            btn = 64 if direction < 0 else 65
            self._write(f"\033[<{btn};1;1M".encode())

    # -- Lifecycle --

    def _close(self):
        if self.child_pid:
            try:
                os.kill(self.child_pid, signal.SIGTERM)
            except OSError:
                pass
        self.root.quit()

    def run(self):
        self.root.mainloop()


# -- Locate companion binary ----------------------------------------------

def _find_tool() -> str:
    """Locate antithese_interactive binary (or .py in dev)."""
    exe_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
    for candidate in ("antithese_interactive",
                      "antithese_interactive.py"):
        p = os.path.join(exe_dir, candidate)
        if os.path.isfile(p):
            return p
    return "antithese_interactive"  # fallback: hope it's on PATH


def main():
    cmd = [_find_tool()] + sys.argv[1:]
    TerminalApp(cmd).run()


if __name__ == "__main__":
    main()
