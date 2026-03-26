# Agent Teams Computer Use Design

## 1. 目标

本设计文档定义 Agent Teams 中“真正的 OpenAI computer use”落地方案。

这里的目标不是实现 browser use，也不是给模型暴露一组 DOM 级浏览器工具，而是实现一条标准的 computer use 执行链：

1. 模型通过 OpenAI `Responses API` 返回 `computer_call`
2. 后端执行鼠标/键盘级动作
3. 后端采集截图和上下文
4. 后端通过 `computer_call_output` 回传执行结果
5. 模型继续决策，直到生成最终文本输出

当前第一阶段只支持“桌面/计算机”语义，不依赖 DOM selector，不暴露 `page.click()`、`page.locator()` 这类 browser use 接口。

## 2. Scope And Non-goals

Scope:

- Add `openai_responses_computer` at the provider layer
- Integrate directly with OpenAI `Responses API`
- Introduce a dedicated `ComputerUseSession`
- Introduce a `ComputerExecutor` abstraction with VM or desktop backends
- Reuse the existing run event stream
- Reuse the existing approval ticket / approval manager / runs approval API
- Support `computer_use` configuration in system settings

Non-goals:

- Do not implement DOM-driven browser automation interfaces
- Do not mix computer use into the existing pydantic-ai tool-call chain
- Do not directly control the host desktop in this phase
- Do not add a dedicated computer-only frontend surface beyond the existing run/session UI reuse path in this phase

## 3. 设计原则

- computer use 与 browser use 严格区分：上层语义必须是截图 + 坐标/键盘动作，而不是 DOM 操作
- 不依赖当前 `pydantic-ai` 的 Responses computer tool 支持，因为本地依赖版本尚未支持该类型
- 复用已有 run/approval/runtime 基础设施，避免再造一套审批和暂停机制
- provider 对上仍然维持 `LLMProvider.generate() -> str` 契约，尽量减少 orchestration 层改动
- environment/executor 抽象必须窄接口、强类型、可替换

## 4. 架构总览

### 4.1 分层

1. Provider 层
   - `OpenAIResponsesComputerProvider`
   - 负责把 role 绑定到 computer-use 专用 session

2. Session 层
   - `ComputerUseSession`
   - 负责整个 `Responses API` 闭环

3. Executor 层
   - `ComputerExecutor`
   - 负责真正执行动作、截图、读取上下文

4. Runtime 集成层
   - `RunEventHub`
   - `RunRuntimeRepository`
   - `ApprovalTicketRepository`
   - `ToolApprovalManager`
   - `ToolApprovalPolicy`

### 4.2 主流程

1. `TaskExecutionService`/provider factory 根据 role 的 model profile 选择 `OPENAI_RESPONSES_COMPUTER`
2. `OpenAIResponsesComputerProvider.generate()` 调用 `ComputerUseSession.run()`
3. `ComputerUseSession` 启动 `ComputerExecutor` session
4. 采集首帧截图和上下文
5. 向 `POST /responses` 发送首个请求
6. 解析 `computer_call`
7. 如无 safety checks：直接执行动作
8. 如有 safety checks：进入现有 tool approval 流
9. 执行动作后采集新截图和上下文
10. 发送 `computer_call_output`
11. 循环直至模型输出最终文本
12. 发布 `TEXT_DELTA` 并结束 executor session

## 5. 核心模块设计

### 5.1 Provider 与配置

相关文件：

- `src/agent_teams/providers/model_config.py`
- `src/agent_teams/providers/openai_responses_computer.py`
- `src/agent_teams/providers/provider_factory.py`
- `src/agent_teams/providers/provider_registry.py`
- `src/agent_teams/providers/model_config_manager.py`
- `src/agent_teams/sessions/runs/runtime_config.py`
- `src/agent_teams/interfaces/server/routers/system.py`

设计：

- 新 provider type：`OPENAI_RESPONSES_COMPUTER`
- 新配置块：`computer_use`
- `computer_use` 当前字段：
  - `display_width`
  - `display_height`
  - `environment`
  - `reasoning_summary`
  - `truncation`
- provider factory 为 computer use provider 注入：
  - `ComputerExecutor`
  - `MessageRepository`
  - `RunEventHub`
  - `RunControlManager`
  - `ApprovalTicketRepository`
  - `ToolApprovalManager`
  - `ToolApprovalPolicy`
  - `RunRuntimeRepository`

说明：

- 当前配置层允许旧的 `computer` / `desktop` 环境值存在，但在真正发给 OpenAI tool schema 时会映射到 `windows`
- 这是为了兼容当前仓库里早期讨论阶段留下的配置语义，同时满足本地 OpenAI SDK 的 tool 参数约束

### 5.2 ComputerUseSession

相关文件：

- `src/agent_teams/agents/execution/computer_use_session.py`

职责：

- 解析 prompt
- 启动 executor session
- 构建 initial response payload
- 解析 `computer_call`
- 执行动作
- 构建 follow-up `computer_call_output`
- 处理 safety check 审批
- 发布 run events
- 结束 executor session

Key points:

- When `request.user_prompt` is empty, the session falls back to the latest `UserPromptPart` from `MessageRepository.get_history_for_conversation_task()`.
- `computer_call_output` sends the latest screenshot as a data URL and includes `current_url` when available.
- Screenshots are persisted under the session artifact directory and `TOOL_RESULT` includes both `artifact_path` and `artifact_url`.
- The execution loop now also persists audit data into `computer_sessions` and `computer_turns`.
- Unsupported payloads fail fast with a runtime error instead of silently degrading.

### 5.3 Executor Abstraction

Relevant files:

- `src/agent_teams/computer/action_models.py`
- `src/agent_teams/computer/executor_contracts.py`
- `src/agent_teams/computer/unavailable_executor.py`
- `src/agent_teams/computer/vm_executor.py`

Current interface:

- `start_session(run_id, instance_id)`
- `execute_action(session_id, action)`
- `capture_screenshot(session_id)`
- `get_context(session_id)`
- `stop_session(session_id)`

Current status:

- `UnavailableComputerExecutor` remains the safe default fallback.
- `VmComputerExecutor` is implemented via an HTTP agent and wired through container config.
- Direct host-desktop control is still out of scope; real execution depends on an external VM agent.

### 5.4 审批集成

复用已有模块：

- `src/agent_teams/tools/runtime/approval_state.py`
- `src/agent_teams/tools/runtime/approval_ticket_repo.py`
- `src/agent_teams/interfaces/server/routers/runs.py`
- `src/agent_teams/sessions/runs/run_manager.py`

设计：

- `pending_safety_checks` 不再只是发一个 `AWAITING_MANUAL_ACTION` 事件后直接失败
- 现在改为：
  1. 写入 approval ticket
  2. 在 `ToolApprovalManager` 中打开 approval entry
  3. 将 run runtime 切到 `PAUSED + AWAITING_TOOL_APPROVAL`
  4. 发布 `TOOL_APPROVAL_REQUESTED`
  5. 阻塞等待现有 `/runs/{run_id}/tool-approvals/{tool_call_id}/resolve`
  6. 根据 `approve/deny/timeout` 更新 runtime 和 ticket
  7. 批准后继续动作执行

结果：

- computer use 已经和普通高风险 tool call 共享同一套 approval API
- 前端无需新增一条完全不同的 resolve API 才能先跑通

## 6. 事件与运行时行为

当前 computer use 复用已有事件类型：

- `MODEL_STEP_STARTED`
- `MODEL_STEP_FINISHED`
- `TOOL_CALL`
- `TOOL_RESULT`
- `TEXT_DELTA`
- `TOOL_APPROVAL_REQUESTED`
- `TOOL_APPROVAL_RESOLVED`

设计原因：

- 先让现有 run stream、run state projection、approval UI 直接复用
- 避免因为增加一组新的 computer 专属事件类型而扩大本轮改造范围

后续可以再考虑补充 computer 专属事件，例如：

- `computer_screenshot_captured`
- `computer_session_started`
- `computer_session_stopped`

## 7. 当前实现状态

### 7.1 已完成

#### PR0: provider skeleton

状态：已完成

提交：

- `1309e53 Add computer use provider skeleton`

内容：

- 新增 `OPENAI_RESPONSES_COMPUTER` provider type
- 新增 `computer` 包基础类型和 executor protocol
- provider registry / connectivity probe 支持 computer provider

#### PR1: config plumbing 与 fallback executor

状态：已完成

提交：

- `27d3b05 Add computer use config plumbing and fallback executor`

内容：

- `computer_use` 配置从系统接口贯通到 runtime/model profile
- 新增 `UnavailableComputerExecutor`
- 补对应单测

#### PR2: response loop

状态：已完成

提交：

- `b63b916 Implement computer use response loop`

内容：

- 新增 `ComputerUseSession`
- provider 改为真正调用 session，而不是 placeholder runtime error
- 实现 `computer_call -> execute -> screenshot -> computer_call_output`
- 补 focused unit tests

#### PR3: safety approval integration

状态：已完成

提交：

- `6dead32 Integrate computer use safety approvals`

内容：

- `pending_safety_checks` 接入现有 approval ticket / approval manager / runs approval API
- run runtime 正确切换到 `AWAITING_TOOL_APPROVAL`
- 批准后恢复执行，拒绝/超时后停留在 paused
- 补 `approve` / `deny` 分支测试

### 7.2 Completed Follow-up PRs

#### PR4: real executor backend

Status: completed

Content:

- Added `src/agent_teams/computer/executor_config.py` to load executor backend settings from `.env` and process env
- Added `src/agent_teams/computer/vm_executor.py` with an HTTP-agent-based `VmComputerExecutor`
- Updated `ServerContainer` to select `VmComputerExecutor` or `UnavailableComputerExecutor` from config
- Added `tests/unit_tests/computer/test_executor_config.py` and `tests/unit_tests/computer/test_vm_executor.py`

#### PR5: artifact persistence

Status: completed

Content:

- Added `src/agent_teams/computer/artifact_store.py`
- `ComputerUseSession` now persists every screenshot into workspace session artifacts
- `TOOL_RESULT` payload now carries screenshot `artifact_path`
- Added `tests/unit_tests/computer/test_artifact_store.py` and session artifact assertions

#### PR6: UI / SSE visualization

Status: completed (minimal reuse version)

Content:

- Continued reusing the existing `TOOL_CALL` / `TOOL_RESULT` / `TOOL_APPROVAL_*` SSE events
- Frontend approval titles now show the requested computer action for `computer_use`
- Frontend result rendering for `computer_use` now summarizes action, URL, window, and artifact references
- Screenshot preview now reuses the existing session artifact endpoint instead of introducing a dedicated computer-only UI surface

#### PR7: notification integration

Status: completed

Content:

- `ComputerUseSession` now emits approval-request notifications through the existing `NotificationService`
- Frontend notification copy now uses computer-action wording for `computer_use`
- Computer approvals reuse the existing dedupe and channel configuration model

#### PR8: stricter policy model

Status: completed

Content:

- `ToolApprovalPolicy` now has computer-action approval rules and risk-level helpers
- `ComputerUseSession` now handles both `pending_safety_checks` and policy-driven computer-action approvals
- Low-risk actions like `wait` can pass automatically, while `click` / `type` / `keypress` / `drag` require approval by default
- Added `tests/unit_tests/tools/runtime/test_policy.py` and policy-approval session assertions

#### PR9: screenshot preview API

Status: completed

Commit:

- `eb8b29b Add screenshot preview API`

Content:

- Added `GET /api/sessions/{session_id}/artifacts/{artifact_path}` to stream session-scoped artifacts securely
- `ComputerUseSession` now emits both screenshot `artifact_path` and `artifact_url`
- Frontend `computer_use` tool result rendering now shows inline screenshot preview through the existing markdown/image path
- Added router, service, artifact-store, and session tests; updated `docs/api-design.md`

#### PR10: computer session / turn persistence

Status: completed

Commit:

- `740823e Add computer session and turn tables`

Content:

- Added `computer_sessions` and `computer_turns` tables through `ComputerSessionRepository`
- `ComputerUseSession` now persists executor-session lifecycle, latest desktop context, and per-action turn records
- Session deletion now cleans persisted computer session / turn rows together with other session data
- Added repository and integration tests; updated `docs/database-schema.md`

## 8. Follow-up Enhancements

The main chain is now runnable. Useful next enhancements are:

1. Add finer-grained computer-specific events such as `computer_screenshot_captured`.
2. Refine computer-action risk models for login, upload, download, submit, and similar flows.
3. Add richer replay and audit views on top of the persisted `computer_sessions` / `computer_turns` data.
4. Add other executor backends if a VM HTTP agent is not sufficient.
5. Add a dedicated screenshot timeline or gallery surface if the current inline preview becomes insufficient.

## 9. Current Risks And Limits

- Real execution still depends on an external VM HTTP agent; without backend config the system still falls back to `UnavailableComputerExecutor`.
- The current screenshot UX is intentionally minimal: inline preview is available, but there is still no dedicated screenshot timeline or replay page.
- `computer_use.environment` still has a local-to-OpenAI tool-schema mapping layer.
- Persisted computer session / turn data is now available, but it is not yet surfaced through dedicated query APIs or replay views.

## 10. Conclusion

The repository now has the full planned PR0-PR8 computer-use path implemented, plus two follow-up capabilities that close the main observability gaps:

- provider/config plumbing
- `Responses API` execution loop
- safety approval and policy approval integration
- VM executor backend config and runtime wiring
- screenshot artifact persistence and preview API
- persisted `computer_sessions` / `computer_turns` audit tables
- reused SSE/UI/notification surfaces with computer-specific wording and inline screenshot preview

That means the codebase is now not only architecturally aligned with computer use, but also equipped with a real executor path, approvals, notifications, artifact preview, and durable computer-action audit data.
