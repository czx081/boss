# 笔试提交说明

## 代码链接

GitHub 仓库：

<https://github.com/czx081/boss>

## 运行方式

完整步骤见 [README.md](README.md#快速运行)。

```powershell
cd D:\JAVA\boss
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
python -m uvicorn app.main:app --reload
```

浏览器访问 <http://127.0.0.1:8000>。

## 操作录屏

录屏完成后，建议上传到网盘、公开视频平台或 GitHub Release，并把链接填在这里：

> 录屏链接：待补充

具体演示顺序见 [docs/demo-script.md](docs/demo-script.md)。

## 要求对应关系

| 提交要求 | 对应内容 |
| --- | --- |
| 代码链接 | <https://github.com/czx081/boss> |
| 终端或网页操作录屏 | 本文“操作录屏”及 `docs/demo-script.md` |
| README | `README.md` |
| 运行方式 | `README.md` 的“快速运行” |
| 系统设计 | `docs/system-design.md` |
| Memory 召回时机与放置方式 | `docs/memory-design.md` |
| AI Prompt | `docs/prompts.md` |
| AI Prompt 与问题解决记录 | `docs/ai-development-log.md` |

## 提交前检查

- [ ] 使用真实 LLM 完成一次直接回答。
- [ ] Calculator、Weather、Search、Todo 均至少演示一次。
- [ ] 在同一 Session 中演示 Todo 跨轮查询或更新。
- [ ] 展示右侧 Execution Trace。
- [ ] 运行测试并录制 `8 passed`。
- [ ] 将录屏上传并填写录屏链接。
- [ ] 确认 `.env`、API Key 和 `data/agent.db` 未提交。

