#!/usr/bin/env bash
set -euo pipefail

HOOK_ID="wechat-listener-autostart"
LISTENER_LABEL="ai.openclaw.wechat-listener"
LISTENER_CTL="${HOME}/.openclaw/skills/wechat-event-autopilot/scripts/listener_ctl.sh"
WORKSPACE_DIR=""

usage() {
  cat <<'USAGE'
Usage: install_gateway_autostart_hook.sh [options]

Create and enable a gateway:startup hook so OpenClaw auto-starts the WeChat listener
when gateway starts.

Options:
  --workspace <path>            Override workspace path (default: config agents.defaults.workspace)
  --listener-ctl <path>         Path to listener_ctl.sh
  --listener-label <label>      Listener launchd label (default: ai.openclaw.wechat-listener)
  -h, --help                    Show this help
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --workspace) WORKSPACE_DIR="$2"; shift 2 ;;
    --listener-ctl) LISTENER_CTL="$2"; shift 2 ;;
    --listener-label) LISTENER_LABEL="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if [[ -z "$WORKSPACE_DIR" ]]; then
  WORKSPACE_DIR="$(openclaw config get agents.defaults.workspace 2>/dev/null || true)"
fi

if [[ -z "$WORKSPACE_DIR" ]]; then
  echo "Workspace is empty. Set agents.defaults.workspace first." >&2
  exit 1
fi

if [[ ! -d "$WORKSPACE_DIR" ]]; then
  echo "Workspace path not found: $WORKSPACE_DIR" >&2
  exit 1
fi

HOOK_DIR="${WORKSPACE_DIR}/hooks/${HOOK_ID}"
mkdir -p "$HOOK_DIR"

cat > "${HOOK_DIR}/HOOK.md" <<EOF
---
name: ${HOOK_ID}
description: "Auto-start WeChat listener service on gateway startup"
metadata:
  {
    "openclaw":
      {
        "emoji": "🔁",
        "events": ["gateway:startup"],
        "requires": { "bins": ["bash", "launchctl"] },
      },
  }
---

# WeChat Listener Autostart Hook

On each gateway startup, this hook runs:

\`bash ${LISTENER_CTL} --label ${LISTENER_LABEL} start\`

This keeps WeChat listener running without manual chat commands.
EOF

cat > "${HOOK_DIR}/handler.ts" <<EOF
import { execFile } from "node:child_process";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);

const LISTENER_CTL = process.env.WECHAT_LISTENER_CTL || "${LISTENER_CTL}";
const LISTENER_LABEL = process.env.WECHAT_LISTENER_LABEL || "${LISTENER_LABEL}";

const handler = async (event: any) => {
  if (!event || event.type !== "gateway" || event.action !== "startup") {
    return;
  }
  try {
    await execFileAsync("bash", [LISTENER_CTL, "--label", LISTENER_LABEL, "start"], {
      timeout: 15000,
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    console.error("[wechat-listener-autostart] start failed:", message);
  }
};

export default handler;
EOF

openclaw config set hooks.internal.enabled true >/dev/null
openclaw hooks enable "$HOOK_ID" >/dev/null

echo "Installed autostart hook: $HOOK_ID"
echo "  workspace: $WORKSPACE_DIR"
echo "  hook dir:  $HOOK_DIR"
echo "  listener:  $LISTENER_LABEL"
echo
echo "Restart gateway to apply startup hook immediately."

