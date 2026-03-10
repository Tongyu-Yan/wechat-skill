#!/usr/bin/env python3
"""Event-triggered bridge: macOS WeChat notification events -> AX scan -> JSON snapshot.

This script avoids continuous AX polling:
1) Listen to system event stream (usernoted / WeChat)
2) On new-message event, debounce + cooldown
3) Call monitor API /scan_once once
4) Persist /unread snapshot to JSON
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import re
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

PREDICATE = (
    '(process == "usernoted" OR process == "WeChat") '
    'AND (eventMessage CONTAINS[c] "com.tencent.xinWeChat" '
    'OR eventMessage CONTAINS[c] "wxid_")'
)

TRIGGER_HINTS = (
    "Adding new request",
    "Adding notification request",
)
BANNER_HINTS = (
    "Presenting <NotificationRecord",
    "Delivering <NotificationRecord",
)

USERNOTED_REQ_RE = re.compile(
    r'<NotificationRecord app:"com\.tencent\.xinWeChat" '
    r'ident:"(?P<ident>[^"]+)" req:"(?P<req>[^"]+)" uuid:"(?P<uuid>[^"]+)"'
)
BANNER_DUMP_DESC_RE = re.compile(
    r"AXGroup subrole='AXNotificationCenterBanner(?:Stack)?'.*?desc='([^']+)'"
)


def now_text() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())


def parse_sender_list(raw: str) -> set[str]:
    values = re.split(r"[,;\n]", str(raw or ""))
    return {v.strip() for v in values if v.strip()}


def http_json(
    method: str,
    url: str,
    payload: dict[str, Any] | None = None,
    extra_headers: dict[str, str] | None = None,
    timeout_sec: float = 15.0,
) -> dict[str, Any]:
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if extra_headers:
        headers.update(extra_headers)

    req = urllib.request.Request(url=url, method=method.upper(), data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
        body = resp.read().decode("utf-8", errors="ignore")
        if not body:
            return {}
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return {"raw": body}


def write_snapshot(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


class Bridge:
    def __init__(
        self,
        api_base: str,
        output_json: Path,
        debounce_sec: float,
        cooldown_sec: float,
        open_panel: bool,
        retry_count: int,
        retry_interval_sec: float,
        open_panel_fallback_cooldown_sec: float,
        enable_open_panel_fallback: bool,
        trigger_min_interval_sec: float,
        max_hourly_files: int,
        notify_hook_url: str,
        notify_hook_token: str,
        notify_hook_token_env: str,
        notify_hook_name: str,
        notify_hook_agent_id: str,
        notify_hook_session_key: str,
        notify_hook_wake_mode: str,
        notify_hook_thinking: str,
        notify_hook_model: str,
        notify_hook_timeout_sec: int,
        notify_hook_deliver: bool,
        notify_hook_cooldown_sec: float,
        notify_hook_max_items: int,
        notify_hook_reply_mode: str,
        notify_hook_allow_senders: str,
        notify_hook_deny_senders: str,
    ) -> None:
        self.api_base = api_base.rstrip("/")
        self.output_json = output_json
        self.debounce_sec = max(0.1, debounce_sec)
        self.cooldown_sec = max(0.1, cooldown_sec)
        self.open_panel = open_panel
        self.retry_count = max(1, int(retry_count))
        self.retry_interval_sec = max(0.05, float(retry_interval_sec))
        self.open_panel_fallback_cooldown_sec = max(10.0, float(open_panel_fallback_cooldown_sec))
        self.enable_open_panel_fallback = bool(enable_open_panel_fallback)
        self.trigger_min_interval_sec = max(0.05, float(trigger_min_interval_sec))
        self.banner_trigger_min_interval_sec = min(0.2, self.trigger_min_interval_sec)
        self.max_hourly_files = max(1, int(max_hourly_files))
        self.notify_hook_url = str(notify_hook_url or "").strip()
        self.notify_hook_token = str(notify_hook_token or "").strip()
        self.notify_hook_token_env = str(notify_hook_token_env or "").strip()
        self.notify_hook_name = str(notify_hook_name or "WeChat").strip() or "WeChat"
        self.notify_hook_agent_id = str(notify_hook_agent_id or "").strip()
        self.notify_hook_session_key = str(notify_hook_session_key or "").strip()
        self.notify_hook_wake_mode = (
            "next-heartbeat" if str(notify_hook_wake_mode).strip() == "next-heartbeat" else "now"
        )
        self.notify_hook_thinking = str(notify_hook_thinking or "").strip()
        self.notify_hook_model = str(notify_hook_model or "").strip()
        self.notify_hook_timeout_sec = max(30, int(notify_hook_timeout_sec))
        self.notify_hook_deliver = bool(notify_hook_deliver)
        self.notify_hook_cooldown_sec = max(0.2, float(notify_hook_cooldown_sec))
        self.notify_hook_max_items = max(1, int(notify_hook_max_items))
        mode = str(notify_hook_reply_mode or "whitelist").strip().lower()
        if mode not in {"whitelist", "blacklist", "all"}:
            mode = "whitelist"
        self.notify_hook_reply_mode = mode
        self.notify_hook_allow_senders = parse_sender_list(notify_hook_allow_senders)
        self.notify_hook_deny_senders = parse_sender_list(notify_hook_deny_senders)

        self.stop_event = threading.Event()
        self.trigger_queue: queue.Queue[float] = queue.Queue()

        self.last_trigger_at = 0.0
        self.last_scan_at = 0.0
        self.last_open_panel_fallback_at = 0.0
        self.last_trigger_enqueued_at = 0.0
        self.last_hook_notify_at = 0.0
        self.pending = False
        self.pending_since = 0.0
        self.pending_request_records: list[dict[str, Any]] = []
        self.batch_request_records: list[dict[str, Any]] = []
        self.recent_request_seen_at: dict[str, float] = {}
        self.consumed_request_seen_at: dict[str, float] = {}
        self.sender_alias_by_req_prefix: dict[str, str] = {}
        self.request_seen_ttl_sec = 3600.0
        self.request_lock = threading.Lock()

        self.log_proc: subprocess.Popen[str] | None = None
        self.reader_thread: threading.Thread | None = None

    def _hour_bucket(self, ts: float | None = None) -> str:
        t = time.localtime(time.time() if ts is None else ts)
        return time.strftime("%Y%m%d_%H", t)

    def _hourly_output_file(self, ts: float | None = None) -> Path:
        bucket = self._hour_bucket(ts)
        base = self.output_json
        if base.suffix.lower() == ".json":
            directory = base.parent
            stem = base.stem
        else:
            directory = base
            stem = "wechat_messages"
        return (directory / f"{stem}_{bucket}.json").resolve()

    def _hourly_glob(self) -> tuple[Path, str]:
        base = self.output_json
        if base.suffix.lower() == ".json":
            return base.parent, f"{base.stem}_*.json"
        return base, "wechat_messages_*.json"

    def _prune_hourly_files(self) -> int:
        directory, pattern = self._hourly_glob()
        files = sorted([p for p in directory.glob(pattern) if p.is_file()])
        if len(files) <= self.max_hourly_files:
            return 0

        remove_count = len(files) - self.max_hourly_files
        removed = 0
        for old in files[:remove_count]:
            try:
                old.unlink(missing_ok=True)
                removed += 1
            except Exception:
                continue
        return removed

    def _storage_item_key(self, item: dict[str, Any]) -> str:
        quality = str(item.get("message_quality", "")).strip()
        if quality == "system_event_placeholder":
            return f"placeholder:{item.get('request_key', '')}"
        notif = str(item.get("notification_id", "")).strip()
        if notif:
            return f"notif:{notif}"
        source = str(item.get("source_notification_id", "")).strip()
        sender = str(item.get("sender", "")).strip()
        body = str(item.get("body", "")).strip()
        return f"fallback:{source}|{sender}|{body}"

    def _compact_item(self, item: dict[str, Any]) -> dict[str, Any]:
        keep = {
            "notification_id": item.get("notification_id", ""),
            "source_notification_id": item.get("source_notification_id", ""),
            "app": item.get("app", ""),
            "sender": item.get("sender", ""),
            "body": item.get("body", ""),
            "captured_at": item.get("captured_at", ""),
            "message_quality": item.get("message_quality", ""),
            "request_key": item.get("request_key", ""),
            "request_id": item.get("request_id", ""),
            "request_uuid": item.get("request_uuid", ""),
            "request_ident": item.get("request_ident", ""),
            "duplicate_count": item.get("duplicate_count", 1),
        }
        return {k: v for k, v in keep.items() if v not in ("", None, [], {})}

    def _is_hidden_placeholder(self, item: dict[str, Any]) -> bool:
        quality = str(item.get("message_quality", "")).strip()
        if quality != "system_event_placeholder":
            return False
        body = str(item.get("body", "")).strip().lower()
        return body.startswith("[stacked/hidden")

    def _seen_keys_in_doc(self, doc: dict[str, Any]) -> set[str]:
        seen: set[str] = set()
        entries = doc.get("entries")
        if not isinstance(entries, list):
            return seen
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            items = entry.get("new_unread_items")
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                key = self._storage_item_key(item)
                if key:
                    seen.add(key)
        return seen

    def _seen_hints_in_doc(self, doc: dict[str, Any]) -> tuple[set[str], set[str]]:
        seen_source_prefix: set[str] = set()
        seen_sender_body: set[str] = set()

        entries = doc.get("entries")
        if not isinstance(entries, list):
            return seen_source_prefix, seen_sender_body

        for entry in entries:
            if not isinstance(entry, dict):
                continue
            items = entry.get("new_unread_items")
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                sid = str(item.get("source_notification_id", "")).strip().upper()
                if sid:
                    seen_source_prefix.add(sid.split("-", 1)[0])
                sender = str(item.get("sender", "")).strip()
                body = str(item.get("body", "")).strip()
                if sender and body:
                    seen_sender_body.add(f"{sender}|{body}")

        return seen_source_prefix, seen_sender_body

    def _append_hourly_snapshot(self, payload: dict[str, Any]) -> tuple[Path, int, int, int]:
        target = self._hourly_output_file()
        bucket = self._hour_bucket()
        target.parent.mkdir(parents=True, exist_ok=True)

        doc: dict[str, Any]
        if target.exists():
            try:
                doc = json.loads(target.read_text(encoding="utf-8"))
                if not isinstance(doc, dict):
                    doc = {}
            except Exception:
                doc = {}
        else:
            doc = {}

        entries = doc.get("entries")
        if not isinstance(entries, list):
            entries = []

        seen_keys = self._seen_keys_in_doc(doc)
        seen_source_prefix, seen_sender_body = self._seen_hints_in_doc(doc)
        raw_new_items = payload.get("new_unread_items")
        if not isinstance(raw_new_items, list):
            raw_new_items = []

        compact_new_items: list[dict[str, Any]] = []
        local_seen: set[str] = set()
        local_source_prefix: set[str] = set()
        local_sender_body: set[str] = set()
        hidden_placeholder_count = 0
        for item in raw_new_items:
            if not isinstance(item, dict):
                continue
            key = self._storage_item_key(item)
            if key and (key in seen_keys or key in local_seen):
                continue

            quality = str(item.get("message_quality", "")).strip()
            sid = str(item.get("source_notification_id", "")).strip().upper()
            sid_prefix = sid.split("-", 1)[0] if sid else ""
            sender = str(item.get("sender", "")).strip()
            body = str(item.get("body", "")).strip()
            sender_body_key = f"{sender}|{body}" if sender and body else ""

            # If we already stored a real message, skip later placeholder duplicates.
            if quality in {"system_event_placeholder", "dump_tree_inferred"}:
                if sid_prefix and (sid_prefix in seen_source_prefix or sid_prefix in local_source_prefix):
                    continue
                if sender_body_key and (
                    sender_body_key in seen_sender_body or sender_body_key in local_sender_body
                ):
                    continue

            if key:
                local_seen.add(key)
            if self._is_hidden_placeholder(item):
                hidden_placeholder_count += 1
                continue

            compact = self._compact_item(item)
            compact_new_items.append(compact)
            if sid_prefix:
                local_source_prefix.add(sid_prefix)
            if sender_body_key:
                local_sender_body.add(sender_body_key)

        if not compact_new_items and hidden_placeholder_count <= 0:
            return target, 0, 0, 0

        scan = payload.get("scan", {}) if isinstance(payload.get("scan"), dict) else {}
        unread = payload.get("unread", {}) if isinstance(payload.get("unread"), dict) else {}
        entry = {
            "updated_at": payload.get("updated_at", now_text()),
            "trigger_event_at": payload.get("trigger_event_at", ""),
            "new_unread_count": len(compact_new_items),
            "new_unread_items": compact_new_items,
            "hidden_placeholder_count": hidden_placeholder_count,
            "trigger_request_count": int(payload.get("trigger_request_count", 0) or 0),
            "open_panel_fallback": bool(payload.get("open_panel_fallback", False)),
            "open_panel_fallback_enabled": bool(payload.get("open_panel_fallback_enabled", False)),
            "scan_summary": {
                "count": int(scan.get("count", 0) or 0),
                "panel_open": bool(scan.get("panel_open", False)),
                "unread_count": int(scan.get("unread_count", 0) or 0),
            },
            "unread_total": int(unread.get("total", 0) or 0),
        }

        entries.append(entry)
        doc["hour_bucket"] = bucket
        doc["updated_at"] = now_text()
        doc.setdefault("created_at", now_text())
        doc["entry_count"] = len(entries)
        doc["entries"] = entries
        write_snapshot(target, doc)
        self._prune_hourly_files()
        return (
            target,
            len(compact_new_items) + hidden_placeholder_count,
            len(compact_new_items),
            hidden_placeholder_count,
        )

    def start(self) -> None:
        print(f"[{now_text()}] bridge starting")
        self._best_effort_stop_backend_loop()

        self.log_proc = subprocess.Popen(
            [
                "/usr/bin/log",
                "stream",
                "--style",
                "compact",
                "--level",
                "debug",
                "--predicate",
                PREDICATE,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

        self.reader_thread = threading.Thread(target=self._read_stream, daemon=True)
        self.reader_thread.start()

        while not self.stop_event.is_set():
            self._drain_triggers()
            self._maybe_scan()
            time.sleep(0.2)

        self._shutdown_subprocess()
        print(f"[{now_text()}] bridge stopped")

    def _read_stream(self) -> None:
        assert self.log_proc is not None
        assert self.log_proc.stdout is not None

        for line in self.log_proc.stdout:
            if self.stop_event.is_set():
                break
            text = line.strip()
            if not text:
                continue
            lower_text = text.lower()
            if "com.tencent.xinwechat" not in lower_text:
                continue

            is_add_event = any(hint.lower() in lower_text for hint in TRIGGER_HINTS)
            is_banner_event = any(hint.lower() in lower_text for hint in BANNER_HINTS)
            if not (is_add_event or is_banner_event):
                continue

            now_ts = time.time()
            record = self._parse_usernoted_request_record(text, now_ts)
            if record:
                with self.request_lock:
                    key = str(record.get("request_key", "")).strip()
                    last_seen = self.recent_request_seen_at.get(key, 0.0)
                    if not (key and now_ts - last_seen < self.request_seen_ttl_sec):
                        if key:
                            self.recent_request_seen_at[key] = now_ts
                        self.pending_request_records.append(record)
                        self._cleanup_request_maps(now_ts)
                    else:
                        # Same request key can still emit a later "Presenting" line.
                        # Keep trigger behavior, only skip duplicate record append.
                        pass
                    if key and key not in self.recent_request_seen_at:
                        self.recent_request_seen_at[key] = now_ts

            min_interval = (
                self.banner_trigger_min_interval_sec if is_banner_event else self.trigger_min_interval_sec
            )
            if now_ts - self.last_trigger_enqueued_at < min_interval:
                continue
            self.last_trigger_enqueued_at = now_ts
            self.trigger_queue.put(now_ts)

    def _parse_usernoted_request_record(self, line: str, ts: float) -> dict[str, Any]:
        match = USERNOTED_REQ_RE.search(line)
        if not match:
            return {}
        req = str(match.group("req") or "").strip()
        uuid = str(match.group("uuid") or "").strip().upper()
        ident = str(match.group("ident") or "").strip().upper()
        request_key = req or uuid or ident
        return {
            "event_at": ts,
            "event_at_text": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts)),
            "request_key": request_key,
            "req": req,
            "uuid": uuid,
            "ident": ident,
            "line": line,
        }

    def _cleanup_request_maps(self, now_ts: float) -> None:
        expire_before = now_ts - self.request_seen_ttl_sec
        for key, seen_ts in list(self.recent_request_seen_at.items()):
            if seen_ts < expire_before:
                self.recent_request_seen_at.pop(key, None)
        for key, seen_ts in list(self.consumed_request_seen_at.items()):
            if seen_ts < expire_before:
                self.consumed_request_seen_at.pop(key, None)

    def _drain_triggers(self) -> None:
        drained = False
        while True:
            try:
                ts = self.trigger_queue.get_nowait()
            except queue.Empty:
                break
            self.last_trigger_at = ts
            drained = True

        if drained:
            with self.request_lock:
                if self.pending_request_records:
                    self.batch_request_records.extend(self.pending_request_records)
                    self.pending_request_records.clear()
            self.pending = True
            self.pending_since = time.time()
            print(f"[{now_text()}] trigger received; waiting debounce {self.debounce_sec:.1f}s")

    def _maybe_scan(self) -> None:
        if not self.pending:
            return

        now = time.time()
        if now - self.pending_since < self.debounce_sec:
            return

        if now - self.last_scan_at < self.cooldown_sec:
            return

        self.pending = False
        self.last_scan_at = now
        self._scan_and_write()

    def _scan_and_write(self) -> None:
        scan_url = f"{self.api_base}/scan_once"
        unread_url = f"{self.api_base}/unread?limit=5000"
        trigger_records = self._consume_batch_request_records()

        try:
            baseline_unread = http_json("GET", unread_url)
            baseline_items = list(baseline_unread.get("items", []))
            baseline_by_id = {
                str(item.get("notification_id", "")).strip(): item for item in baseline_items
            }
            baseline_ids = {
                str(item.get("notification_id", "")).strip()
                for item in baseline_items
                if str(item.get("notification_id", "")).strip()
            }

            best_scan: dict[str, Any] = {}
            best_unread: dict[str, Any] = {}
            best_new_items: list[dict[str, Any]] = []
            best_score = -1
            used_open_panel_fallback = False

            for i in range(self.retry_count):
                scan = http_json(
                    "POST",
                    scan_url,
                    payload={
                        "open_panel": self.open_panel,
                        "store": True,
                        "allow_generic_banner_fallback": True,
                    },
                )
                unread = http_json("GET", unread_url)
                unread_items = list(unread.get("items", []))
                new_items = [
                    item
                    for item in unread_items
                    if str(item.get("notification_id", "")).strip() not in baseline_ids
                ]
                inferred_duplicate_items = self._build_duplicate_delta_items(
                    baseline_by_id=baseline_by_id,
                    current_items=unread_items,
                )
                combined_new_items = list(new_items) + inferred_duplicate_items

                scan_count = int(scan.get("count", 0))
                new_count = len(combined_new_items)
                score = max(scan_count, new_count)
                if score > best_score:
                    best_score = score
                    best_scan = scan
                    best_unread = unread
                    best_new_items = combined_new_items

                if score > 0:
                    break

                if i < self.retry_count - 1:
                    delay = min(0.7, self.retry_interval_sec * (1.35**i))
                    time.sleep(delay)

            should_try_open_panel_fallback = (
                self.enable_open_panel_fallback
                and
                best_score <= 0
                and not self.open_panel
                and (time.time() - self.last_open_panel_fallback_at)
                >= self.open_panel_fallback_cooldown_sec
            )

            if best_score <= 0:
                # Some banners become AX-readable slightly later than request creation.
                for extra_delay in (0.9, 1.6):
                    time.sleep(extra_delay)
                    scan = http_json(
                        "POST",
                        scan_url,
                        payload={
                            "open_panel": self.open_panel,
                            "store": True,
                            "allow_generic_banner_fallback": True,
                        },
                    )
                    unread = http_json("GET", unread_url)
                    unread_items = list(unread.get("items", []))
                    new_items = [
                        item
                        for item in unread_items
                        if str(item.get("notification_id", "")).strip() not in baseline_ids
                    ]
                    inferred_duplicate_items = self._build_duplicate_delta_items(
                        baseline_by_id=baseline_by_id,
                        current_items=unread_items,
                    )
                    combined_new_items = list(new_items) + inferred_duplicate_items
                    scan_count = int(scan.get("count", 0))
                    new_count = len(combined_new_items)
                    score = max(scan_count, new_count)
                    if score > best_score:
                        best_score = score
                        best_scan = scan
                        best_unread = unread
                        best_new_items = combined_new_items
                    if score > 0:
                        break

            if should_try_open_panel_fallback:
                # Last-chance fallback: open panel once only when needed.
                used_open_panel_fallback = True
                self.last_open_panel_fallback_at = time.time()
                time.sleep(0.2)
                scan = http_json(
                    "POST",
                    scan_url,
                    payload={
                        "open_panel": True,
                        "store": True,
                        "close_panel_after_scan": True,
                        "allow_generic_banner_fallback": True,
                    },
                )
                unread = http_json("GET", unread_url)
                unread_items = list(unread.get("items", []))
                new_items = [
                    item
                    for item in unread_items
                    if str(item.get("notification_id", "")).strip() not in baseline_ids
                ]
                inferred_duplicate_items = self._build_duplicate_delta_items(
                    baseline_by_id=baseline_by_id,
                    current_items=unread_items,
                )
                combined_new_items = list(new_items) + inferred_duplicate_items
                scan_count = int(scan.get("count", 0))
                new_count = len(combined_new_items)
                score = max(scan_count, new_count)
                if score > best_score:
                    best_score = score
                    best_scan = scan
                    best_unread = unread
                    best_new_items = combined_new_items

            self._update_sender_aliases(trigger_records=trigger_records, new_items=best_new_items)
            current_unread_items = list(best_unread.get("items", [])) if isinstance(best_unread, dict) else []
            synthetic_items = self._build_synthetic_items(
                trigger_records,
                best_new_items,
                current_unread_items,
            )
            if synthetic_items:
                unread_items = list(best_unread.get("items", []))
                unread_items.extend(synthetic_items)
                best_unread = dict(best_unread)
                best_unread["items"] = unread_items
                best_unread["count"] = len(unread_items)
                best_unread["total"] = len(unread_items)
                best_new_items = list(best_new_items) + synthetic_items

            best_new_items = self._enrich_placeholders_from_dump_tree(best_new_items)

            payload = {
                "updated_at": now_text(),
                "trigger_event_at": time.strftime(
                    "%Y-%m-%d %H:%M:%S", time.localtime(self.last_trigger_at)
                )
                if self.last_trigger_at
                else "",
                "scan": best_scan,
                "unread": best_unread,
                "new_unread_count": len(best_new_items),
                "new_unread_items": best_new_items,
                "open_panel_fallback": used_open_panel_fallback,
                "open_panel_fallback_enabled": self.enable_open_panel_fallback,
                "trigger_request_count": len(trigger_records),
            }

            if len(best_new_items) == 0:
                print(
                    f"[{now_text()}] no new unread; skip snapshot update "
                    f"(scan_count={best_scan.get('count', 0)} unread_total={best_unread.get('total', 0)})"
                )
                return

            saved_path, stored_count, readable_count, hidden_count = self._append_hourly_snapshot(payload)
            if stored_count <= 0:
                print(
                    f"[{now_text()}] hourly dedupe: no storable new items "
                    f"(new_unread={len(best_new_items)})"
                )
                return

            hook_sent = self._send_openclaw_hook(
                saved_path=saved_path,
                new_items=best_new_items,
                readable_count=readable_count,
                hidden_count=hidden_count,
            )
            print(
                f"[{now_text()}] scan done: count={best_scan.get('count', 0)} "
                f"unread_total={best_unread.get('total', 0)} "
                f"new_unread={len(best_new_items)} stored={stored_count} "
                f"retries={self.retry_count} fallback_open_panel={used_open_panel_fallback} "
                f"hook_sent={hook_sent} "
                f"-> {saved_path}"
            )
        except urllib.error.URLError as exc:
            print(f"[{now_text()}] scan failed (network): {exc}", file=sys.stderr)
        except Exception as exc:
            print(f"[{now_text()}] scan failed: {exc}", file=sys.stderr)

    def _consume_batch_request_records(self) -> list[dict[str, Any]]:
        with self.request_lock:
            if not self.batch_request_records:
                return []
            records = list(self.batch_request_records)
            self.batch_request_records.clear()
            return records

    def _sender_hint_from_req(self, req: str) -> str:
        text = str(req or "").strip()
        if not text:
            return ""
        parts = text.split("_")
        if len(parts) >= 3 and parts[-2].isdigit() and parts[-1].isdigit():
            return "_".join(parts[:-2]) or text
        if len(parts) >= 2 and parts[-1].isdigit():
            return "_".join(parts[:-1]) or text
        return text

    def _request_prefix(self, req: str) -> str:
        text = str(req or "").strip()
        if not text:
            return ""
        parts = text.split("_")
        if len(parts) >= 3 and parts[-2].isdigit() and parts[-1].isdigit():
            return "_".join(parts[:-2]) or text
        if len(parts) >= 2 and parts[-1].isdigit():
            return "_".join(parts[:-1]) or text
        return text

    def _looks_like_wxid(self, sender: str) -> bool:
        s = str(sender or "").strip().lower()
        return s.startswith("wxid_")

    def _to_int(self, value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except Exception:
            return default

    def _build_duplicate_delta_items(
        self,
        baseline_by_id: dict[str, dict[str, Any]],
        current_items: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        inferred: list[dict[str, Any]] = []
        for item in current_items:
            nid = str(item.get("notification_id", "")).strip()
            if not nid or nid not in baseline_by_id:
                continue

            before = self._to_int(baseline_by_id[nid].get("duplicate_count", 1), default=1)
            after = self._to_int(item.get("duplicate_count", 1), default=1)
            if after <= before:
                continue

            for idx in range(before + 1, after + 1):
                clone = dict(item)
                clone["notification_id"] = f"{nid}#dup{idx}"
                clone["message_quality"] = "duplicate_inferred"
                clone["inferred_from_notification_id"] = nid
                clone["inferred_index"] = idx
                inferred.append(clone)

        return inferred

    def _update_sender_aliases(
        self,
        trigger_records: list[dict[str, Any]],
        new_items: list[dict[str, Any]],
    ) -> None:
        if not trigger_records or not new_items:
            return

        uuid_to_prefix: dict[str, str] = {}
        for rec in trigger_records:
            req = str(rec.get("req", "")).strip()
            prefix = self._request_prefix(req)
            if not prefix:
                continue
            rec_uuid = str(rec.get("uuid", "")).strip().upper()
            if rec_uuid:
                uuid_to_prefix[rec_uuid] = prefix
            else:
                # Weak fallback: single batch with one sender.
                uuid_to_prefix[prefix] = prefix

        for item in new_items:
            sender = str(item.get("sender", "")).strip()
            if not sender or self._looks_like_wxid(sender):
                continue

            sid = str(item.get("source_notification_id", "")).strip().upper()
            if not sid:
                continue

            for rec_uuid, prefix in uuid_to_prefix.items():
                if not rec_uuid:
                    continue
                if sid.startswith(rec_uuid):
                    self.sender_alias_by_req_prefix[prefix] = sender
                    break

    def _build_synthetic_items(
        self,
        trigger_records: list[dict[str, Any]],
        real_new_items: list[dict[str, Any]],
        current_unread_items: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not trigger_records:
            return []

        real_source_ids: set[str] = set()
        for item in real_new_items:
            sid = str(item.get("source_notification_id", "")).strip().upper()
            if sid:
                real_source_ids.add(sid)
        for item in current_unread_items:
            sid = str(item.get("source_notification_id", "")).strip().upper()
            if sid:
                real_source_ids.add(sid)

        synthetic: list[dict[str, Any]] = []
        now_ts = time.time()
        with self.request_lock:
            consumed_keys = set(self.consumed_request_seen_at.keys())
        newly_consumed_keys: list[str] = []

        for rec in trigger_records:
            request_key = str(rec.get("request_key", "")).strip()
            if not request_key:
                continue
            if request_key in consumed_keys:
                continue

            rec_uuid = str(rec.get("uuid", "")).strip().upper()
            rec_ident = str(rec.get("ident", "")).strip().upper()
            matched_real = False
            for sid in real_source_ids:
                if rec_uuid and sid.startswith(rec_uuid):
                    matched_real = True
                    break
                if rec_ident and rec_ident in sid:
                    matched_real = True
                    break
            if matched_real:
                consumed_keys.add(request_key)
                newly_consumed_keys.append(request_key)
                continue

            req_text = str(rec.get("req", ""))
            req_prefix = self._request_prefix(req_text)
            sender_hint = self.sender_alias_by_req_prefix.get(req_prefix, "")
            if not sender_hint:
                sender_hint = self._sender_hint_from_req(req_text)
            synthetic_item = {
                "notification_id": f"log_req_{request_key}",
                "source_notification_id": rec_uuid or rec_ident or request_key,
                "app": "WeChat",
                "sender": sender_hint or str(rec.get("req", "")),
                "body": "[stacked/hidden in Notification Center; text not exposed by AX]",
                "date_text": "",
                "captured_at": now_text(),
                "first_seen_at": str(rec.get("event_at_text", "")),
                "last_seen_at": now_text(),
                "visible_now": False,
                "message_quality": "system_event_placeholder",
                "request_key": request_key,
                "request_id": str(rec.get("req", "")),
                "request_uuid": rec_uuid,
                "request_ident": rec_ident,
            }
            synthetic.append(synthetic_item)
            consumed_keys.add(request_key)
            newly_consumed_keys.append(request_key)

        with self.request_lock:
            for key in newly_consumed_keys:
                self.consumed_request_seen_at[key] = now_ts
            self._cleanup_request_maps(now_ts)
        return synthetic

    def _parse_desc_sender_body(self, description: str) -> tuple[str, str]:
        text = str(description or "").strip()
        if not text:
            return "", ""

        parts = [p.strip() for p in text.split(",")]
        if len(parts) < 3:
            return "", ""

        first = parts[0].lower()
        if first in {"wechat", "weixin", "微信"}:
            sender = parts[1].strip()
            body_parts = parts[2:]
        else:
            sender = parts[0].strip()
            body_parts = parts[1:]

        if body_parts and body_parts[-1].lower() in {"stacked", "展开", "已堆叠"}:
            body_parts = body_parts[:-1]
        body = ",".join(body_parts).strip()
        return sender, body

    def _extract_dump_tree_candidates(self) -> list[dict[str, str]]:
        try:
            dump = http_json(
                "POST",
                f"{self.api_base}/dump_tree",
                payload={"max_depth": 12, "max_nodes": 12000, "ensure_panel_open": False},
            )
        except Exception:
            return []

        dump_text = str(dump.get("dump", "") or "")
        if not dump_text:
            return []

        candidates: list[dict[str, str]] = []
        for match in BANNER_DUMP_DESC_RE.finditer(dump_text):
            desc = str(match.group(1) or "").strip()
            if not desc:
                continue
            sender, body = self._parse_desc_sender_body(desc)
            if not sender and not body:
                continue
            candidates.append({"sender": sender, "body": body, "description": desc})
        return candidates

    def _enrich_placeholders_from_dump_tree(
        self,
        items: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not items:
            return items

        placeholder_idx = [
            idx
            for idx, item in enumerate(items)
            if str(item.get("message_quality", "")).strip() == "system_event_placeholder"
        ]
        if not placeholder_idx:
            return items

        candidates = self._extract_dump_tree_candidates()
        if len(placeholder_idx) != 1 or len(candidates) != 1:
            return items

        idx = placeholder_idx[0]
        item = dict(items[idx])
        cand = candidates[0]
        sender = str(cand.get("sender", "")).strip()
        body = str(cand.get("body", "")).strip()
        if not sender and not body:
            return items

        if sender:
            item["sender"] = sender
        if body:
            item["body"] = body
        item["message_quality"] = "dump_tree_inferred"
        item["source_description"] = cand.get("description", "")

        updated = list(items)
        updated[idx] = item
        return updated

    def _send_openclaw_hook(
        self,
        saved_path: Path,
        new_items: list[dict[str, Any]],
        readable_count: int,
        hidden_count: int,
    ) -> bool:
        if not self.notify_hook_url:
            return False

        now_ts = time.time()
        if now_ts - self.last_hook_notify_at < self.notify_hook_cooldown_sec:
            return False

        token = self.notify_hook_token
        if not token and self.notify_hook_token_env:
            token = str(os.environ.get(self.notify_hook_token_env, "")).strip()
        if not token:
            print(
                f"[{now_text()}] hook skipped: missing token "
                f"(set --notify-hook-token or env {self.notify_hook_token_env})"
            )
            return False

        filtered_items, skipped_count = self._filter_items_by_reply_mode(new_items)
        if not filtered_items:
            print(
                f"[{now_text()}] hook skipped by reply mode "
                f"(mode={self.notify_hook_reply_mode}, skipped={len(new_items)})"
            )
            return False

        filtered_hidden_count = sum(1 for item in filtered_items if self._is_hidden_placeholder(item))
        filtered_readable_count = len(filtered_items) - filtered_hidden_count

        latest_sender = ""
        latest_body = ""
        previews: list[str] = []
        for item in filtered_items:
            if not isinstance(item, dict):
                continue
            if self._is_hidden_placeholder(item):
                continue
            sender = str(item.get("sender", "")).strip() or "Unknown"
            body = str(item.get("body", "")).strip()
            body_compact = " ".join(body.split())
            if body:
                if len(body_compact) > 160:
                    body_compact = f"{body_compact[:160]}..."
                previews.append(f"{sender}: {body_compact}")
            else:
                previews.append(f"{sender}: [no body]")
            if not latest_sender:
                latest_sender = sender
                latest_body = body_compact if body_compact else "[no body]"
            if len(previews) >= self.notify_hook_max_items:
                break

        if latest_sender:
            message_lines = [
                f"--自动hook提醒A：{latest_sender} 发来微信消息「{latest_body}」。",
                f"你现在处于微信自动回复模式：{self._reply_mode_label()}。本次消息已命中模式过滤，必须回复，不要输出 NO_ACTION。",
                "请先给一句简短决策理由，然后立即调用turix-mac执行回复。",
                "调用前必须先明确输出：1) 要定位到谁；2) 计划回复文本；3) 是否按上下文微调（是/否+理由）；4) 任务名（格式 WeChatReply-<sender>-<MMDD-HHMMSS>）。",
                "调用turix-mac执行期间，请持续读取turix日志直到任务结束，再给最终结论。",
                f"消息快照文件: {saved_path}",
                f"本次可读消息数: {filtered_readable_count}，隐藏占位数: {filtered_hidden_count}",
                f"本次被模式过滤跳过数: {skipped_count}",
                "如需补充读取，请使用 wechat-json-inbox 读取该快照中的 NEW 项。",
            ]
            if len(previews) > 1:
                message_lines.append("本批次其他可读消息：")
                for p in previews[1:]:
                    message_lines.append(f"- {p}")
        else:
            message_lines = [
                "--自动hook提醒A：收到微信新事件，但通知正文当前不可见（可能被折叠/隐藏）。",
                f"当前自动回复模式：{self._reply_mode_label()}。",
                "先不要调用turix-mac，输出 NO_ACTION_HIDDEN，并等待下一次可读事件。",
                f"消息快照文件: {saved_path}",
                f"本次可读消息数: {filtered_readable_count}，隐藏占位数: {filtered_hidden_count}",
                f"本次被模式过滤跳过数: {skipped_count}",
            ]

        payload: dict[str, Any] = {
            "message": "\n".join(message_lines),
            "name": self.notify_hook_name,
            "wakeMode": self.notify_hook_wake_mode,
            "deliver": self.notify_hook_deliver,
            "timeoutSeconds": self.notify_hook_timeout_sec,
        }
        if self.notify_hook_agent_id:
            payload["agentId"] = self.notify_hook_agent_id
        if self.notify_hook_session_key:
            payload["sessionKey"] = self.notify_hook_session_key
        if self.notify_hook_thinking:
            payload["thinking"] = self.notify_hook_thinking
        if self.notify_hook_model:
            payload["model"] = self.notify_hook_model

        try:
            _ = http_json(
                "POST",
                self.notify_hook_url,
                payload=payload,
                extra_headers={"Authorization": f"Bearer {token}"},
                timeout_sec=15.0,
            )
            self.last_hook_notify_at = now_ts
            return True
        except Exception as exc:
            print(f"[{now_text()}] hook notify failed: {exc}", file=sys.stderr)
            return False

    def _reply_mode_label(self) -> str:
        if self.notify_hook_reply_mode == "whitelist":
            senders = ", ".join(sorted(self.notify_hook_allow_senders)) or "(empty)"
            return f"whitelist（仅回复：{senders}）"
        if self.notify_hook_reply_mode == "blacklist":
            senders = ", ".join(sorted(self.notify_hook_deny_senders)) or "(empty)"
            return f"blacklist（排除：{senders}）"
        return "all（全量回复）"

    def _sender_allowed_by_mode(self, sender: str) -> bool:
        sender_text = str(sender or "").strip()
        if self.notify_hook_reply_mode == "all":
            return True
        if self.notify_hook_reply_mode == "whitelist":
            return bool(sender_text) and sender_text in self.notify_hook_allow_senders
        return sender_text not in self.notify_hook_deny_senders

    def _filter_items_by_reply_mode(
        self,
        items: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], int]:
        filtered: list[dict[str, Any]] = []
        skipped_count = 0
        for item in items:
            if not isinstance(item, dict):
                continue
            # Hidden placeholders may not have a stable sender; keep them so hook can emit
            # NO_ACTION_HIDDEN instead of silently dropping the event.
            if self._is_hidden_placeholder(item):
                filtered.append(item)
                continue
            sender = str(item.get("sender", "")).strip()
            if self._sender_allowed_by_mode(sender):
                filtered.append(item)
            else:
                skipped_count += 1
        return filtered, skipped_count

    def _best_effort_stop_backend_loop(self) -> None:
        try:
            _ = http_json("POST", f"{self.api_base}/stop", payload={})
        except Exception:
            pass

    def _shutdown_subprocess(self) -> None:
        if self.log_proc and self.log_proc.poll() is None:
            try:
                self.log_proc.terminate()
                self.log_proc.wait(timeout=2)
            except Exception:
                self.log_proc.kill()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="WeChat system-event -> AX scan bridge")
    parser.add_argument("--api-base", default="http://127.0.0.1:8787")
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--debounce-sec", type=float, default=0.25)
    parser.add_argument("--cooldown-sec", type=float, default=0.8)
    parser.add_argument("--retry-count", type=int, default=3)
    parser.add_argument("--retry-interval-sec", type=float, default=0.35)
    parser.add_argument("--open-panel-fallback-cooldown-sec", type=float, default=180.0)
    parser.add_argument("--enable-open-panel-fallback", action="store_true")
    parser.add_argument("--disable-open-panel-fallback", action="store_true")
    parser.add_argument("--trigger-min-interval-sec", type=float, default=0.2)
    parser.add_argument("--max-hourly-files", type=int, default=12)
    parser.add_argument("--notify-hook-url", default="")
    parser.add_argument("--notify-hook-token", default="")
    parser.add_argument("--notify-hook-token-env", default="OPENCLAW_HOOKS_TOKEN")
    parser.add_argument("--notify-hook-name", default="WeChat")
    parser.add_argument("--notify-hook-agent-id", default="")
    parser.add_argument("--notify-hook-session-key", default="hook:wechat-inbox")
    parser.add_argument("--notify-hook-wake-mode", choices=["now", "next-heartbeat"], default="now")
    parser.add_argument("--notify-hook-thinking", default="low")
    parser.add_argument("--notify-hook-model", default="")
    parser.add_argument("--notify-hook-timeout-sec", type=int, default=120)
    parser.add_argument("--notify-hook-deliver", action="store_true", default=False)
    parser.add_argument("--notify-hook-cooldown-sec", type=float, default=1.5)
    parser.add_argument("--notify-hook-max-items", type=int, default=5)
    parser.add_argument("--notify-hook-reply-mode", choices=["whitelist", "blacklist", "all"], default="whitelist")
    parser.add_argument("--notify-hook-allow-senders", default="")
    parser.add_argument("--notify-hook-deny-senders", default="")
    parser.add_argument("--open-panel", action="store_true", default=False)
    parser.add_argument("--no-open-panel", dest="open_panel", action="store_false")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    enable_open_panel_fallback = bool(args.enable_open_panel_fallback)
    if args.disable_open_panel_fallback:
        enable_open_panel_fallback = False

    bridge = Bridge(
        api_base=args.api_base,
        output_json=Path(args.output_json).expanduser().resolve(),
        debounce_sec=args.debounce_sec,
        cooldown_sec=args.cooldown_sec,
        open_panel=args.open_panel,
        retry_count=args.retry_count,
        retry_interval_sec=args.retry_interval_sec,
        open_panel_fallback_cooldown_sec=args.open_panel_fallback_cooldown_sec,
        enable_open_panel_fallback=enable_open_panel_fallback,
        trigger_min_interval_sec=args.trigger_min_interval_sec,
        max_hourly_files=args.max_hourly_files,
        notify_hook_url=args.notify_hook_url,
        notify_hook_token=args.notify_hook_token,
        notify_hook_token_env=args.notify_hook_token_env,
        notify_hook_name=args.notify_hook_name,
        notify_hook_agent_id=args.notify_hook_agent_id,
        notify_hook_session_key=args.notify_hook_session_key,
        notify_hook_wake_mode=args.notify_hook_wake_mode,
        notify_hook_thinking=args.notify_hook_thinking,
        notify_hook_model=args.notify_hook_model,
        notify_hook_timeout_sec=args.notify_hook_timeout_sec,
        notify_hook_deliver=args.notify_hook_deliver,
        notify_hook_cooldown_sec=args.notify_hook_cooldown_sec,
        notify_hook_max_items=args.notify_hook_max_items,
        notify_hook_reply_mode=args.notify_hook_reply_mode,
        notify_hook_allow_senders=args.notify_hook_allow_senders,
        notify_hook_deny_senders=args.notify_hook_deny_senders,
    )

    def _handle_sig(_sig: int, _frame: Any) -> None:
        bridge.stop_event.set()

    signal.signal(signal.SIGINT, _handle_sig)
    signal.signal(signal.SIGTERM, _handle_sig)

    bridge.start()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
