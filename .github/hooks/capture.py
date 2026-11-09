"""Append a privacy-conscious agent progress timeline to a local JSONL log."""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


LOG_FILE = Path(".github/hooks/session-events.jsonl")
EVENT_LABELS = {
    "SessionStart": "Session started",
    "UserPromptSubmit": "Prompt submitted",
    "PreToolUse": "Tool started",
    "PostToolUse": "Tool completed",
    "PostToolUseFailure": "Tool failed",
    "Stop": "Assistant turn finished",
    "SessionEnd": "Session ended",
    "PreCompact": "Context compaction started",
    "SubagentStart": "Subagent started",
    "SubagentStop": "Subagent completed",
}
SAFE_FIELDS = (
    "session_id",
    "tool_name",
    "tool_use_id",
    "source",
    "stop_reason",
    "reason",
    "trigger",
    "agent_id",
    "agent_name",
    "result_type",
)
MAX_EVENT_BYTES = 10_000_000


def main() -> None:
    raw = sys.stdin.read()
    if not raw.strip():
        return

    try:
        event: Any = json.loads(raw)
    except json.JSONDecodeError:
        return

    if not isinstance(event, dict):
        return

    if len(raw.encode("utf-8")) > MAX_EVENT_BYTES:
        return

    raw_event_name = event.get("hook_event_name", "Unknown")
    event_name = raw_event_name if isinstance(raw_event_name, str) else "Unknown"
    record = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "event": event_name,
        "progress": EVENT_LABELS.get(event_name, "Agent activity"),
    }
    for key in SAFE_FIELDS:
        value = event.get(key)
        if isinstance(value, (str, int, float, bool)):
            record[key] = value

    tool_name = event.get("tool_name")
    agent_name = event.get("agent_name")
    if isinstance(tool_name, str) and tool_name:
        record["progress"] = f"{record['progress']}: {tool_name[:120]}"
    elif isinstance(agent_name, str) and agent_name:
        record["progress"] = f"{record['progress']}: {agent_name[:120]}"

    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as file:
        file.write(json.dumps(record, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()