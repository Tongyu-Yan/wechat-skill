# WeChat Listener Self Managed Setup

Goal:

- OpenClaw auto-starts WeChat listener on gateway startup.
- Press `Command+Shift+1` to stop the listener hook immediately.

## 1) Install listener with reply mode

```bash
bash {baseDir}/scripts/listener_ctl.sh install \
  --bridge-script /ABS/PATH/TO/wechat_event_trigger_bridge.py \
  --api-base http://127.0.0.1:8787 \
  --output-json ~/.openclaw/state/wechat_messages.json \
  --hook-url http://127.0.0.1:18789/hooks/agent \
  --hook-token "REPLACE_WITH_A_LONG_RANDOM_TOKEN" \
  --hook-agent-id main \
  --hook-session-key agent:main:main \
  --hook-name WeChatFast \
  --hook-model openai-codex/gpt-5.2-codex \
  --hook-timeout-sec 900 \
  --hook-cooldown-sec 0.40 \
  --hook-reply-mode whitelist \
  --hook-allow-senders "y"
```

Notes:

- `listener_ctl.sh install` now installs hotkey stop service by default.
- To skip hotkey install once, add `--no-hotkey-stop`.

## 2) Enable OpenClaw gateway startup autostart

```bash
bash {baseDir}/scripts/install_gateway_autostart_hook.sh \
  --listener-ctl ~/.openclaw/skills/wechat-event-autopilot/scripts/listener_ctl.sh \
  --listener-label ai.openclaw.wechat-listener
```

This creates and enables hook `wechat-listener-autostart` under workspace `hooks/`.

## 3) Restart gateway once

```bash
openclaw gateway restart --force
```

After this, listener will be started automatically by OpenClaw on each gateway startup.

## 4) Use hotkey to stop listener hook

- Press `Command+Shift+1`
- Effect: runs `listener_ctl.sh stop` for label `ai.openclaw.wechat-listener`

Hotkey service logs:

- `~/.openclaw/logs/ai.openclaw.wechat-listener-hotkey-stop.log`
- `~/.openclaw/logs/ai.openclaw.wechat-listener-hotkey-stop.err.log`

## 5) Verify

```bash
bash {baseDir}/scripts/listener_ctl.sh status
bash {baseDir}/scripts/hotkey_ctl.sh status
openclaw hooks info wechat-listener-autostart
```

## Troubleshooting

- If hotkey does not trigger, grant Accessibility permission to Terminal/Python:
  - System Settings -> Privacy and Security -> Accessibility
- If hotkey service keeps restarting with `No module named 'Quartz'`:
  - reinstall hotkey service with a Python that supports Quartz:
  - `bash {baseDir}/scripts/hotkey_ctl.sh install --python-bin /ABS/PATH/TO/python3`
  - verify: `/ABS/PATH/TO/python3 -c "import Quartz"`
- If listener is not auto-started, confirm:
  - `openclaw config get hooks.internal.enabled` is `true`
  - hook exists in workspace: `hooks/wechat-listener-autostart`
  - hook enabled: `openclaw hooks list | rg wechat-listener-autostart`
