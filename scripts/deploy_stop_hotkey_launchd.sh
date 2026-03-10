#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_HOTKEY_SCRIPT="${SCRIPT_DIR}/wechat_stop_hotkey.py"

LABEL="ai.openclaw.wechat-listener-hotkey-stop"
PYTHON_BIN="python3"
HOTKEY_SCRIPT="$DEFAULT_HOTKEY_SCRIPT"
LISTENER_CTL="${SCRIPT_DIR}/listener_ctl.sh"
LISTENER_LABEL="ai.openclaw.wechat-listener"
KEYCODE="18"
DEBOUNCE_SEC="0.8"
REQUIRE_COMMAND="1"
REQUIRE_SHIFT="1"

usage() {
  cat <<'USAGE'
Usage: deploy_stop_hotkey_launchd.sh [options]

Install and start a launchd service that watches Command+Shift+1 and stops
the WeChat listener hook service.

Options:
  --label <label>                    LaunchAgent label (default: ai.openclaw.wechat-listener-hotkey-stop)
  --python-bin <path>                Python executable (default: python3)
  --hotkey-script <path>             Path to wechat_stop_hotkey.py
  --listener-ctl <path>              Path to listener_ctl.sh
  --listener-label <label>           Listener launchd label (default: ai.openclaw.wechat-listener)
  --keycode <int>                    macOS keycode (default: 18 for "1")
  --debounce-sec <float>             Trigger debounce (default: 0.8)
  --no-command                       Do not require Command modifier
  --no-shift                         Do not require Shift modifier
  -h, --help                         Show this help
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --label) LABEL="$2"; shift 2 ;;
    --python-bin) PYTHON_BIN="$2"; shift 2 ;;
    --hotkey-script) HOTKEY_SCRIPT="$2"; shift 2 ;;
    --listener-ctl) LISTENER_CTL="$2"; shift 2 ;;
    --listener-label) LISTENER_LABEL="$2"; shift 2 ;;
    --keycode) KEYCODE="$2"; shift 2 ;;
    --debounce-sec) DEBOUNCE_SEC="$2"; shift 2 ;;
    --no-command) REQUIRE_COMMAND="0"; shift ;;
    --no-shift) REQUIRE_SHIFT="0"; shift ;;
    -h|--help) usage; exit 0 ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "Python binary not found: $PYTHON_BIN" >&2
  exit 1
fi
PYTHON_BIN="$(command -v "$PYTHON_BIN")"

if ! "$PYTHON_BIN" - <<'PY' >/dev/null 2>&1
import Quartz  # noqa: F401
PY
then
  echo "Selected python does not provide Quartz: $PYTHON_BIN" >&2
  echo "Use --python-bin with a Python that can 'import Quartz'." >&2
  exit 1
fi

if [[ ! -f "$HOTKEY_SCRIPT" ]]; then
  echo "Hotkey script not found: $HOTKEY_SCRIPT" >&2
  exit 1
fi

if [[ ! -f "$LISTENER_CTL" ]]; then
  echo "Listener control script not found: $LISTENER_CTL" >&2
  exit 1
fi

LAUNCH_AGENTS_DIR="${HOME}/Library/LaunchAgents"
PLIST_PATH="${LAUNCH_AGENTS_DIR}/${LABEL}.plist"
LOG_DIR="${HOME}/.openclaw/logs"
STDOUT_LOG="${LOG_DIR}/${LABEL}.log"
STDERR_LOG="${LOG_DIR}/${LABEL}.err.log"
mkdir -p "$LAUNCH_AGENTS_DIR" "$LOG_DIR"

declare -a ARGS=(
  "$PYTHON_BIN"
  "$HOTKEY_SCRIPT"
  --listener-ctl "$LISTENER_CTL"
  --listener-label "$LISTENER_LABEL"
  --keycode "$KEYCODE"
  --debounce-sec "$DEBOUNCE_SEC"
)

if [[ "$REQUIRE_COMMAND" == "0" ]]; then
  ARGS+=(--no-require-command)
fi
if [[ "$REQUIRE_SHIFT" == "0" ]]; then
  ARGS+=(--no-require-shift)
fi

cat > "$PLIST_PATH" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${LABEL}</string>
  <key>ProgramArguments</key>
  <array>
PLIST

for arg in "${ARGS[@]}"; do
  escaped="${arg//&/&amp;}"
  escaped="${escaped//</&lt;}"
  escaped="${escaped//>/&gt;}"
  echo "    <string>${escaped}</string>" >> "$PLIST_PATH"
done

cat >> "$PLIST_PATH" <<PLIST
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

echo "Installed hotkey stop service"
echo "  label: ${LABEL}"
echo "  plist: ${PLIST_PATH}"
echo "  shortcut: Command+Shift+1"
echo "  controls listener label: ${LISTENER_LABEL}"
echo "  out: ${STDOUT_LOG}"
echo "  err: ${STDERR_LOG}"
