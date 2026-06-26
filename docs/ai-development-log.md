# AI Prompt 与问题解决记录

## 使用 AI 的方式

本项目允许使用 AI 辅助开发。AI 主要用于：

- 将笔试要求拆分为 runtime、tool、memory、持久化、UI 和文档。
- 生成初始代码并做静态检查。
- 设计 Fake LLM 测试，避免测试阶段消耗真实 API Token。
- 检查最大步数、危险表达式执行、跨 Session 数据隔离等风险。
- 根据面试反馈继续做低延迟优化。

## 关键问题记录

### 为什么不使用 Agent 框架

题目要求核心 runtime 自研，因此没有用 LangChain、OpenHands、Spring AI、Dify、n8n 等框架完成主流程。主循环、工具分发、memory 组装、trace 记录都由普通 Python 实现。

### 如何支持真实 LLM 又保持供应商可替换

项目没有绑定特定厂商 SDK，而是调用 OpenAI-compatible `/chat/completions`。通过配置 `LLM_BASE_URL`、`LLM_MODEL`、`LLM_API_KEY` 可以切换 DeepSeek、OpenAI 或其他兼容服务。

### 如何安全实现 Calculator

拒绝使用 `eval`。表达式解析成 AST，只允许数字、白名单二元运算符和一元运算符，并限制表达式长度与指数大小。

### 如何证明跨轮继续执行

Todo 是独立结构化状态，不只存在聊天文本中。每轮开始都会召回 Todo；后续追问“刚才那个任务”时，模型可以基于任务状态继续回答或更新。

### 如何避免 Agent 无限循环

Runtime 使用固定 `max_steps`。每次 LLM 请求算一步，到达限制后写入 `max_steps_reached` trace，并返回明确错误。

### 如何处理工具错误

参数解析或执行失败不会直接终止进程。错误会被记录，并作为 `tool` 结果回填给模型，模型可以在下一步修正参数。

### 面试后针对延迟做了哪些修改

面试官重点关注用户等待时间，项目随后做了这些改造：

- memory 从串行召回改为并行召回。
- 每个召回源增加超时和降级。
- 短期记忆从固定轮数改为 token 预算。
- TaskContext 从普通历史中拆出来，结构化注入。
- 增加 context block 优先级，任务状态优先保留。
- 增加 schema/context cache，减少重复构造。
- 增加只读工具并行执行。
- 增加后台 summary compaction，避免压缩阻塞当前请求。
- 增加 SSE 阶段事件流式接口，降低前端等待感。
- 增加 `LLM_MAX_TOKENS` 控制输出长度。

### 为什么不是所有东西都并行

并行适合只读、无副作用、互不依赖的操作，例如 calculator、search、weather。`todo` 会修改任务状态，如果并行执行可能出现写入顺序不确定，因此保持串行。

### 为什么摘要放后台

摘要会额外消耗时间。如果在用户请求链路中同步执行，用户会明显等待更久。因此当前请求只负责判断是否需要压缩，真正压缩放到后台线程执行，下一轮请求再读取更新后的 summary。

## 人工确认项

- 真实 API Key 只放在本地 `.env`，不能写入 Git。
- 录屏前需要用目标模型完整走一遍 Demo 流程，确认服务支持 tool calling。
- 提交前检查 `.env`、`data/agent.db`、缓存文件没有进入版本库。
