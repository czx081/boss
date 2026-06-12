# Minimal Agent

一个不依赖 LangChain、OpenHands 等 Agent 框架的最小可用 Agent。核心 runtime 自行实现 LLM 决策、工具执行、结果回填、循环控制、Session Memory 和执行 Trace。

## 功能

- 多轮对话与 SQLite Session 持久化
- 真实 OpenAI-compatible LLM API
- 自研 Agent tool-use loop
- `calculator`、`search`、`weather`、`todo` 四个工具
- 最大步数限制、参数错误与 API 异常处理
- 跨轮 Todo 创建、查询和状态更新
- 网页聊天界面与逐步执行 Trace
- 使用 Fake LLM 的核心流程测试，不消耗 API Token

## 快速运行

当前项目兼容 Python 3.8+，建议正式环境使用 Python 3.11 或 3.12。

```powershell
cd D:\JAVA\boss
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

编辑 `.env`，至少设置：

```dotenv
LLM_API_KEY=你的真实密钥
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o-mini
```

也可填入其他兼容 OpenAI Chat Completions 与 tool calling 协议的服务地址和模型。

启动：

```powershell
uvicorn app.main:app --reload
```

访问 <http://127.0.0.1:8000>。API 文档位于 <http://127.0.0.1:8000/docs>。

运行测试：

```powershell
python -m unittest discover -s tests -v
```

## 演示流程

在同一个 Session 中依次输入：

1. `计算 (18 + 6) * 4`
2. `帮我创建一个“准备 Agent 项目演示”的任务，并标记为进行中`
3. `刚才那个任务进度怎么样？`
4. `把它标记为完成`
5. `查询上海天气`

右侧 Trace 会展示 `llm_request`、`tool_call`、`tool_result` 和 `final_answer`。点击“新建 Session”后，任务状态与原 Session 隔离。

## 核心循环

`app/agent/runtime.py` 中的 runtime 每轮执行：

1. 保存用户消息。
2. 召回 Session 历史和持久 Todo 状态。
3. 将消息、工具 JSON Schema 发送给真实 LLM。
4. 没有工具调用时保存并返回最终答案。
5. 有工具调用时解析参数、执行工具，将结果作为 `tool` 消息回填。
6. 继续请求 LLM，直到最终回答或达到 `AGENT_MAX_STEPS`。

核心流程只使用普通 Python、HTTP 请求和 JSON 数据结构，没有使用现成 Agent runtime。

## Memory 设计

召回发生在每次 `AgentRuntime.run` 开始时：

- 从 `messages` 表读取当前 Session 最近 `AGENT_HISTORY_LIMIT` 条消息。
- 从 `todos` 表读取当前 Session 的全部任务状态。
- 第一条消息放固定 System Prompt。
- 第二条 System Message 放结构化 Session 状态。
- 之后按时间顺序放历史对话。

工具调用产生的中间消息只保留在当前执行循环中；最终回答和用户消息持久化。这避免下轮构造出缺少配对关系的历史 `tool_call`，同时持久任务状态由独立 Todo 表可靠保存。

详细说明见 [docs/memory-design.md](docs/memory-design.md)。

## 项目结构

```text
app/
  agent/       LLM 客户端、Memory、Prompt、Runtime、Trace
  tools/       工具实现与注册中心
  static/      网页界面
  database.py  SQLite schema 和连接
  repositories.py 持久化访问
  main.py      FastAPI 接口
tests/         工具、Memory、持久化和 Runtime 测试
docs/          系统设计、Prompt、开发记录、录屏脚本
```

## 已知边界

- `search` 和 `weather` 按题目允许采用 mock，结果不代表真实网络数据。
- 当前 Memory 使用最近消息窗口加结构化任务状态，未实现向量检索。
- Chat Completions 服务必须支持 OpenAI 风格的 `tools` / `tool_calls`。
- Demo 页面切换 Session 后不回显旧聊天内容，但后端会继续召回该 Session 历史。

## 更多文档

- [系统设计](docs/system-design.md)
- [Memory 设计](docs/memory-design.md)
- [Prompt](docs/prompts.md)
- [AI Prompt 与问题解决记录](docs/ai-development-log.md)
- [录屏脚本](docs/demo-script.md)
