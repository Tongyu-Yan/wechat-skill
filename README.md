# WeChat Event Autopilot - Friend Install Guide

Chinese version: [README.zh-CN.md](README.zh-CN.md)

This package provides an OpenClaw skill for WeChat event-driven monitoring on macOS.

Core flow:

1. Listen to WeChat notification events.
2. Scan unread messages and write hourly JSON snapshots.
3. Trigger OpenClaw `/hooks/agent`.
4. Let OpenClaw decide whether to auto-reply (can call `turix-mac`).

## Plain-Language Overview

This repository is not a standalone product. You must install and set up [TuriX-CUA](https://github.com/TurixAI/TuriX-CUA) before using it.

In simple terms, it works like this:

1. Read the latest WeChat message events from the macOS Notification Center.
2. Send those events to OpenClaw through hooks.
3. Let OpenClaw decide what to do, then use TuriX to operate the computer for actions such as replying in WeChat.

It currently supports three reply scope modes:

- `whitelist`
- `blacklist`
- `all`

Choose the mode based on your needs, and tell OpenClaw clearly which mode you want.

Please note: due to WeChat's strict risk controls, this solution currently relies on macOS Notification Center events to read messages; delays, collapsed notifications, or occluded notifications are expected.

## Repository Overview

This repository packages a production-style OpenClaw skill for event-driven WeChat automation on macOS.

Main components:

- `scripts/wechat_event_trigger_bridge.py`: listens to macOS WeChat notification events, scans unread messages, and writes hourly JSON snapshots.
- `scripts/listener_ctl.sh`: one-command install/start/stop/restart/status/logs wrapper for launchd service management.
- `scripts/decide_wechat_reply.py`: guarded reply decision engine (supports dry-run or optional `turix-mac` execution).
- `scripts/install_gateway_autostart_hook.sh`: optional gateway startup hook for zero-manual daily operation.
- `scripts/wechat_stop_hotkey.py`: optional hotkey stopper (`Command+Shift+1`) for emergency listener stop.

Open-source note:

- Docs use placeholder credentials (for example `REPLACE_WITH_A_LONG_RANDOM_TOKEN`).
- URLs in examples default to local loopback endpoints (`127.0.0.1`).
- Runtime message snapshots and local env files are generated on each user's own machine.

## Reply Modes (Important)

Before install, choose one reply mode for auto-reply filtering:

- `whitelist`: only reply to listed senders.
- `blacklist`: reply to everyone except listed senders.
- `all`: reply to everyone.

Mode requirements:

- `whitelist` requires `--hook-allow-senders` (or repeated `--hook-allow-sender`).
- `blacklist` requires `--hook-deny-senders` (or repeated `--hook-deny-sender`).
- `all` ignores allow/deny sender lists.

## 0) Requirements

- macOS
- Installed and working [TuriX-CUA](https://github.com/TurixAI/TuriX-CUA)
- OpenClaw CLI + gateway
- Python 3
- WeChat backend API available at `http://127.0.0.1:8787` (or your own endpoint)

## 1) Install Skill into OpenClaw Workspace

Check active workspace:

```bash
openclaw config get agents.defaults.workspace
```

Copy skill to workspace:

```bash
WORKSPACE="$(openclaw config get agents.defaults.workspace)"
SKILL_DIR="${WORKSPACE}/skills/wechat-event-autopilot"
mkdir -p "${SKILL_DIR}"
cp -R ./scripts ./references ./SKILL.md ./SELF_MANAGED_SETUP.md ./README.md ./README.zh-CN.md "${SKILL_DIR}/"
```

## 2) Enable Hooks

```bash
openclaw config set hooks.enabled true
openclaw config set hooks.token '"REPLACE_WITH_A_LONG_RANDOM_TOKEN"'
openclaw config set hooks.path '"/hooks"'
openclaw config set hooks.allowRequestSessionKey true
openclaw config set hooks.allowedSessionKeyPrefixes '["hook:","agent:"]'
```

## 3) Install Listener (Choose Reply Mode First)

`listener_ctl.sh install` requires one reply mode:

- `whitelist`: only reply to listed senders
- `blacklist`: reply to everyone except listed senders
- `all`: reply to everyone

Run from installed skill path:

```bash
WORKSPACE="$(openclaw config get agents.defaults.workspace)"
SKILL_DIR="${WORKSPACE}/skills/wechat-event-autopilot"
```

Whitelist example:

```bash
bash "${SKILL_DIR}/scripts/listener_ctl.sh" install \
  --bridge-script "${SKILL_DIR}/scripts/wechat_event_trigger_bridge.py" \
  --api-base http://127.0.0.1:8787 \
  --output-json ~/.openclaw/state/wechat_messages.json \
  --hook-url http://127.0.0.1:18789/hooks/agent \
  --hook-token "REPLACE_WITH_A_LONG_RANDOM_TOKEN" \
  --hook-token-env OPENCLAW_HOOKS_TOKEN \
  --hook-agent-id main \
  --hook-session-key agent:main:main \
  --hook-name WeChat \
  --hook-thinking low \
  --hook-reply-mode whitelist \
  --hook-allow-senders "y" \
  --enable-open-panel-fallback
```

Blacklist example:

```bash
bash "${SKILL_DIR}/scripts/listener_ctl.sh" install \
  --bridge-script "${SKILL_DIR}/scripts/wechat_event_trigger_bridge.py" \
  --api-base http://127.0.0.1:8787 \
  --output-json ~/.openclaw/state/wechat_messages.json \
  --hook-url http://127.0.0.1:18789/hooks/agent \
  --hook-token "REPLACE_WITH_A_LONG_RANDOM_TOKEN" \
  --hook-agent-id main \
  --hook-session-key agent:main:main \
  --hook-reply-mode blacklist \
  --hook-deny-senders "老板,广告群"
```

Full mode example:

```bash
bash "${SKILL_DIR}/scripts/listener_ctl.sh" install \
  --bridge-script "${SKILL_DIR}/scripts/wechat_event_trigger_bridge.py" \
  --api-base http://127.0.0.1:8787 \
  --output-json ~/.openclaw/state/wechat_messages.json \
  --hook-url http://127.0.0.1:18789/hooks/agent \
  --hook-token "REPLACE_WITH_A_LONG_RANDOM_TOKEN" \
  --hook-agent-id main \
  --hook-session-key agent:main:main \
  --hook-reply-mode all
```

## 4) Daily Operations

```bash
bash "${SKILL_DIR}/scripts/listener_ctl.sh" status
bash "${SKILL_DIR}/scripts/listener_ctl.sh" restart
bash "${SKILL_DIR}/scripts/listener_ctl.sh" logs --lines 200
bash "${SKILL_DIR}/scripts/listener_ctl.sh" stop
```

Hotkey stopper:

- `Command+Shift+1` stops the listener service.

## 5) Verify End-to-End

Check gateway and session:

```bash
openclaw gateway health
openclaw gateway call sessions.list --json --params '{}'
```

Send a hook test:

```bash
python3 "${SKILL_DIR}/scripts/notify_openclaw_hook.py" \
  --hook-url http://127.0.0.1:18789/hooks/agent \
  --token "REPLACE_WITH_A_LONG_RANDOM_TOKEN" \
  --agent-id main \
  --session-key agent:main:main \
  --message "Hook test from wechat-event-autopilot"
```

Expected:

- listener status shows `state = running`
- new events show `trigger received` and `scan done`
- hook message appears in session `agent:main:main`

## 6) Optional: Auto-Start on Gateway Boot

```bash
bash "${SKILL_DIR}/scripts/install_gateway_autostart_hook.sh" \
  --listener-ctl "${SKILL_DIR}/scripts/listener_ctl.sh" \
  --listener-label ai.openclaw.wechat-listener
```

Then restart gateway once:

```bash
openclaw gateway restart --force
```

## Notes

- Due to WeChat's strict risk controls, this solution currently relies on macOS Notification Center events to read messages; delays, collapsed notifications, or occluded notifications are expected.
- Run launchd scripts from trusted local paths (not Desktop temp copies), otherwise macOS privacy controls may block execution.
- In whitelist mode, sender names must match exactly as captured from WeChat notifications.
- Hidden/stacked notifications can be delayed; `--enable-open-panel-fallback` improves reliability.
