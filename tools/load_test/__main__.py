"""Entry point: ``python -m tools.load_test ...``."""

from __future__ import annotations

import sys

from tools.load_test.runner import main

if __name__ == "__main__":
    sys.exit(main())
