"""Compatibility launcher. Prefer the installed ``fieldnote`` command."""

import sys

from fieldnote.cli import main

if __name__ == "__main__":
    raise SystemExit(main(["analyze", *sys.argv[1:]]))
