"""
utils.py
Shared utility helpers.
"""

import logging
import os
import sys


def configure_logging(level: int = logging.INFO) -> None:
    """
    Set up a clean console logger for the whole application.
    Call once at program start from main.py.
    """
    fmt = "%(asctime)s [%(levelname)-8s] %(name)s — %(message)s"
    date_fmt = "%H:%M:%S"
    logging.basicConfig(stream=sys.stdout, level=level, format=fmt, datefmt=date_fmt)


def wait_for_space() -> None:
    """
    Block until the user presses SPACE (then Enter on non-Unix systems).

    On POSIX systems we use termios for raw, single-keypress detection.
    On Windows we fall back to a simple input() prompt so the code stays
    portable without requiring extra dependencies.
    """
    print("\n" + "=" * 60)
    print("  Scanning complete.  Press [SPACE] to finalize the pallet.")
    print("=" * 60)

    if os.name == "posix":
        _wait_posix()
    else:
        _wait_fallback()


def _wait_posix() -> None:
    import termios
    import tty

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        while True:
            ch = sys.stdin.read(1)
            if ch == " ":
                break
            if ch in ("\x03", "\x04"):      # Ctrl-C / Ctrl-D → also exit cleanly
                print("\nAborted.")
                sys.exit(0)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def _wait_fallback() -> None:
    while True:
        val = input("Type SPACE and press Enter to finalize: ")
        if val == " " or val.strip() == "":
            break


def print_banner(title: str) -> None:
    width = 60
    print("\n" + "=" * width)
    print(f"  {title}")
    print("=" * width)


def print_section(label: str) -> None:
    print(f"\n  ── {label}")
