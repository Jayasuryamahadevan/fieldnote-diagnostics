"""Compatibility launcher. Prefer the installed ``fieldnote`` command."""

import sys

from fieldnote.cli import main


def _run() -> int:
    argv = sys.argv[1:]
    if "--inspect" in argv:
        argv = ["inspect"]
    elif not argv or argv[0] in ("-h", "--help", "--version"):
        return main(argv)
    else:
        argv = ["analyze", *argv]
    return main(argv)


if __name__ == "__main__":
    raise SystemExit(_run())
