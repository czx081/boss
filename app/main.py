import json
from pathlib import Path
from typing import List

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app.agent.llm_client import LLMClient
from app.agent.memory import Memory
from app.agent.runtime import AgentRuntime
from app.config import settings
from app.database import init_db
from app.repositories import Repository
from app.schemas import ChatRequest, ChatResponse, SessionSummary
from app.tools.registry import ToolRegistry


app = FastAPI(title="Minimal Agent", version="0.1.0")
static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

repository = Repository()
tools = ToolRegistry(repository)
memory = Memory(repository, settings.agent_history_limit)
llm = LLMClient(
    api_key=settings.llm_api_key,
    base_url=settings.llm_base_url,
    model=settings.llm_model,
    max_tokens=settings.llm_max_tokens,
)
runtime = AgentRuntime(
    repository=repository,
    llm=llm,
    tools=tools,
    memory=memory,
    max_steps=settings.agent_max_steps,
)


@app.on_event("startup")
def startup() -> None:
    init_db()


@app.get("/")
def index() -> FileResponse:
    return FileResponse(str(static_dir / "index.html"))


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "model": settings.llm_model,
        "llm_configured": bool(settings.llm_api_key),
    }


@app.get("/api/sessions", response_model=List[SessionSummary])
def list_sessions() -> List[dict]:
    return repository.list_sessions()


@app.post("/api/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    session_id = request.session_id
    if session_id:
        if not repository.session_exists(session_id):
            raise HTTPException(status_code=404, detail="Session not found")
    else:
        session_id = repository.create_session(request.message)

    answer, request_id = runtime.run(session_id, request.message)
    return ChatResponse(
        session_id=session_id,
        answer=answer,
        traces=repository.get_traces(request_id),
    )


@app.post("/api/chat/stream")
def chat_stream(request: ChatRequest) -> StreamingResponse:
    def event_stream():
        session_id = request.session_id
        if session_id:
            if not repository.session_exists(session_id):
                yield _sse("error", {"detail": "Session not found"})
                return
        else:
            session_id = repository.create_session(request.message)

        yield _sse("start", {"session_id": session_id})
        answer, request_id = runtime.run(session_id, request.message)
        traces = repository.get_traces(request_id)
        for item in traces:
            yield _sse("trace", item)
        yield _sse(
            "answer",
            {
                "session_id": session_id,
                "answer": answer,
                "traces": traces,
            },
        )
        yield _sse("done", {"session_id": session_id})

    return StreamingResponse(event_stream(), media_type="text/event-stream")


def _sse(event: str, data: dict) -> str:
    return "event: {}\ndata: {}\n\n".format(
        event,
        json.dumps(data, ensure_ascii=False),
    )
