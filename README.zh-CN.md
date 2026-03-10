# WeChat Event Autopilot - 朋友安装指南

本包提供一个 OpenClaw skill，用于在 macOS 上实现微信事件驱动监控。

核心流程：

1. 监听微信通知事件。
2. 扫描未读消息并按小时写入 JSON 快照。
3. 触发 OpenClaw `/hooks/agent`。
4. 由 OpenClaw 决定是否自动回复（可调用 `turix-mac`）。

## 给普通用户的仓库介绍

这个仓库不是独立运行的产品，必须先安装并可用 [TuriX-CUA](https://github.com/TurixAI/TuriX-CUA) 才能正常使用。

它的工作方式可以理解为：

1. 读取 macOS 通知中心里的微信最新消息事件。
2. 通过 hook 把事件发送给 OpenClaw（龙虾）。
3. 由 OpenClaw 决策后，再通过 TuriX 操作电脑完成微信回复等动作。

当前支持三种回复范围模式：

- `whitelist`（白名单）
- `blacklist`（黑名单）
- `all`（全量）

请根据你的实际需求，提前和 OpenClaw（龙虾）说明要使用哪一种模式。

另外请知悉：由于微信当前风控较强，本方案目前只能通过 macOS 通知中心拿取消息；消息可能出现延迟、被折叠或被遮挡，属于预期现象。

## 仓库介绍

这个仓库是一个可直接开源的 OpenClaw 微信事件驱动自动化 skill（macOS）。

主要组成：

- `scripts/wechat_event_trigger_bridge.py`：监听 macOS 微信通知事件，扫描未读消息，并按小时写入 JSON 快照。
- `scripts/listener_ctl.sh`：提供 launchd 服务的一键安装/启动/停止/重启/状态/日志管理。
- `scripts/decide_wechat_reply.py`：带保护策略的自动回复决策器（支持仅决策 dry-run，也可选调用 `turix-mac` 执行）。
- `scripts/install_gateway_autostart_hook.sh`：可选的 gateway 启动自拉起能力，减少手工操作。
- `scripts/wechat_stop_hotkey.py`：可选紧急停止热键（`Command+Shift+1`）。

开源说明：

- 文档中的凭证均为占位符（例如 `REPLACE_WITH_A_LONG_RANDOM_TOKEN`）。
- 示例 URL 默认使用本机回环地址（`127.0.0.1`）。
- 运行期消息快照和本地环境文件由每位使用者在自己的机器上生成。

## 回复模式说明（重要）

安装前必须先选择一种自动回复过滤模式：

- `whitelist`：仅回复白名单中的发送者。
- `blacklist`：回复除黑名单外的所有发送者。
- `all`：回复所有发送者。

模式约束：

- `whitelist` 必须提供 `--hook-allow-senders`（或重复使用 `--hook-allow-sender`）。
- `blacklist` 必须提供 `--hook-deny-senders`（或重复使用 `--hook-deny-sender`）。
- `all` 会忽略 allow/deny 列表。

## 0) 环境要求

- macOS
- 已安装并可用 [TuriX-CUA](https://github.com/TurixAI/TuriX-CUA)
- OpenClaw CLI + gateway
- Python 3
- 可用的微信后端 API：`http://127.0.0.1:8787`（或你自己的端点）

## 1) 将 Skill 安装到 OpenClaw 工作区

先检查当前激活的工作区：

```bash
openclaw config get agents.defaults.workspace
```

将 skill 复制到工作区：

```bash
WORKSPACE="$(openclaw config get agents.defaults.workspace)"
SKILL_DIR="${WORKSPACE}/skills/wechat-event-autopilot"
mkdir -p "${SKILL_DIR}"
cp -R ./scripts ./references ./SKILL.md ./SELF_MANAGED_SETUP.md ./README.md ./README.zh-CN.md "${SKILL_DIR}/"
```

## 2) 启用 Hooks

```bash
openclaw config set hooks.enabled true
openclaw config set hooks.token '"REPLACE_WITH_A_LONG_RANDOM_TOKEN"'
openclaw config set hooks.path '"/hooks"'
openclaw config set hooks.allowRequestSessionKey true
openclaw config set hooks.allowedSessionKeyPrefixes '["hook:","agent:"]'
```

## 3) 安装监听器（先选择回复模式）

`listener_ctl.sh install` 需要指定一种回复模式：

- `whitelist`：仅回复白名单发件人
- `blacklist`：回复除黑名单外的所有发件人
- `all`：回复所有人

请在已安装 skill 的目录下运行：

```bash
WORKSPACE="$(openclaw config get agents.defaults.workspace)"
SKILL_DIR="${WORKSPACE}/skills/wechat-event-autopilot"
```

白名单模式示例：

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

黑名单模式示例：

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

全量模式示例：

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

## 4) 日常运维

```bash
bash "${SKILL_DIR}/scripts/listener_ctl.sh" status
bash "${SKILL_DIR}/scripts/listener_ctl.sh" restart
bash "${SKILL_DIR}/scripts/listener_ctl.sh" logs --lines 200
bash "${SKILL_DIR}/scripts/listener_ctl.sh" stop
```

快捷键停止：

- `Command+Shift+1` 可停止监听服务。

## 5) 端到端验证

检查 gateway 和 session：

```bash
openclaw gateway health
openclaw gateway call sessions.list --json --params '{}'
```

发送 hook 测试：

```bash
python3 "${SKILL_DIR}/scripts/notify_openclaw_hook.py" \
  --hook-url http://127.0.0.1:18789/hooks/agent \
  --token "REPLACE_WITH_A_LONG_RANDOM_TOKEN" \
  --agent-id main \
  --session-key agent:main:main \
  --message "Hook test from wechat-event-autopilot"
```

预期结果：

- listener status 显示 `state = running`
- 新事件日志出现 `trigger received` 和 `scan done`
- hook 消息出现在会话 `agent:main:main`

## 6) 可选：随 Gateway 启动自动拉起

```bash
bash "${SKILL_DIR}/scripts/install_gateway_autostart_hook.sh" \
  --listener-ctl "${SKILL_DIR}/scripts/listener_ctl.sh" \
  --listener-label ai.openclaw.wechat-listener
```

然后重启一次 gateway：

```bash
openclaw gateway restart --force
```

## 注意事项

- 由于微信当前风控较强，本方案目前只能通过 macOS 通知中心拿取消息；消息可能出现延迟、被折叠或被遮挡，属于预期现象。
- 请从可信的本地路径运行 launchd 脚本（不要用 Desktop 临时副本），否则可能被 macOS 隐私控制拦截。
- 在 `whitelist` 模式下，发送者名称必须与微信通知中抓取到的名称完全一致。
- 隐藏/堆叠通知可能导致延迟；`--enable-open-panel-fallback` 可提高可靠性。
