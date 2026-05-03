"""Top-level entry point for the bundled executable.

PyInstaller treats this file as the entry script, so it cannot use relative
imports. It just delegates to scheduler.__main__'s logic.
"""
import atexit
import sys

from scheduler.main import main


def _wait_on_exit() -> None:
    if getattr(sys, "frozen", False):
        try:
            input("\nPress Enter to close…")
        except (EOFError, KeyboardInterrupt):
            pass


if __name__ == "__main__":
    atexit.register(_wait_on_exit)
    try:
        main()
    except KeyboardInterrupt:
        print("\nCancelled.")
        sys.exit(130)
    except Exception as e:
        import traceback
        print()
        print("ERROR:", e)
        traceback.print_exc()
        sys.exit(1)
