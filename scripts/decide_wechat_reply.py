#!/usr/bin/env python3
"""Read WeChat JSON snapshots and produce guarded reply decisions.

Default behavior is dry-run style decision only. It will only call turix when
--execute-turix is explicitly enabled.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

PLACEHOLDER_PREFIX = "[stacked/hidden"


def now_ts() -> float:
    return time.time()


def now_text() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())


def build_turix_task_name(sender: str) -> str:
    sender_clean = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "", sender or "").strip()
    if not sender_clean:
        sender_clean = "unknown"
    sender_clean = sender_clean[:16]
    suffix = time.strftime("%m%d-%H%M%S", time.localtime())
    return f"WeChatReply-{sender_clean}-{suffix}"


def resolve_input_path(path: Path) -> Path:
    if path.suffix.lower() == ".json":
        candidates = sorted(path.parent.glob(f"{path.stem}_*.json"))
        if candidates:
            return candidates[-1].resolve()
    return path.resolve()


def read_json(path: Path) -> Any:
    if not path.exists():
        raise FileNotFoundError(f"input file not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def extract_items(payload: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if isinstance(payload, dict):
        entries = payload.get("entries")
        if isinstance(entries, list):
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                items = entry.get("new_unread_items")
                if isinstance(items, list):
                    out.extend([x for x in items if isinstance(x, dict)])
            return out

        items = payload.get("items")
        if isinstance(items, list):
            out.extend([x for x in items if isinstance(x, dict)])
            return out

        unread = payload.get("unread")
        if isinstance(unread, list):
            out.extend([x for x in unread if isinstance(x, dict)])
            return out
        if isinstance(unread, dict):
            nested = unread.get("items")
            if isinstance(nested, list):
                out.extend([x for x in nested if isinstance(x, dict)])
                return out

    if isinstance(payload, list):
        out.extend([x for x in payload if isinstance(x, dict)])
    return out


def item_event_id(item: dict[str, Any]) -> str:
    direct = str(item.get("notification_id", "")).strip() or str(item.get("id", "")).strip()
    if direct:
        return direct

    sender = str(item.get("sender", "")).strip()
    body = str(item.get("body", "")).strip()
    captured = str(item.get("captured_at", "")).strip()
    digest = hashlib.sha1(f"{sender}|{body}|{captured}".encode("utf-8", errors="ignore")).hexdigest()
    return f"hash_{digest[:20]}"


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"seen_ids": [], "last_reply_by_sender": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"seen_ids": [], "last_reply_by_sender": {}}

    seen_ids = data.get("seen_ids") if isinstance(data, dict) else None
    last_reply = data.get("last_reply_by_sender") if isinstance(data, dict) else None
    if not isinstance(seen_ids, list):
        seen_ids = []
    if not isinstance(last_reply, dict):
        last_reply = {}
    return {"seen_ids": [str(x) for x in seen_ids], "last_reply_by_sender": last_reply}


def save_state(path: Path, seen_ids: list[str], last_reply_by_sender: dict[str, float]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": now_text(),
        "seen_ids": seen_ids[-50000:],
        "last_reply_by_sender": last_reply_by_sender,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_policy(path: Path | None) -> dict[str, Any]:
    if not path:
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def normalize_set(values: list[str]) -> set[str]:
    return {v.strip() for v in values if v and v.strip()}


def is_hidden_placeholder(item: dict[str, Any]) -> bool:
    quality = str(item.get("message_quality", "")).strip()
    body = str(item.get("body", "")).strip().lower()
    return quality == "system_event_placeholder" and body.startswith(PLACEHOLDER_PREFIX)


def should_reply(
    item: dict[str, Any],
    reply_mode: str,
    allow_senders: set[str],
    deny_senders: set[str],
    trigger_keywords: list[str],
    cooldown_sec: float,
    last_reply_by_sender: dict[str, float],
) -> tuple[bool, str]:
    sender = str(item.get("sender", "")).strip()
    body = str(item.get("body", "")).strip()

    if is_hidden_placeholder(item):
        return False, "hidden_placeholder"
    if not sender:
        return False, "missing_sender"
    if not body:
        return False, "missing_body"
    if reply_mode == "whitelist":
        if sender not in allow_senders:
            return False, "sender_not_in_whitelist"
    elif reply_mode == "blacklist":
        if sender in deny_senders:
            return False, "sender_in_blacklist"
    elif reply_mode != "all":
        return False, "invalid_reply_mode"

    sender_last_reply = float(last_reply_by_sender.get(sender, 0.0) or 0.0)
    if sender_last_reply and now_ts() - sender_last_reply < cooldown_sec:
        return False, "sender_cooldown_active"

    body_lower = body.lower()
    if trigger_keywords:
        matched = any(keyword.lower() in body_lower for keyword in trigger_keywords)
        if not matched:
            return False, "keyword_not_matched"

    return True, "reply_candidate"


def build_turix_task(sender: str, body: str, max_body_chars: int) -> str:
    trimmed = body[:max_body_chars]
    task_name = build_turix_task_name(sender)
    return (
        "请执行微信回复任务，并按以下步骤输出与执行：\n"
        f"1) 先把turix当前任务名改为：{task_name}\n"
        f"2) 打开微信，定位到联系人/群聊：{sender}\n"
        f"3) 对方最新消息：{trimmed}\n"
        "4) 先写出拟回复内容草稿（不超过60字，中文、自然、礼貌）\n"
        "5) 判断是否需要基于前后文微调草稿，并明确输出：需要/不需要 + 理由\n"
        "6) 若需要则微调后发送；若不需要则直接发送草稿\n"
        "7) 执行期间持续输出关键日志（任务名已更新、已定位联系人、已输入内容、已点击发送/失败原因）\n"
        "8) 最终输出：任务名、已回复对象、最终发送文本、是否发生微调及原因"
    )


def run_turix(turix_script: Path, task: str, timeout_sec: int) -> tuple[bool, str]:
    if not turix_script.exists():
        return False, f"turix script not found: {turix_script}"

    try:
        proc = subprocess.run(
            [str(turix_script), task],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
    except subprocess.TimeoutExpired:
        return False, "turix timeout"
    except Exception as exc:
        return False, f"turix failed: {exc}"

    if proc.returncode == 0:
        return True, proc.stdout.strip()
    return False, (proc.stderr or proc.stdout or "turix non-zero exit").strip()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Decide whether WeChat messages should trigger auto reply")
    parser.add_argument("--input", default="~/.openclaw/state/wechat_messages.json")
    parser.add_argument("--state", default="~/.openclaw/state/wechat-autopilot-state.json")
    parser.add_argument("--mode", choices=["new", "all"], default="new")
    parser.add_argument("--policy", default="")

    parser.add_argument("--allow-sender", action="append", default=[])
    parser.add_argument("--deny-sender", action="append", default=[])
    parser.add_argument("--reply-mode", choices=["whitelist", "blacklist", "all"], default="whitelist")
    parser.add_argument("--trigger-keyword", action="append", default=[])
    parser.add_argument("--cooldown-sec", type=float, default=90.0)

    parser.add_argument("--execute-turix", action="store_true", default=False)
    parser.add_argument("--turix-script", default="~/.openclaw/skills/turix-mac/scripts/run_turix.sh")
    parser.add_argument("--turix-timeout-sec", type=int, default=900)
    parser.add_argument("--max-actions", type=int, default=1)
    parser.add_argument("--max-body-chars", type=int, default=160)

    parser.add_argument("--mark-seen", dest="mark_seen", action="store_true")
    parser.add_argument("--no-mark-seen", dest="mark_seen", action="store_false")
    parser.set_defaults(mark_seen=None)

    parser.add_argument("--format", choices=["json", "text"], default="json")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    input_path = resolve_input_path(Path(os.path.expanduser(args.input)))
    state_path = Path(os.path.expanduser(args.state)).resolve()
    policy_path = Path(os.path.expanduser(args.policy)).resolve() if args.policy else None
    turix_script = Path(os.path.expanduser(args.turix_script)).resolve()

    payload = read_json(input_path)
    items = extract_items(payload)

    state = load_state(state_path)
    seen_ids = list(state.get("seen_ids", []))
    seen_set = set(seen_ids)
    last_reply_by_sender = dict(state.get("last_reply_by_sender", {}))

    policy = load_policy(policy_path)
    allow_senders = normalize_set(args.allow_sender + list(policy.get("allow_senders", [])))
    deny_senders = normalize_set(args.deny_sender + list(policy.get("deny_senders", [])))
    reply_mode = str(policy.get("reply_mode", args.reply_mode)).strip().lower()
    if reply_mode not in {"whitelist", "blacklist", "all"}:
        raise ValueError(f"invalid reply_mode: {reply_mode}")
    trigger_keywords = [
        str(k).strip() for k in (args.trigger_keyword + list(policy.get("trigger_keywords", []))) if str(k).strip()
    ]
    cooldown_sec = float(policy.get("cooldown_sec", args.cooldown_sec))
    max_actions = int(policy.get("max_actions", args.max_actions))

    normalized_items: list[dict[str, Any]] = []
    for raw in items:
        event_id = item_event_id(raw)
        normalized_items.append(
            {
                "event_id": event_id,
                "sender": str(raw.get("sender", "")).strip(),
                "body": str(raw.get("body", "")).strip(),
                "captured_at": str(raw.get("captured_at", "")).strip(),
                "message_quality": str(raw.get("message_quality", "")).strip(),
                "raw": raw,
            }
        )

    if args.mode == "new":
        selected = [item for item in normalized_items if item["event_id"] not in seen_set]
    else:
        selected = normalized_items

    decisions: list[dict[str, Any]] = []
    actions_taken = 0

    for item in selected:
        should, reason = should_reply(
            item["raw"],
            reply_mode=reply_mode,
            allow_senders=allow_senders,
            deny_senders=deny_senders,
            trigger_keywords=trigger_keywords,
            cooldown_sec=cooldown_sec,
            last_reply_by_sender=last_reply_by_sender,
        )

        decision: dict[str, Any] = {
            "event_id": item["event_id"],
            "sender": item["sender"],
            "body": item["body"],
            "captured_at": item["captured_at"],
            "should_reply": should,
            "reason": reason,
            "executed": False,
        }

        if should and args.execute_turix and actions_taken < max_actions:
            task = build_turix_task(item["sender"], item["body"], max_body_chars=max(40, args.max_body_chars))
            ok, detail = run_turix(turix_script, task=task, timeout_sec=max(120, args.turix_timeout_sec))
            decision["executed"] = True
            decision["execute_ok"] = ok
            decision["execute_detail"] = detail
            decision["turix_task"] = task
            if ok:
                last_reply_by_sender[item["sender"]] = now_ts()
            actions_taken += 1

        decisions.append(decision)

    mark_seen = args.mark_seen
    if mark_seen is None:
        mark_seen = args.mode == "new"

    if mark_seen:
        for item in selected:
            eid = item["event_id"]
            if eid not in seen_set:
                seen_set.add(eid)
                seen_ids.append(eid)

    save_state(state_path, seen_ids=seen_ids, last_reply_by_sender=last_reply_by_sender)

    summary = {
        "source": str(input_path),
        "state": str(state_path),
        "updated_at": now_text(),
        "mode": args.mode,
        "reply_mode": reply_mode,
        "allow_senders": sorted(allow_senders),
        "deny_senders": sorted(deny_senders),
        "selected_count": len(selected),
        "decision_count": len(decisions),
        "reply_candidates": sum(1 for d in decisions if d.get("should_reply")),
        "executed_count": sum(1 for d in decisions if d.get("executed")),
        "decisions": decisions,
    }

    if args.format == "json":
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        if not decisions:
            print("NO_MESSAGES")
            return 0
        for idx, d in enumerate(decisions, start=1):
            print(
                f"#{idx} sender={d['sender']} should_reply={d['should_reply']} "
                f"reason={d['reason']} executed={d['executed']}"
            )
            print(f"body={d['body']}")
            print()

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
