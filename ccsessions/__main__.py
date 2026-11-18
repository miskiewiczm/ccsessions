from __future__ import annotations

import argparse
import sys

from . import __version__
from .core.resume import ResumeError, ResumeRequest, execute_resume
from .ui.app import CCSessionsApp


def main() -> int:
    parser = argparse.ArgumentParser(prog="ccsessions")
    parser.add_argument("-V", "--version", action="version", version=f"ccsessions {__version__}")
    parser.parse_args()
    app = CCSessionsApp()
    result = app.run()
    if isinstance(result, ResumeRequest):
        try:
            execute_resume(result)  # replaces process; does not return on success
        except ResumeError as e:
            print(f"Resume failed: {e}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
