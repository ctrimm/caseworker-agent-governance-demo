"""Append-only audit trail. Logs the why (the agent's stated rationale), not just the what."""
from __future__ import annotations

import json
import time
from pathlib import Path


class Audit:
    def __init__(self, path=None, redact=lambda s: s):
        self.events: list[dict] = []
        self.path = Path(path) if path else None
        self.redact = redact
        if self.path:
            self.path.write_text("")

    def log(self, **fields):
        event = {"seq": len(self.events) + 1, "ts": round(time.time(), 3), **fields}
        if "args" in fields:
            event["args"] = json.loads(self.redact(json.dumps(fields["args"])))
        for key in ("why", "reason"):  # the agent's rationale can quote the case file too
            if isinstance(fields.get(key), str):
                event[key] = self.redact(fields[key])
        self.events.append(event)
        if self.path:
            with self.path.open("a") as f:
                f.write(json.dumps(event) + "\n")
        return event
