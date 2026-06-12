from typing import Any, Dict, Optional

from app.repositories import Repository


class TraceRecorder:
    def __init__(self, repository: Repository, request_id: str, session_id: str):
        self.repository = repository
        self.request_id = request_id
        self.session_id = session_id

    def record(
        self,
        step: int,
        event: str,
        name: Optional[str] = None,
        input_data: Optional[Dict[str, Any]] = None,
        output_data: Any = None,
        error: Optional[str] = None,
    ) -> None:
        self.repository.add_trace(
            request_id=self.request_id,
            session_id=self.session_id,
            step=step,
            event=event,
            name=name,
            input_data=input_data,
            output_data=output_data,
            error=error,
        )

