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

## 2. 范围与非目标

范围：

- 在 provider 层新增 `openai_responses_computer`
- 直接对接 OpenAI `Responses API`
- 引入独立的 `ComputerUseSession`
- 引入 `ComputerExecutor` 抽象，底层可替换为 VM 或桌面执行器
- 接入现有 run 事件流
- 接入现有 approval ticket / approval manager / runs approval API
- 在系统配置中支持 `computer_use` 配置项

非目标：

- 不实现 DOM 驱动浏览器自动化接口
- 不把 computer use 混入现有 pydantic-ai tool call 链路
- 不在本阶段实现真实 VM executor
- 不在本阶段实现截图工件持久化和前端截图时间线 UI
- 不在本阶段实现 notification service 对 computer approval 的专门通知文案

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

关键点：

- 当 `request.user_prompt` 为空时，会回退到 `MessageRepository.get_history_for_conversation_task()` 中提取最近的 `UserPromptPart`
- `computer_call_output` 使用截图 data URL + 可选 `current_url`
- 对 unsupported payload 会直接抛出 runtime error，不隐式降级

### 5.3 Executor 抽象

相关文件：

- `src/agent_teams/computer/action_models.py`
- `src/agent_teams/computer/executor_contracts.py`
- `src/agent_teams/computer/unavailable_executor.py`

当前接口：

- `start_session(run_id, instance_id)`
- `execute_action(session_id, action)`
- `capture_screenshot(session_id)`
- `get_context(session_id)`
- `stop_session(session_id)`

当前状态：

- 已有 `UnavailableComputerExecutor` 作为默认占位
- 真实 VM/desktop executor 仍未实现

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

### 7.2 未完成

#### PR4: real executor backend

状态：未开始

目标：

- 实现真实 `VmComputerExecutor` 或 `LocalDesktopExecutor`
- 将 `UnavailableComputerExecutor` 替换为可运行执行器
- 定义 executor 接入方式：HTTP agent、MCP 或本地驱动

建议文件：

- `src/agent_teams/computer/vm_executor.py`
- `src/agent_teams/computer/executor_client.py`
- `tests/unit_tests/computer/test_vm_executor.py`

#### PR5: artifact persistence

状态：未开始

目标：

- 持久化每步截图
- 可选保存录像或关键帧
- 为后续前端时间线和调试提供数据基础

建议文件：

- `src/agent_teams/computer/artifact_store.py`
- `src/agent_teams/computer/session_repo.py`
- `docs/database-schema.md` 更新 computer artifacts / sessions 表

#### PR6: UI / SSE visualization

状态：未开始

目标：

- 前端展示 computer use step timeline
- 展示最近截图和当前动作
- 在现有 tool approval UI 中明确区分普通工具审批和 computer safety check 审批

#### PR7: notification integration

状态：未开始

目标：

- 对 computer safety approval 发出与普通 tool approval 一致的通知
- 为通知文案增加 computer-specific 上下文

#### PR8: stricter policy model

状态：未开始

目标：

- 将 `ToolApprovalPolicy` 从“按工具名审批”扩展为“按 computer action 风险等级审批”
- 示例：
  - `wait` / `screenshot` 可自动放行
  - `click` / `type` / `keypress` 为中高风险
  - 登录、提交、下载、上传等更高风险动作可附加专门策略

## 8. 推荐 PR 分解

推荐后续继续按下面顺序推进：

1. PR4: real executor backend
2. PR5: artifact persistence
3. PR6: UI / SSE visualization
4. PR7: notification integration
5. PR8: stricter policy model

原因：

- 没有真实 executor，当前链路只能单测，无法真正运行
- 没有 artifact persistence，调试和 UI 都缺基础数据
- UI 和通知应建立在已稳定的后端事件和工件之上
- 更精细的 policy 应该放在真实 executor 和 UI 跑通之后再做

## 9. 当前风险与限制

- 当前默认 executor 仍是 `UnavailableComputerExecutor`，所以生产路径还不能真正操控计算机
- 当前 approval 复用现有 tool approval API，但 UI 侧是否已明确区分 computer safety check 仍待实现
- 当前 `computer_use.environment` 的本地配置语义与 OpenAI tool schema 的取值存在映射层
- 当前还没有 screenshot artifact 持久化，run 结束后无法回放 computer use 过程
- 当前没有 notification service 的 computer-specific approval 提醒

## 10. 结论

当前仓库已经完成 computer use 后端主链路的前三个关键阶段：

- provider/config 落地
- `Responses API` 执行闭环
- safety approval 接入现有审批体系

也就是说，架构上已经是 computer use，而不是 browser use。

剩余工作主要集中在“真实执行器”和“可观测性/UI”两块。只要补上真实 `ComputerExecutor` 实现，这条链路就可以从目前的单测可运行状态，推进到真正的端到端可用状态。
