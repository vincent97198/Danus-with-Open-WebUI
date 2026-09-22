"""Role-gated command-line access to the same Danus gateway operations.

This is a fallback for Codex versions that start an MCP server but omit its
tools from the model's callable tool list. It calls the same implementation as
the MCP server, so fact_submit still goes through the verifier gate.
"""

from __future__ import annotations

import json
import os
import sys

from . import server
from .roles import tools_for


def main() -> int:
    if len(sys.argv) not in (2, 3):
        print("Usage: danus-tool TOOL [JSON_OBJECT] (or pipe JSON_OBJECT to stdin)", file=sys.stderr)
        return 2
    name = sys.argv[1]
    role = os.environ.get("DANUS_ROLE", "verifier")
    if name not in tools_for(role):
        print(json.dumps({"error": f"{name} is not available to role {role}"}), file=sys.stderr)
        return 2
    try:
        raw = sys.argv[2] if len(sys.argv) == 3 else sys.stdin.read()
        args = json.loads(raw) if raw.strip() else {}
        if not isinstance(args, dict):
            raise ValueError("arguments must be a JSON object")
        if role == "worker" and args.get("project") is not None:
            raise ValueError("worker calls must use their pinned project")
        result = server._TOOLS[name](**args)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (ValueError, TypeError, OSError, RuntimeError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
