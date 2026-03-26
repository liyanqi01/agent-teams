# Agent Teams Computer Use 使用文档

## 1. 概览

本文档说明如何在 Agent Teams 中使用当前已经实现的 computer use 能力。

当前实现具备以下特征：

- 底层基于 OpenAI Responses API
- 通过 `OPENAI_RESPONSES_COMPUTER` provider 执行
- 由截图 + 鼠标/键盘动作驱动，而不是 DOM selector
- 通过外部 VM HTTP agent 接入 `VmComputerExecutor`

这不是一个直接控制宿主机桌面的实现。如果没有配置 executor backend，系统会回退到 `UnavailableComputerExecutor`，computer use run 不会执行真实动作。

相关设计文档：

- `docs/computer-use-design.md`

## 2. 当前已实现的能力

当前仓库已经支持：

- `OPENAI_RESPONSES_COMPUTER` 的 provider 和 runtime 配置
- `ComputerUseSession` 中的 Responses API computer-use loop
- 本地策略审批与 OpenAI `pending_safety_checks` 审批流
- VM HTTP executor backend 选择和装配
- screenshot 持久化到 session artifacts
- 通过 session artifact API 预览 screenshot
- `computer_sessions` 和 `computer_turns` 审计数据表

核心代码路径：

- `src/agent_teams/providers/openai_responses_computer.py`
- `src/agent_teams/agents/execution/computer_use_session.py`
- `src/agent_teams/computer/vm_executor.py`
- `src/agent_teams/computer/artifact_store.py`
- `src/agent_teams/computer/session_repo.py`

## 3. 运行时架构

运行时主流程如下：

1. 某个 role 使用 provider 为 `openai_responses_computer` 的 model profile。
2. provider 启动 `ComputerUseSession`。
3. `ComputerUseSession` 启动一个 VM executor session。
4. executor 返回首帧 screenshot 和桌面上下文。
5. 后端调用 OpenAI `POST /responses`，并传入 `computer_use_preview`。
6. 模型返回 `computer_call` 动作。
7. executor 执行动作并采集新的 screenshot。
8. 后端把 `computer_call_output` 回传给 OpenAI。
9. 循环继续，直到模型返回最终文本。
10. screenshot 和每一步审计数据会被持久化。

## 4. Model Profile 配置

需要创建或更新一个 model profile，并将其 provider 设置为 `openai_responses_computer`。

示例配置：

```json
{
  "provider": "openai_responses_computer",
  "model": "computer-use-preview",
  "base_url": "https://api.openai.com/v1",
  "api_key": "<OPENAI_API_KEY>",
  "computer_use": {
    "display_width": 1280,
    "display_height": 800,
    "environment": "desktop",
    "reasoning_summary": "concise",
    "truncation": "auto"
  }
}
```

说明：

- 仓库配置层接受 `computer` 或 `desktop`，但运行时目前会把它映射成 OpenAI tool payload 中的 `windows`。
- `base_url` 正常应为 `https://api.openai.com/v1`。
- `model` 需要是你的 OpenAI 账户可用的 computer-use 模型。

相关文件：

- `src/agent_teams/providers/model_config.py`
- `src/agent_teams/interfaces/server/routers/system.py`
- `src/agent_teams/sessions/runs/runtime_config.py`

## 5. Executor Backend 配置

当前真实可执行的 backend 是 `vm_http`。

通过环境变量配置：

- `AGENT_TEAMS_COMPUTER_EXECUTOR_BACKEND=vm_http`
- `AGENT_TEAMS_COMPUTER_VM_BASE_URL=http://<vm-agent-host>:<port>`
- `AGENT_TEAMS_COMPUTER_VM_API_KEY=<optional-api-key>`
- `AGENT_TEAMS_COMPUTER_VM_SSL_VERIFY=true|false`
- `AGENT_TEAMS_COMPUTER_VM_TIMEOUT_SECONDS=30`

如果没有设置 `AGENT_TEAMS_COMPUTER_EXECUTOR_BACKEND=vm_http`，backend 会保持为 `unavailable`。

相关文件：

- `src/agent_teams/computer/executor_config.py`

## 6. VM Agent 协议

`VmComputerExecutor` 期望外部 VM agent 提供这些接口：

- `POST /sessions`
- `POST /sessions/{session_id}/actions`
- `GET /sessions/{session_id}/screenshot`
- `GET /sessions/{session_id}/context`
- `DELETE /sessions/{session_id}`

预期返回结构：

- `POST /sessions` 返回 `{ "session_id": "..." }`
- `POST /sessions/{session_id}/actions` 返回 `ComputerActionResult`
- `GET /sessions/{session_id}/screenshot` 返回 `ComputerScreenshot`
- `GET /sessions/{session_id}/context` 返回 `ComputerContext`

对应的 Pydantic 模型定义在：

- `src/agent_teams/computer/action_models.py`

## 7. 如何运行

1. 配置一个 `openai_responses_computer` model profile。
2. 配置 VM executor 环境变量。
3. 启动 Agent Teams server。
4. 使用一个指向该 computer-use profile 的 role。
5. 通过 `/api/runs` 或 Web UI 正常创建 run。
6. 当 role 进入 computer use 后，run stream 会继续发普通 tool 事件，只是 `tool_name = computer_use`。
7. 如有高风险动作或 safety check，按要求审批。

复用的现有 run API：

- `POST /api/runs`
- `GET /api/runs/{run_id}/events`
- `GET /api/runs/{run_id}/tool-approvals`
- `POST /api/runs/{run_id}/tool-approvals/{tool_call_id}/resolve`

参见：

- `docs/api-design.md`

## 8. 审批流

computer-use 动作复用现有 tool approval 流。

审批会由以下两类条件触发：

- 模型返回 `pending_safety_checks`
- 本地策略要求该动作必须审批

默认会被视为需要审批的动作包括：

- `click`
- `type`
- `keypress`
- `drag`

像 `wait` 这样的低风险动作，是否自动放行取决于当前策略。

相关文件：

- `src/agent_teams/tools/runtime/policy.py`

## 9. Screenshot 与预览

每张 computer-use screenshot 都会持久化到 session artifact 根目录下。

`computer_use` 的 `TOOL_RESULT` 中会包含：

- `artifact_path`
- `artifact_url`
- `mime_type`
- `width`
- `height`

当前预览 API：

- `GET /api/sessions/{session_id}/artifacts/{artifact_path}`

前端已经复用这个 URL，在 tool result block 中直接显示 inline screenshot preview。

相关文件：

- `src/agent_teams/computer/artifact_store.py`
- `src/agent_teams/interfaces/server/routers/sessions.py`
- `frontend/dist/js/components/messageRenderer/helpers/toolBlocks.js`

## 10. 审计数据

computer-use 执行过程目前会持久化两张表：

- `computer_sessions`
- `computer_turns`

这些表记录：

- executor session 生命周期
- 最新 URL 和窗口标题
- 动作类型和序列化后的 action payload
- action result payload
- screenshot artifact 引用
- 每一步的状态

相关文件：

- `src/agent_teams/computer/session_repo.py`
- `docs/database-schema.md`

## 11. 排障

### 11.1 Computer Use 没有执行真实动作

优先检查：

- model profile 的 provider 是否为 `openai_responses_computer`
- 是否设置了 `AGENT_TEAMS_COMPUTER_EXECUTOR_BACKEND=vm_http`
- `AGENT_TEAMS_COMPUTER_VM_BASE_URL` 是否可达
- VM agent 是否实现了所有必需接口

如果 backend 配置缺失，container 会使用 `UnavailableComputerExecutor`。

### 11.2 Screenshot 预览无法加载

检查：

- `computer_use` tool result payload 中是否有 `artifact_url`
- artifact 文件是否真实存在于 session artifact 目录下
- `GET /api/sessions/{session_id}/artifacts/{artifact_path}` 是否返回 `200`

### 11.3 Run 卡在等待审批

检查：

- `GET /api/runs/{run_id}/tool-approvals`
- 动作是否被 `pending_safety_checks` 阻塞
- 本地策略是否要求对该动作审批

通过下面的接口完成审批：

- `POST /api/runs/{run_id}/tool-approvals/{tool_call_id}/resolve`

### 11.4 OpenAI 请求失败

检查：

- `base_url`
- `api_key`
- 模型是否对当前账户可用
- 出站代理和 TLS 设置是否正确

相关文件：

- `src/agent_teams/agents/execution/computer_use_session.py`

## 12. 当前限制

当前实现仍有这些限制：

- 不直接控制宿主机桌面
- 没有专门的 screenshot timeline 页面
- 没有面向 `computer_sessions` / `computer_turns` 的专用 replay API
- 这条路径不支持 browser-DOM automation 模式
- 执行依赖外部 VM HTTP agent

## 13. 建议的下一步

如果要继续增强这套实现，优先级最高的方向是：

1. 基于 `computer_sessions` 和 `computer_turns` 增加 replay/read API。
2. 增强 screenshot timeline UI。
3. 增加 `vm_http` 之外的 executor backend。
4. 对 submit、upload、download、login 等动作增加更细粒度的风险策略。
