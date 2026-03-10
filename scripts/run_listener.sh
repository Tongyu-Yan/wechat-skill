#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${HOME}/.openclaw/state/wechat-listener.env"

usage() {
  cat <<'USAGE'
Usage: run_listener.sh [--env-file <path>]

Launch the WeChat event bridge with values from an env file.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env-file)
      ENV_FILE="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if [[ -f "$ENV_FILE" ]]; then
  # shellcheck disable=SC1090
  source "$ENV_FILE"
fi

PYTHON_BIN="${PYTHON_BIN:-python3}"
WECHAT_BRIDGE_SCRIPT="${WECHAT_BRIDGE_SCRIPT:-}"
WECHAT_API_BASE="${WECHAT_API_BASE:-http://127.0.0.1:8787}"
WECHAT_OUTPUT_JSON="${WECHAT_OUTPUT_JSON:-${HOME}/.openclaw/state/wechat_messages.json}"
WECHAT_DEBOUNCE_SEC="${WECHAT_DEBOUNCE_SEC:-0.25}"
WECHAT_COOLDOWN_SEC="${WECHAT_COOLDOWN_SEC:-0.8}"
WECHAT_RETRY_COUNT="${WECHAT_RETRY_COUNT:-3}"
WECHAT_RETRY_INTERVAL_SEC="${WECHAT_RETRY_INTERVAL_SEC:-0.35}"
WECHAT_TRIGGER_MIN_INTERVAL_SEC="${WECHAT_TRIGGER_MIN_INTERVAL_SEC:-0.2}"
WECHAT_MAX_HOURLY_FILES="${WECHAT_MAX_HOURLY_FILES:-12}"
WECHAT_OPEN_PANEL="${WECHAT_OPEN_PANEL:-0}"
WECHAT_ENABLE_OPEN_PANEL_FALLBACK="${WECHAT_ENABLE_OPEN_PANEL_FALLBACK:-0}"
WECHAT_OPEN_PANEL_FALLBACK_COOLDOWN_SEC="${WECHAT_OPEN_PANEL_FALLBACK_COOLDOWN_SEC:-180}"

OPENCLAW_HOOK_URL="${OPENCLAW_HOOK_URL:-}"
OPENCLAW_HOOK_TOKEN="${OPENCLAW_HOOK_TOKEN:-}"
OPENCLAW_HOOK_TOKEN_ENV="${OPENCLAW_HOOK_TOKEN_ENV:-OPENCLAW_HOOKS_TOKEN}"
OPENCLAW_HOOK_NAME="${OPENCLAW_HOOK_NAME:-WeChat}"
OPENCLAW_HOOK_AGENT_ID="${OPENCLAW_HOOK_AGENT_ID:-}"
OPENCLAW_HOOK_SESSION_KEY="${OPENCLAW_HOOK_SESSION_KEY:-hook:wechat-inbox}"
OPENCLAW_HOOK_WAKE_MODE="${OPENCLAW_HOOK_WAKE_MODE:-now}"
OPENCLAW_HOOK_THINKING="${OPENCLAW_HOOK_THINKING:-low}"
OPENCLAW_HOOK_MODEL="${OPENCLAW_HOOK_MODEL:-}"
OPENCLAW_HOOK_TIMEOUT_SEC="${OPENCLAW_HOOK_TIMEOUT_SEC:-120}"
OPENCLAW_HOOK_DELIVER="${OPENCLAW_HOOK_DELIVER:-0}"
OPENCLAW_HOOK_COOLDOWN_SEC="${OPENCLAW_HOOK_COOLDOWN_SEC:-1.5}"
OPENCLAW_HOOK_MAX_ITEMS="${OPENCLAW_HOOK_MAX_ITEMS:-5}"
OPENCLAW_HOOK_REPLY_MODE="${OPENCLAW_HOOK_REPLY_MODE:-whitelist}"
OPENCLAW_HOOK_ALLOW_SENDERS="${OPENCLAW_HOOK_ALLOW_SENDERS:-}"
OPENCLAW_HOOK_DENY_SENDERS="${OPENCLAW_HOOK_DENY_SENDERS:-}"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "Python binary not found: $PYTHON_BIN" >&2
  exit 1
fi

if [[ -z "$WECHAT_BRIDGE_SCRIPT" ]]; then
  echo "WECHAT_BRIDGE_SCRIPT is empty. Set it in env file or pass via deploy script." >&2
  exit 1
fi

if [[ ! -f "$WECHAT_BRIDGE_SCRIPT" ]]; then
  echo "Bridge script not found: $WECHAT_BRIDGE_SCRIPT" >&2
  exit 1
fi

args=(
  "$PYTHON_BIN"
  "$WECHAT_BRIDGE_SCRIPT"
  --api-base "$WECHAT_API_BASE"
  --output-json "$WECHAT_OUTPUT_JSON"
  --debounce-sec "$WECHAT_DEBOUNCE_SEC"
  --cooldown-sec "$WECHAT_COOLDOWN_SEC"
  --retry-count "$WECHAT_RETRY_COUNT"
  --retry-interval-sec "$WECHAT_RETRY_INTERVAL_SEC"
  --trigger-min-interval-sec "$WECHAT_TRIGGER_MIN_INTERVAL_SEC"
  --open-panel-fallback-cooldown-sec "$WECHAT_OPEN_PANEL_FALLBACK_COOLDOWN_SEC"
  --max-hourly-files "$WECHAT_MAX_HOURLY_FILES"
)

if [[ "$WECHAT_OPEN_PANEL" == "1" ]]; then
  args+=(--open-panel)
else
  args+=(--no-open-panel)
fi

if [[ "$WECHAT_ENABLE_OPEN_PANEL_FALLBACK" == "1" ]]; then
  args+=(--enable-open-panel-fallback)
else
  args+=(--disable-open-panel-fallback)
fi

if [[ -n "$OPENCLAW_HOOK_URL" ]]; then
  case "$OPENCLAW_HOOK_REPLY_MODE" in
    whitelist|blacklist|all) ;;
    *)
      echo "Invalid OPENCLAW_HOOK_REPLY_MODE: $OPENCLAW_HOOK_REPLY_MODE" >&2
      echo "Expected one of: whitelist, blacklist, all" >&2
      exit 1
      ;;
  esac
  if [[ "$OPENCLAW_HOOK_REPLY_MODE" == "whitelist" && -z "$OPENCLAW_HOOK_ALLOW_SENDERS" ]]; then
    echo "OPENCLAW_HOOK_ALLOW_SENDERS is required when OPENCLAW_HOOK_REPLY_MODE=whitelist" >&2
    exit 1
  fi

  args+=(
    --notify-hook-url "$OPENCLAW_HOOK_URL"
    --notify-hook-token-env "$OPENCLAW_HOOK_TOKEN_ENV"
    --notify-hook-name "$OPENCLAW_HOOK_NAME"
    --notify-hook-session-key "$OPENCLAW_HOOK_SESSION_KEY"
    --notify-hook-wake-mode "$OPENCLAW_HOOK_WAKE_MODE"
    --notify-hook-thinking "$OPENCLAW_HOOK_THINKING"
    --notify-hook-timeout-sec "$OPENCLAW_HOOK_TIMEOUT_SEC"
    --notify-hook-cooldown-sec "$OPENCLAW_HOOK_COOLDOWN_SEC"
    --notify-hook-max-items "$OPENCLAW_HOOK_MAX_ITEMS"
    --notify-hook-reply-mode "$OPENCLAW_HOOK_REPLY_MODE"
  )
  if [[ -n "$OPENCLAW_HOOK_ALLOW_SENDERS" ]]; then
    args+=(--notify-hook-allow-senders "$OPENCLAW_HOOK_ALLOW_SENDERS")
  fi
  if [[ -n "$OPENCLAW_HOOK_DENY_SENDERS" ]]; then
    args+=(--notify-hook-deny-senders "$OPENCLAW_HOOK_DENY_SENDERS")
  fi

  if [[ -n "$OPENCLAW_HOOK_TOKEN" ]]; then
    args+=(--notify-hook-token "$OPENCLAW_HOOK_TOKEN")
  fi
  if [[ -n "$OPENCLAW_HOOK_AGENT_ID" ]]; then
    args+=(--notify-hook-agent-id "$OPENCLAW_HOOK_AGENT_ID")
  fi
  if [[ -n "$OPENCLAW_HOOK_MODEL" ]]; then
    args+=(--notify-hook-model "$OPENCLAW_HOOK_MODEL")
  fi
  if [[ "$OPENCLAW_HOOK_DELIVER" == "1" ]]; then
    args+=(--notify-hook-deliver)
  fi
fi

exec "${args[@]}"
