"""Moved to ``tools/stubs/router.py``; this entry point is kept so existing commands keep working.

Prefer: ``python -m tools.stubs router ...``
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.stubs.router import StubRouter, main  # noqa: E402

__all__ = ["StubRouter", "main"]

if __name__ == "__main__":
    main()
