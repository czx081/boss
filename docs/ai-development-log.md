# AI Prompt 与问题解决记录

## 使用 AI 的方式

本项目允许 AI 辅助开发。AI 用于：

- 将笔试要求拆分为运行时、工具、Memory、持久化、UI 和文档。
- 生成初始代码并做静态检查。
- 设计 Fake LLM 测试，避免测试阶段消耗真实 API Token。
- 检查最大步数、危险表达式执行和跨 Session 数据隔离风险。

## 关键问题记录

### 为什么不用 Agent 框架

题目要求核心 runtime 自研，因此没有使用 LangChain、OpenHands 等。主循环、工具分发、Memory 组装和 Trace 均是普通 Python 实现。

### 如何支持真实 LLM 又保持供应商可替换

没有绑定特定厂商 SDK，而是用 Python 标准库调用 OpenAI-compatible `/chat/completions`，配置 URL、Key 和模型即可切换服务。

### 如何安全实现 Calculator

拒绝 `eval`。表达式解析成 AST，只允许数字、白名单二元运算符和一元运算符，并限制表达式长度与指数大小。

### 如何证明跨轮继续执行

Todo 是独立结构化状态，不只存在聊天文本中。每轮开始召回 Todo，后续追问可以基于任务 ID 和状态继续执行。

### 如何避免 Agent 无限循环

Runtime 使用固定 `max_steps`。每次 LLM 请求算一步，到达限制后写入 `max_steps_reached` Trace 并返回明确错误。

### 如何处理工具错误

参数解析或执行失败不会直接终止进程。错误被记录并作为 `tool` 结果回填给模型，模型可以在下一步修正参数。

## 人工确认项

- 真实 API Key 只能由提交者自行配置，不应写入 Git。
- 录屏前需要用目标模型完整走一遍 Demo 流程，确认该服务支持 Tool Calling。
- 提交前检查 `.env` 和 `data/agent.db` 未进入版本库。
