#!/usr/bin/env python3
"""Send a one-shot OpenClaw /hooks/agent trigger for testing."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any


def send_json(url: str, payload: dict[str, Any], token: str, timeout_sec: float) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }
    req = urllib.request.Request(url=url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
        text = resp.read().decode("utf-8", errors="ignore").strip()
        if not text:
            return {}
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"raw": text}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send OpenClaw hook trigger")
    parser.add_argument("--hook-url", default="http://127.0.0.1:18789/hooks/agent")
    parser.add_argument("--token", default="")
    parser.add_argument("--token-env", default="OPENCLAW_HOOKS_TOKEN")
    parser.add_argument("--message", required=True)
    parser.add_argument("--name", default="WeChat")
    parser.add_argument("--agent-id", default="")
    parser.add_argument("--session-key", default="hook:wechat-inbox")
    parser.add_argument("--wake-mode", choices=["now", "next-heartbeat"], default="now")
    parser.add_argument("--thinking", default="low")
    parser.add_argument("--model", default="")
    parser.add_argument("--timeout-sec", type=int, default=120)
    parser.add_argument("--deliver", action="store_true", default=False)
    parser.add_argument("--dry-run", action="store_true", default=False)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload: dict[str, Any] = {
        "message": args.message,
        "name": args.name,
        "sessionKey": args.session_key,
        "wakeMode": args.wake_mode,
        "thinking": args.thinking,
        "deliver": bool(args.deliver),
        "timeoutSeconds": int(args.timeout_sec),
    }
    if args.agent_id:
        payload["agentId"] = args.agent_id
    if args.model:
        payload["model"] = args.model

    if args.dry_run:
        print(json.dumps({"hook_url": args.hook_url, "payload": payload}, ensure_ascii=False, indent=2))
        return 0

    token = args.token.strip() or os.environ.get(args.token_env, "").strip()
    if not token:
        print(
            f"ERROR: missing hook token. Use --token or set env {args.token_env}",
            file=sys.stderr,
        )
        return 2

    try:
        result = send_json(args.hook_url, payload, token=token, timeout_sec=15.0)
    except urllib.error.URLError as exc:
        print(f"ERROR: hook request failed: {exc}", file=sys.stderr)
        return 3

    print(json.dumps({"ok": True, "result": result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
