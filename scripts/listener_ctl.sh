#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_SCRIPT="${SCRIPT_DIR}/deploy_listener_launchd.sh"
HOTKEY_DEPLOY_SCRIPT="${SCRIPT_DIR}/deploy_stop_hotkey_launchd.sh"

LABEL="ai.openclaw.wechat-listener"
HOTKEY_LABEL="ai.openclaw.wechat-listener-hotkey-stop"
LINES="120"

usage() {
  cat <<'USAGE'
Usage: listener_ctl.sh [--label <launchd-label>] <command> [args]

Commands:
  install [deploy-options...]   Install and start launchd service
                                Also installs Command+Shift+1 stop-hotkey by default
  start                          Start service
  stop                           Stop service
  restart                        Restart service
  status                         Show launchd status
  logs [--lines N]               Tail logs
  uninstall                      Stop and remove plist

Install extras:
  --no-hotkey-stop               Skip hotkey service install
  --hotkey-label <label>         Override hotkey LaunchAgent label
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
    INSTALL_HOTKEY="1"
    INSTALL_ARGS=()
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --no-hotkey-stop)
          INSTALL_HOTKEY="0"
          shift
          ;;
        --hotkey-label)
          HOTKEY_LABEL="$2"
          shift 2
          ;;
        *)
          INSTALL_ARGS+=("$1")
          shift
          ;;
      esac
    done

    "$DEPLOY_SCRIPT" --label "$LABEL" "${INSTALL_ARGS[@]}"

    if [[ "$INSTALL_HOTKEY" == "1" ]]; then
      if [[ ! -x "$HOTKEY_DEPLOY_SCRIPT" ]]; then
        echo "Hotkey deploy script missing or not executable: $HOTKEY_DEPLOY_SCRIPT" >&2
        exit 1
      fi
      "$HOTKEY_DEPLOY_SCRIPT" \
        --label "$HOTKEY_LABEL" \
        --listener-ctl "${SCRIPT_DIR}/listener_ctl.sh" \
        --listener-label "$LABEL"
    fi
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
    if launchctl print "$domain" >/tmp/openclaw_wechat_listener_status.txt 2>&1; then
      echo "launchd: loaded ($domain)"
      sed -n '1,80p' /tmp/openclaw_wechat_listener_status.txt
    else
      echo "launchd: not loaded ($domain)"
    fi
    rm -f /tmp/openclaw_wechat_listener_status.txt

    echo
    hotkey_domain="gui/${UID}/${HOTKEY_LABEL}"
    if launchctl print "$hotkey_domain" >/dev/null 2>&1; then
      echo "Hotkey: loaded ($hotkey_domain) -> Command+Shift+1 stops listener"
    else
      echo "Hotkey: not loaded ($hotkey_domain)"
    fi

    echo
    echo "Bridge process candidates:"
    pgrep -fl "wechat_event_trigger_bridge.py" || echo "(none)"

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
    hotkey_plist="${HOME}/Library/LaunchAgents/${HOTKEY_LABEL}.plist"
    launchctl bootout "gui/${UID}/${HOTKEY_LABEL}" >/dev/null 2>&1 || true
    rm -f "$hotkey_plist"
    echo "Uninstalled: $domain"
    echo "Removed plist: $plist_path"
    echo "Removed hotkey plist: $hotkey_plist"
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
