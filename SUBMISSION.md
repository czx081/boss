# 笔试提交说明

## 代码链接

GitHub 仓库：

<https://github.com/czx081/boss>

## 运行方式

完整步骤见 [README.md](README.md)。

```powershell
cd D:\JAVA\boss
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
python -m uvicorn app.main:app --reload
```

浏览器访问：

<http://127.0.0.1:8000>

## 操作录屏

录屏文件：`2026-06-12 21-53-39.mp4`

- 夸克网盘：<https://pan.quark.cn/s/9a705b312cb6>
- 提取码：`ULEY`

演示顺序见 [docs/demo-script.md](docs/demo-script.md)。

## 要求对应关系

| 提交要求 | 对应内容 |
| --- | --- |
| 代码链接 | <https://github.com/czx081/boss> |
| 终端或网页操作录屏 | 本文“操作录屏”与 `docs/demo-script.md` |
| README | `README.md` |
| 运行方式 | `README.md` 的“快速运行” |
| 系统设计 | `docs/system-design.md` |
| memory 的召回时机与放置方式说明 | `docs/memory-design.md` |
| AI Prompt | `docs/prompts.md` |
| AI Prompt 与问题解决记录 | `docs/ai-development-log.md` |

## 提交前检查

- [x] 使用真实 LLM API 配置运行。
- [x] 支持 calculator、search、weather、todo 工具。
- [x] 支持同一 Session 的跨轮任务追问。
- [x] 支持最大步数限制和异常处理。
- [x] 支持工具调用 trace 和延迟 trace。
- [x] 支持 memory 并行召回、token 预算、上下文优先级和后台摘要。
- [x] 支持 SSE 阶段事件流式接口。
- [x] 已填写录屏链接。
- [x] `.env`、API Key、数据库文件不提交。
