---
name: wechat-event-autopilot
description: Deploy and operate an event-driven WeChat listener on macOS that pushes new notification events into OpenClaw via /hooks/agent, stores hourly JSON snapshots, and optionally runs guarded auto-reply decisions that can call turix-mac.
metadata:
  {
    "openclaw":
      {
        "emoji": "🛰️",
        "os": ["darwin"],
        "requires": { "bins": ["python3", "openclaw", "launchctl"] },
      },
  }
---

# wechat-event-autopilot

Use this skill to make WeChat monitoring fully event-driven:

1. Backend bridge listens to macOS WeChat notification events.
2. Bridge writes hourly JSON snapshots.
3. Bridge triggers OpenClaw `/hooks/agent` on new events.
4. OpenClaw decides whether to call `turix-mac` for reply.

Dependencies:

- WeChat AX backend API process (default `http://127.0.0.1:8787`)
- Bridge script `scripts/wechat_event_trigger_bridge.py` (included in this skill package)
- OpenClaw gateway with hooks enabled

## Quick Start

### 0) Install in active OpenClaw workspace

Check your active workspace first:

```bash
openclaw config get agents.defaults.workspace
```

Put this skill under `<workspace>/skills/<skill-name>`, then start a new session.
Avoid running launchd service scripts from Desktop paths because macOS privacy controls can block execution.

### 1) Enable OpenClaw hooks

```bash
openclaw config set hooks.enabled true
openclaw config set hooks.token '"REPLACE_WITH_A_LONG_RANDOM_TOKEN"'
openclaw config set hooks.path '"/hooks"'
openclaw config set hooks.allowRequestSessionKey true
openclaw config set hooks.allowedSessionKeyPrefixes '["hook:"]'
```

### 2) Export hook token for listener runtime

```bash
export OPENCLAW_HOOKS_TOKEN="REPLACE_WITH_A_LONG_RANDOM_TOKEN"
```

If you use launchd (recommended), also pass `--hook-token` during install so the token is written into the listener env file (`chmod 600`).

### 3) Install background listener service

```bash
bash {baseDir}/scripts/listener_ctl.sh install \
  --bridge-script {baseDir}/scripts/wechat_event_trigger_bridge.py \
  --api-base http://127.0.0.1:8787 \
  --output-json ~/.openclaw/state/wechat_messages.json \
  --hook-url http://127.0.0.1:18789/hooks/agent \
  --hook-token \"REPLACE_WITH_A_LONG_RANDOM_TOKEN\" \
  --hook-token-env OPENCLAW_HOOKS_TOKEN \
  --hook-agent-id main \
  --hook-session-key hook:wechat-inbox \
  --hook-reply-mode whitelist \
  --hook-allow-senders "y" \
  --max-hourly-files 12 \
  --disable-open-panel-fallback
```

If `--bridge-script` is omitted, deploy script tries to auto-detect nearby bridge scripts. For this package, prefer explicitly setting `{baseDir}/scripts/wechat_event_trigger_bridge.py`.

### 3.1) Reply Mode (Required)

You must define one reply mode before installing listener:

- `whitelist`: only reply to listed senders
- `blacklist`: reply to everyone except listed senders
- `all`: reply to all senders

Examples:

```bash
# whitelist mode
--hook-reply-mode whitelist --hook-allow-senders "y,Jennifer"

# blacklist mode
--hook-reply-mode blacklist --hook-deny-senders "老板,广告群"

# full mode
--hook-reply-mode all
```

Notes:

- `whitelist` requires `--hook-allow-senders` (or repeated `--hook-allow-sender`).
- `blacklist` requires `--hook-deny-senders` (or repeated `--hook-deny-sender`).
- `all` ignores allow/deny lists.

### 4) Operate service

```bash
bash {baseDir}/scripts/listener_ctl.sh status
bash {baseDir}/scripts/listener_ctl.sh restart
bash {baseDir}/scripts/listener_ctl.sh logs --lines 200
```

`listener_ctl.sh install` now installs a hotkey stop service by default:

- `Command+Shift+1` -> stop WeChat listener hook service
- To skip once: add `--no-hotkey-stop`

## OpenClaw Self Start + Hotkey Stop

Use this guide for zero-manual startup:

- [SELF_MANAGED_SETUP.md](SELF_MANAGED_SETUP.md)

Key pieces:

1. Install listener with your `reply-mode`.
2. Run `scripts/install_gateway_autostart_hook.sh` once.
3. Restart gateway.
4. Listener is auto-started by OpenClaw on every gateway startup.
5. Press `Command+Shift+1` to stop listener hook at any time.

## Main Chat Visibility Fix (Important)

If the WeChat hook runs but you cannot see output in your active `openclaw tui` chat, the hook is usually running in an isolated `hook:*` session.

Recommended setup for visible output in main chat:

1. Allow request session keys under both `hook:` and `agent:` prefixes.
2. Route listener hook runs to `agent:main:main`.
3. Restart gateway after hook policy changes.
4. Restart listener after env/script changes.

```bash
# 1) Hook session key policy
openclaw config set hooks.enabled true
openclaw config set hooks.allowRequestSessionKey true
openclaw config set hooks.allowedSessionKeyPrefixes '["hook:","agent:"]'

# 2) Restart gateway so new policy is applied
openclaw gateway restart --force

# 3) Install (or reinstall) listener with main-session routing
bash {baseDir}/scripts/listener_ctl.sh install \
  --bridge-script /ABS/PATH/TO/wechat_event_trigger_bridge.py \
  --api-base http://127.0.0.1:8787 \
  --output-json ~/.openclaw/state/wechat_messages.json \
  --hook-url http://127.0.0.1:18789/hooks/agent \
  --hook-token "REPLACE_WITH_A_LONG_RANDOM_TOKEN" \
  --hook-agent-id main \
  --hook-session-key agent:main:main \
  --hook-name WeChatFast \
  --hook-thinking off \
  --hook-model openai-codex/gpt-5.2-codex \
  --hook-timeout-sec 45 \
  --hook-cooldown-sec 0.40 \
  --hook-reply-mode whitelist \
  --hook-allow-senders "y"
```

If launchd `restart` hits a bootstrap I/O error, use `stop` then `start`:

```bash
bash {baseDir}/scripts/listener_ctl.sh stop
bash {baseDir}/scripts/listener_ctl.sh start
```

Quick verification:

```bash
openclaw gateway call sessions.list --json --params '{}'
bash {baseDir}/scripts/listener_ctl.sh status
```

Expected:

- listener args include `--notify-hook-session-key agent:main:main`
- new hook events appear under `agent:main:main` instead of only `agent:main:hook:*`

## 10-Second Fast-Reaction Preset

Use this preset when you want OpenClaw to react as quickly as possible after a readable notification arrives:

```bash
bash {baseDir}/scripts/listener_ctl.sh install \
  --bridge-script /ABS/PATH/TO/wechat_event_trigger_bridge.py \
  --api-base http://127.0.0.1:8787 \
  --output-json ~/.openclaw/state/wechat_messages.json \
  --debounce-sec 0.10 \
  --cooldown-sec 0.25 \
  --retry-count 2 \
  --retry-interval-sec 0.15 \
  --trigger-min-interval-sec 0.10 \
  --disable-open-panel-fallback \
  --hook-url http://127.0.0.1:18789/hooks/agent \
  --hook-token "REPLACE_WITH_A_LONG_RANDOM_TOKEN" \
  --hook-agent-id main \
  --hook-session-key hook:wechat-fast \
  --hook-name WeChatFast \
  --hook-thinking off \
  --hook-model openai-codex/gpt-5.2-codex \
  --hook-timeout-sec 45 \
  --hook-cooldown-sec 0.40 \
  --hook-reply-mode all
```

Notes:

- This is a best-effort target for readable text notifications; hidden/stacked banners can still delay or block full-text extraction.
- If reply itself requires long desktop navigation in `turix-mac`, total completion can exceed 10 seconds.

## Hook Test

Send a one-shot hook trigger to validate OpenClaw ingress:

```bash
python3 {baseDir}/scripts/notify_openclaw_hook.py \
  --hook-url http://127.0.0.1:18789/hooks/agent \
  --token-env OPENCLAW_HOOKS_TOKEN \
  --message "Hook test from wechat-event-autopilot" \
  --agent-id main \
  --session-key hook:wechat-inbox
```

## Guarded Auto-Reply Decision

By default, this script only decides and prints output. It does not reply unless `--execute-turix` is given.

```bash
# Decision only (safe default)
python3 {baseDir}/scripts/decide_wechat_reply.py \
  --input ~/.openclaw/state/wechat_messages.json \
  --mode new \
  --format json

# Decision + execute turix replies (opt-in)
python3 {baseDir}/scripts/decide_wechat_reply.py \
  --input ~/.openclaw/state/wechat_messages.json \
  --mode new \
  --policy {baseDir}/references/policy.example.json \
  --execute-turix \
  --turix-script ~/.openclaw/skills/turix-mac/scripts/run_turix.sh
```

Policy fields:

- `allow_senders`: whitelist candidates for decision script.
- `deny_senders`: blacklist candidates for decision script.
- `trigger_keywords`: optional keyword gate.
- `cooldown_sec`: per-sender cooldown.
- `max_actions`: max turix calls per run.

## Recommended Hook Prompt Pattern

Use a stable prompt in hook-triggered runs:

1. Read new items from `~/.openclaw/state/wechat_messages.json` generated by this skill's bridge.
2. If no actionable messages, output `NO_ACTION` (or `NO_ACTION_HIDDEN` for hidden placeholders).
3. If actionable and mode-filtered in, before calling `turix-mac`, explicitly state target chat, planned reply text, whether context-based rewrite is needed, and the task name you will set.
4. Always rename the turix task first (recommended format: `WeChatReply-<sender>-<MMDD-HHMMSS>`), then execute.
5. During `turix-mac` execution, continuously read/track turix logs until success or failure.
6. Keep replies short and avoid unsafe commitments.

Current bridge hook message format is sender/body aware and mode-aware:

- Example first line: `--自动hook提醒A：<sender> 发来微信消息「<body>」。`
- It includes mode info (`whitelist` / `blacklist` / `all`) and requires direct reply once sender passes mode filter.
- If notification body is hidden, bridge asks for `NO_ACTION_HIDDEN`.

Current default first-line style in hook prompt:

- `--自动hook提醒A：<sender> 发来微信消息「<body>」。`

## Scripts

- `scripts/listener_ctl.sh`: install/start/stop/restart/status/logs/uninstall for launchd listener.
- `scripts/hotkey_ctl.sh`: install/start/stop/restart/status/logs/uninstall for hotkey stop service.
- `scripts/deploy_listener_launchd.sh`: writes env + plist and bootstraps launchd.
- `scripts/deploy_stop_hotkey_launchd.sh`: installs global hotkey service for stop shortcut.
- `scripts/run_listener.sh`: service entrypoint that starts bridge with env config.
- `scripts/wechat_stop_hotkey.py`: global key watcher (`Command+Shift+1`) that stops listener.
- `scripts/install_gateway_autostart_hook.sh`: create and enable gateway startup hook for autostart.
- `scripts/notify_openclaw_hook.py`: manual `/hooks/agent` trigger.
- `scripts/decide_wechat_reply.py`: deterministic guardrail decision + optional turix execution.
