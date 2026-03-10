#!/usr/bin/env python3
"""Global hotkey watcher to stop the WeChat listener service.

Default shortcut:
- Command + Shift + 1
"""

from __future__ import annotations

import argparse
import signal
import subprocess
import sys
import time
from typing import Any

try:
    import Quartz  # type: ignore
except Exception as exc:  # pragma: no cover
    print(f"ERROR: failed to import Quartz: {exc}", file=sys.stderr)
    raise SystemExit(2)


def now_text() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())


class HotkeyStopper:
    def __init__(
        self,
        listener_ctl: str,
        listener_label: str,
        keycode: int,
        require_command: bool,
        require_shift: bool,
        debounce_sec: float,
    ) -> None:
        self.listener_ctl = listener_ctl
        self.listener_label = listener_label
        self.keycode = int(keycode)
        self.require_command = bool(require_command)
        self.require_shift = bool(require_shift)
        self.debounce_sec = max(0.1, float(debounce_sec))
        self.last_trigger_at = 0.0
        self._run_loop: Any = None

    def _flags_match(self, flags: int) -> bool:
        if self.require_command and not (flags & Quartz.kCGEventFlagMaskCommand):
            return False
        if self.require_shift and not (flags & Quartz.kCGEventFlagMaskShift):
            return False
        return True

    def _on_hotkey(self) -> None:
        now_ts = time.time()
        if now_ts - self.last_trigger_at < self.debounce_sec:
            return
        self.last_trigger_at = now_ts

        cmd = ["bash", self.listener_ctl, "--label", self.listener_label, "stop"]
        try:
            proc = subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                text=True,
                timeout=12,
            )
            output = (proc.stdout or proc.stderr or "").strip()
            print(
                f"[{now_text()}] hotkey matched -> stop listener "
                f"(label={self.listener_label}, rc={proc.returncode})"
            )
            if output:
                print(output)
        except Exception as exc:
            print(f"[{now_text()}] hotkey stop failed: {exc}", file=sys.stderr)

    def _callback(self, _proxy: Any, event_type: int, event: Any, _refcon: Any) -> Any:
        if event_type == Quartz.kCGEventTapDisabledByTimeout:
            return event
        if event_type != Quartz.kCGEventKeyDown:
            return event

        keycode = int(
            Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventKeycode)
        )
        if keycode != self.keycode:
            return event

        flags = int(Quartz.CGEventGetFlags(event))
        if not self._flags_match(flags):
            return event

        self._on_hotkey()
        return event

    def _handle_signal(self, _sig: int, _frame: Any) -> None:
        if self._run_loop is not None:
            Quartz.CFRunLoopStop(self._run_loop)

    def run(self) -> int:
        print(
            f"[{now_text()}] hotkey watcher started "
            f"(shortcut=Cmd+Shift+1 keycode={self.keycode}, listener={self.listener_label})"
        )

        callback = self._callback
        event_mask = Quartz.CGEventMaskBit(Quartz.kCGEventKeyDown)
        tap = Quartz.CGEventTapCreate(
            Quartz.kCGSessionEventTap,
            Quartz.kCGHeadInsertEventTap,
            Quartz.kCGEventTapOptionDefault,
            event_mask,
            callback,
            None,
        )

        if tap is None:
            print(
                "ERROR: failed to create event tap. Grant Accessibility permission "
                "to Terminal/Python and retry.",
                file=sys.stderr,
            )
            return 2

        run_loop_source = Quartz.CFMachPortCreateRunLoopSource(None, tap, 0)
        self._run_loop = Quartz.CFRunLoopGetCurrent()
        Quartz.CFRunLoopAddSource(
            self._run_loop, run_loop_source, Quartz.kCFRunLoopCommonModes
        )
        Quartz.CGEventTapEnable(tap, True)

        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

        Quartz.CFRunLoopRun()
        print(f"[{now_text()}] hotkey watcher stopped")
        return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Global hotkey watcher for WeChat listener stop")
    parser.add_argument(
        "--listener-ctl",
        default="~/.openclaw/skills/wechat-event-autopilot/scripts/listener_ctl.sh",
    )
    parser.add_argument("--listener-label", default="ai.openclaw.wechat-listener")
    parser.add_argument("--keycode", type=int, default=18, help="macOS keycode for '1' on ANSI layout")
    parser.add_argument("--require-command", action="store_true", default=True)
    parser.add_argument("--no-require-command", dest="require_command", action="store_false")
    parser.add_argument("--require-shift", action="store_true", default=True)
    parser.add_argument("--no-require-shift", dest="require_shift", action="store_false")
    parser.add_argument("--debounce-sec", type=float, default=0.8)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    stopper = HotkeyStopper(
        listener_ctl=args.listener_ctl,
        listener_label=args.listener_label,
        keycode=args.keycode,
        require_command=args.require_command,
        require_shift=args.require_shift,
        debounce_sec=args.debounce_sec,
    )
    return stopper.run()


if __name__ == "__main__":
    raise SystemExit(main())

