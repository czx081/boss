from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=8000)
    session_id: Optional[str] = None


class TraceItem(BaseModel):
    step: int
    event: str
    name: Optional[str] = None
    input: Optional[Dict[str, Any]] = None
    output: Optional[Any] = None
    error: Optional[str] = None
    created_at: str


class ChatResponse(BaseModel):
    session_id: str
    answer: str
    traces: List[TraceItem]


class SessionSummary(BaseModel):
    id: str
    title: str
    created_at: str
    updated_at: str

