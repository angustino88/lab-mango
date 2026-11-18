"""Moved to ``tools/stubs/agent.py``; this entry point is kept so existing commands keep working.

    python tools/stub_agent.py enroll --base-url http://localhost:8000 --agent-uid <uid> --grant <grant>
    python tools/stub_agent.py heartbeat

Prefer: ``python -m tools.stubs agent ...`` (profiles, booking actions, operator API, provision).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.stubs.agent import StubAgent, main  # noqa: E402

__all__ = ["StubAgent", "main"]

if __name__ == "__main__":
    sys.exit(main())
