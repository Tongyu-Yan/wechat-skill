#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_RUNNER_SCRIPT="${SCRIPT_DIR}/run_listener.sh"

LABEL="ai.openclaw.wechat-listener"
PYTHON_BIN="python3"
BRIDGE_SCRIPT=""
API_BASE="http://127.0.0.1:8787"
OUTPUT_JSON="${HOME}/.openclaw/state/wechat_messages.json"
ENV_FILE="${HOME}/.openclaw/state/wechat-listener.env"
DEBOUNCE_SEC="0.25"
COOLDOWN_SEC="0.8"
RETRY_COUNT="3"
RETRY_INTERVAL_SEC="0.35"
TRIGGER_MIN_INTERVAL_SEC="0.2"
MAX_HOURLY_FILES="12"
OPEN_PANEL="0"
ENABLE_OPEN_PANEL_FALLBACK="0"
OPEN_PANEL_FALLBACK_COOLDOWN_SEC="180"

HOOK_URL="http://127.0.0.1:18789/hooks/agent"
HOOK_TOKEN=""
HOOK_TOKEN_ENV="OPENCLAW_HOOKS_TOKEN"
HOOK_NAME="WeChat"
HOOK_AGENT_ID=""
HOOK_SESSION_KEY="hook:wechat-inbox"
HOOK_WAKE_MODE="now"
HOOK_THINKING="low"
HOOK_MODEL=""
HOOK_TIMEOUT_SEC="120"
HOOK_DELIVER="0"
HOOK_COOLDOWN_SEC="1.5"
HOOK_MAX_ITEMS="5"
HOOK_REPLY_MODE=""
HOOK_ALLOW_SENDERS=""
HOOK_DENY_SENDERS=""
HOOK_REPLY_MODE_SET="0"

RUNNER_SCRIPT="$DEFAULT_RUNNER_SCRIPT"

usage() {
  cat <<'USAGE'
Usage: deploy_listener_launchd.sh [options]

Install and start a launchd service that runs the WeChat event bridge.

Options:
  --label <label>                       LaunchAgent label (default: ai.openclaw.wechat-listener)
  --python-bin <path>                   Python executable (default: python3)
  --bridge-script <path>                Path to wechat_event_trigger_bridge.py
  --api-base <url>                      Backend API base (default: http://127.0.0.1:8787)
  --output-json <path>                  Base JSON path (default: ~/.openclaw/state/wechat_messages.json)
  --env-file <path>                     Env file for runtime config
  --runner-script <path>                Service entry script
  --debounce-sec <float>
  --cooldown-sec <float>
  --retry-count <int>
  --retry-interval-sec <float>
  --trigger-min-interval-sec <float>
  --max-hourly-files <int>
  --open-panel                          Enable open_panel mode
  --no-open-panel                       Disable open_panel mode (default)
  --enable-open-panel-fallback          Allow one-shot panel fallback
  --disable-open-panel-fallback         Disable fallback (default)
  --open-panel-fallback-cooldown-sec <float>

  --hook-url <url>                      OpenClaw /hooks/agent URL
  --hook-token <token>                  Hook token value (optional)
  --hook-token-env <name>               Env var name for token (default: OPENCLAW_HOOKS_TOKEN)
  --hook-name <name>                    Hook run name (default: WeChat)
  --hook-agent-id <id>                  Agent id for isolated run
  --hook-session-key <key>              Session key (default: hook:wechat-inbox)
  --hook-wake-mode <now|next-heartbeat>
  --hook-thinking <level>
  --hook-model <model>
  --hook-timeout-sec <int>
  --hook-deliver                        Deliver hook run result to channel
  --hook-no-deliver                     Don't deliver (default)
  --hook-cooldown-sec <float>
  --hook-max-items <int>
  --hook-reply-mode <whitelist|blacklist|all>  Required. Define auto-reply mode first.
  --hook-allow-senders <csv>            Sender allowlist (required for whitelist mode)
  --hook-deny-senders <csv>             Sender denylist (used by blacklist mode)
  --hook-allow-sender <name>            Add one sender to allowlist (repeatable)
  --hook-deny-sender <name>             Add one sender to denylist (repeatable)

  -h, --help                            Show this help
USAGE
}

detect_bridge_script() {
  local skills_dir candidate_a candidate_b
  skills_dir="$(cd "${SCRIPT_DIR}/.." && pwd)"
  candidate_a="${skills_dir}/../wechat-json-inbox/scripts/wechat_event_trigger_bridge.py"
  candidate_b="${skills_dir}/../../wechat-json-inbox/scripts/wechat_event_trigger_bridge.py"

  if [[ -f "$candidate_a" ]]; then
    echo "$candidate_a"
    return 0
  fi
  if [[ -f "$candidate_b" ]]; then
    echo "$candidate_b"
    return 0
  fi
  return 1
}

append_csv() {
  local current="$1"
  local value="$2"
  if [[ -z "$current" ]]; then
    printf '%s' "$value"
  else
    printf '%s,%s' "$current" "$value"
  fi
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --label) LABEL="$2"; shift 2 ;;
    --python-bin) PYTHON_BIN="$2"; shift 2 ;;
    --bridge-script) BRIDGE_SCRIPT="$2"; shift 2 ;;
    --api-base) API_BASE="$2"; shift 2 ;;
    --output-json) OUTPUT_JSON="$2"; shift 2 ;;
    --env-file) ENV_FILE="$2"; shift 2 ;;
    --runner-script) RUNNER_SCRIPT="$2"; shift 2 ;;
    --debounce-sec) DEBOUNCE_SEC="$2"; shift 2 ;;
    --cooldown-sec) COOLDOWN_SEC="$2"; shift 2 ;;
    --retry-count) RETRY_COUNT="$2"; shift 2 ;;
    --retry-interval-sec) RETRY_INTERVAL_SEC="$2"; shift 2 ;;
    --trigger-min-interval-sec) TRIGGER_MIN_INTERVAL_SEC="$2"; shift 2 ;;
    --max-hourly-files) MAX_HOURLY_FILES="$2"; shift 2 ;;
    --open-panel) OPEN_PANEL="1"; shift ;;
    --no-open-panel) OPEN_PANEL="0"; shift ;;
    --enable-open-panel-fallback) ENABLE_OPEN_PANEL_FALLBACK="1"; shift ;;
    --disable-open-panel-fallback) ENABLE_OPEN_PANEL_FALLBACK="0"; shift ;;
    --open-panel-fallback-cooldown-sec) OPEN_PANEL_FALLBACK_COOLDOWN_SEC="$2"; shift 2 ;;

    --hook-url) HOOK_URL="$2"; shift 2 ;;
    --hook-token) HOOK_TOKEN="$2"; shift 2 ;;
    --hook-token-env) HOOK_TOKEN_ENV="$2"; shift 2 ;;
    --hook-name) HOOK_NAME="$2"; shift 2 ;;
    --hook-agent-id) HOOK_AGENT_ID="$2"; shift 2 ;;
    --hook-session-key) HOOK_SESSION_KEY="$2"; shift 2 ;;
    --hook-wake-mode) HOOK_WAKE_MODE="$2"; shift 2 ;;
    --hook-thinking) HOOK_THINKING="$2"; shift 2 ;;
    --hook-model) HOOK_MODEL="$2"; shift 2 ;;
    --hook-timeout-sec) HOOK_TIMEOUT_SEC="$2"; shift 2 ;;
    --hook-deliver) HOOK_DELIVER="1"; shift ;;
    --hook-no-deliver) HOOK_DELIVER="0"; shift ;;
    --hook-cooldown-sec) HOOK_COOLDOWN_SEC="$2"; shift 2 ;;
    --hook-max-items) HOOK_MAX_ITEMS="$2"; shift 2 ;;
    --hook-reply-mode) HOOK_REPLY_MODE="$2"; HOOK_REPLY_MODE_SET="1"; shift 2 ;;
    --hook-allow-senders) HOOK_ALLOW_SENDERS="$2"; shift 2 ;;
    --hook-deny-senders) HOOK_DENY_SENDERS="$2"; shift 2 ;;
    --hook-allow-sender) HOOK_ALLOW_SENDERS="$(append_csv "$HOOK_ALLOW_SENDERS" "$2")"; shift 2 ;;
    --hook-deny-sender) HOOK_DENY_SENDERS="$(append_csv "$HOOK_DENY_SENDERS" "$2")"; shift 2 ;;

    -h|--help) usage; exit 0 ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if [[ -z "$BRIDGE_SCRIPT" ]]; then
  if ! BRIDGE_SCRIPT="$(detect_bridge_script)"; then
    echo "Cannot auto-detect wechat_event_trigger_bridge.py" >&2
    echo "Pass --bridge-script <path>" >&2
    exit 1
  fi
fi

if [[ ! -f "$BRIDGE_SCRIPT" ]]; then
  echo "Bridge script does not exist: $BRIDGE_SCRIPT" >&2
  exit 1
fi

if [[ ! -x "$RUNNER_SCRIPT" ]]; then
  echo "Runner script is missing or not executable: $RUNNER_SCRIPT" >&2
  exit 1
fi

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "Python binary not found: $PYTHON_BIN" >&2
  exit 1
fi

if [[ "$HOOK_REPLY_MODE_SET" != "1" ]]; then
  echo "Missing required option: --hook-reply-mode <whitelist|blacklist|all>" >&2
  echo "You must define reply mode first before installing this listener." >&2
  exit 1
fi

case "$HOOK_REPLY_MODE" in
  whitelist|blacklist|all) ;;
  *)
    echo "Invalid --hook-reply-mode: $HOOK_REPLY_MODE" >&2
    echo "Expected one of: whitelist, blacklist, all" >&2
    exit 1
    ;;
esac

if [[ "$HOOK_REPLY_MODE" == "whitelist" && -z "$HOOK_ALLOW_SENDERS" ]]; then
  echo "--hook-allow-senders (or repeated --hook-allow-sender) is required in whitelist mode" >&2
  exit 1
fi

if [[ "$HOOK_REPLY_MODE" == "blacklist" && -z "$HOOK_DENY_SENDERS" ]]; then
  echo "--hook-deny-senders (or repeated --hook-deny-sender) is required in blacklist mode" >&2
  exit 1
fi

LAUNCH_AGENTS_DIR="${HOME}/Library/LaunchAgents"
PLIST_PATH="${LAUNCH_AGENTS_DIR}/${LABEL}.plist"
LOG_DIR="${HOME}/.openclaw/logs"
STDOUT_LOG="${LOG_DIR}/${LABEL}.log"
STDERR_LOG="${LOG_DIR}/${LABEL}.err.log"

mkdir -p "$LAUNCH_AGENTS_DIR" "$(dirname "$ENV_FILE")" "$LOG_DIR"

tmp_env="$(mktemp)"
write_kv() {
  local key="$1"
  local value="$2"
  printf '%s=%q\n' "$key" "$value" >> "$tmp_env"
}

write_kv "PYTHON_BIN" "$PYTHON_BIN"
write_kv "WECHAT_BRIDGE_SCRIPT" "$BRIDGE_SCRIPT"
write_kv "WECHAT_API_BASE" "$API_BASE"
write_kv "WECHAT_OUTPUT_JSON" "$OUTPUT_JSON"
write_kv "WECHAT_DEBOUNCE_SEC" "$DEBOUNCE_SEC"
write_kv "WECHAT_COOLDOWN_SEC" "$COOLDOWN_SEC"
write_kv "WECHAT_RETRY_COUNT" "$RETRY_COUNT"
write_kv "WECHAT_RETRY_INTERVAL_SEC" "$RETRY_INTERVAL_SEC"
write_kv "WECHAT_TRIGGER_MIN_INTERVAL_SEC" "$TRIGGER_MIN_INTERVAL_SEC"
write_kv "WECHAT_MAX_HOURLY_FILES" "$MAX_HOURLY_FILES"
write_kv "WECHAT_OPEN_PANEL" "$OPEN_PANEL"
write_kv "WECHAT_ENABLE_OPEN_PANEL_FALLBACK" "$ENABLE_OPEN_PANEL_FALLBACK"
write_kv "WECHAT_OPEN_PANEL_FALLBACK_COOLDOWN_SEC" "$OPEN_PANEL_FALLBACK_COOLDOWN_SEC"

write_kv "OPENCLAW_HOOK_URL" "$HOOK_URL"
write_kv "OPENCLAW_HOOK_TOKEN" "$HOOK_TOKEN"
write_kv "OPENCLAW_HOOK_TOKEN_ENV" "$HOOK_TOKEN_ENV"
write_kv "OPENCLAW_HOOK_NAME" "$HOOK_NAME"
write_kv "OPENCLAW_HOOK_AGENT_ID" "$HOOK_AGENT_ID"
write_kv "OPENCLAW_HOOK_SESSION_KEY" "$HOOK_SESSION_KEY"
write_kv "OPENCLAW_HOOK_WAKE_MODE" "$HOOK_WAKE_MODE"
write_kv "OPENCLAW_HOOK_THINKING" "$HOOK_THINKING"
write_kv "OPENCLAW_HOOK_MODEL" "$HOOK_MODEL"
write_kv "OPENCLAW_HOOK_TIMEOUT_SEC" "$HOOK_TIMEOUT_SEC"
write_kv "OPENCLAW_HOOK_DELIVER" "$HOOK_DELIVER"
write_kv "OPENCLAW_HOOK_COOLDOWN_SEC" "$HOOK_COOLDOWN_SEC"
write_kv "OPENCLAW_HOOK_MAX_ITEMS" "$HOOK_MAX_ITEMS"
write_kv "OPENCLAW_HOOK_REPLY_MODE" "$HOOK_REPLY_MODE"
write_kv "OPENCLAW_HOOK_ALLOW_SENDERS" "$HOOK_ALLOW_SENDERS"
write_kv "OPENCLAW_HOOK_DENY_SENDERS" "$HOOK_DENY_SENDERS"

mv "$tmp_env" "$ENV_FILE"
chmod 600 "$ENV_FILE"

cat > "$PLIST_PATH" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${RUNNER_SCRIPT}</string>
    <string>--env-file</string>
    <string>${ENV_FILE}</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>${STDOUT_LOG}</string>
  <key>StandardErrorPath</key>
  <string>${STDERR_LOG}</string>
  <key>WorkingDirectory</key>
  <string>${HOME}</string>
</dict>
</plist>
PLIST

launchctl bootout "gui/${UID}/${LABEL}" >/dev/null 2>&1 || true
launchctl bootstrap "gui/${UID}" "$PLIST_PATH"
launchctl kickstart -k "gui/${UID}/${LABEL}" >/dev/null 2>&1 || true

echo "Installed launchd listener"
echo "  label: ${LABEL}"
echo "  plist: ${PLIST_PATH}"
echo "  env:   ${ENV_FILE}"
echo "  bridge:${BRIDGE_SCRIPT}"
echo "  out:   ${STDOUT_LOG}"
echo "  err:   ${STDERR_LOG}"

echo
echo "Tip: ensure OpenClaw hooks are enabled with a token:"
echo "  openclaw config set hooks.enabled true"
echo "  openclaw config set hooks.token '\"<your-token>\"'"
