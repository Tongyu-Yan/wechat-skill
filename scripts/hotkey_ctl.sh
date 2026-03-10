#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_SCRIPT="${SCRIPT_DIR}/deploy_stop_hotkey_launchd.sh"

LABEL="ai.openclaw.wechat-listener-hotkey-stop"
LINES="120"

usage() {
  cat <<'USAGE'
Usage: hotkey_ctl.sh [--label <launchd-label>] <command> [args]

Commands:
  install [deploy-options...]   Install and start hotkey service
  start                         Start hotkey service
  stop                          Stop hotkey service
  restart                       Restart hotkey service
  status                        Show launchd status
  logs [--lines N]              Tail logs
  uninstall                     Stop and remove plist
USAGE
}

if [[ "${1:-}" == "--label" ]]; then
  LABEL="$2"
  shift 2
fi

CMD="${1:-help}"
if [[ $# -gt 0 ]]; then
  shift
fi

plist_path="${HOME}/Library/LaunchAgents/${LABEL}.plist"
stdout_log="${HOME}/.openclaw/logs/${LABEL}.log"
stderr_log="${HOME}/.openclaw/logs/${LABEL}.err.log"
domain="gui/${UID}/${LABEL}"

case "$CMD" in
  install)
    "$DEPLOY_SCRIPT" --label "$LABEL" "$@"
    ;;

  start)
    if [[ ! -f "$plist_path" ]]; then
      echo "Plist not found: $plist_path" >&2
      exit 1
    fi
    launchctl bootstrap "gui/${UID}" "$plist_path" >/dev/null 2>&1 || true
    launchctl kickstart -k "$domain"
    echo "Started: $domain"
    ;;

  stop)
    launchctl bootout "$domain" >/dev/null 2>&1 || true
    echo "Stopped: $domain"
    ;;

  restart)
    launchctl bootout "$domain" >/dev/null 2>&1 || true
    if [[ ! -f "$plist_path" ]]; then
      echo "Plist not found: $plist_path" >&2
      exit 1
    fi
    launchctl bootstrap "gui/${UID}" "$plist_path"
    launchctl kickstart -k "$domain" >/dev/null 2>&1 || true
    echo "Restarted: $domain"
    ;;

  status)
    if launchctl print "$domain" >/tmp/openclaw_wechat_hotkey_status.txt 2>&1; then
      echo "launchd: loaded ($domain)"
      sed -n '1,80p' /tmp/openclaw_wechat_hotkey_status.txt
    else
      echo "launchd: not loaded ($domain)"
    fi
    rm -f /tmp/openclaw_wechat_hotkey_status.txt

    echo
    echo "Hotkey watcher process candidates:"
    pgrep -fl "wechat_stop_hotkey.py" || echo "(none)"

    echo
    echo "Logs:"
    echo "  $stdout_log"
    echo "  $stderr_log"
    ;;

  logs)
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --lines)
          LINES="$2"
          shift 2
          ;;
        *)
          echo "Unknown logs option: $1" >&2
          exit 1
          ;;
      esac
    done
    touch "$stdout_log" "$stderr_log"
    tail -n "$LINES" -f "$stdout_log" "$stderr_log"
    ;;

  uninstall)
    launchctl bootout "$domain" >/dev/null 2>&1 || true
    rm -f "$plist_path"
    echo "Uninstalled: $domain"
    echo "Removed plist: $plist_path"
    ;;

  -h|--help|help|"")
    usage
    ;;

  *)
    echo "Unknown command: $CMD" >&2
    usage >&2
    exit 1
    ;;
esac

