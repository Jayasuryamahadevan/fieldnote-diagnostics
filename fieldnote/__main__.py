"""Allow ``python -m fieldnote`` to behave like the ``fieldnote`` command."""

import sys

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
