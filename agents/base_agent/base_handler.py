from __future__ import annotations
from typing import Any, Dict, Optional, TypedDict
from langgraph.graph import StateGraph, END
from common.a2a_types import (
    Task,
    TaskState,
    TaskStatus,
    Message,
    TextPart,
    DataPart,
    Artifact,
)

class AgentState(TypedDict, total=False):
    task_id: str
    session_id: Optional[str]
    message: str
    history: list
    metadata: Dict[str, Any]
    result: str
    result_data: Optional[Dict[str, Any]]
    error: Optional[str]
    needs_input: bool
    input_prompt: str

class BaseHandler:

    def __init__(self):
        self.graph = StateGraph(AgentState)
        self._build_graph()
        self._compiled = self.graph.compile()

    def _build_graph(self) -> None:
        raise NotImplementedError

    async def handle(self, task: Task) -> Task:
        # Extract last user message, matches Task shape from base_a2a_server
        user_text = ""
        if task.history:
            last_user = next(
                (m for m in reversed(task.history) if m.role == "user"), None
            )
            if last_user:
                user_text = last_user.text()

        # Resume from persisted LangGraph state if task was INPUT_REQUIRED
        persisted: Dict[str, Any] = {}
        for k, v in list(task.metadata.items()):
            if k.startswith("__state_"):
                persisted[k[len("__state_"):]] = v
                del task.metadata[k]

        initial_state: AgentState = {
            "task_id": task.id,
            "session_id": task.session_id,
            "message": user_text,
            "history": [
                {"role": m.role, "text": m.text()} for m in task.history
            ],
            "metadata": dict(task.metadata),
            "result": persisted.get("result", ""),
            "result_data": persisted.get("result_data"),
            "error": None,
            "needs_input": False,
            "input_prompt": "",
            **{k: v for k, v in persisted.items()
               if k not in ("result", "result_data", "metadata")},
        }

        try:
            final_state = await self._compiled.ainvoke(initial_state)
        except Exception as exc:
            task.status = TaskStatus(
                state=TaskState.FAILED,
                message=Message(
                    role="agent",
                    parts=[TextPart(text=str(exc))],
                ),
            )
            return task

        if final_state.get("error"):
            task.status = TaskStatus(
                state=TaskState.FAILED,
                message=Message(
                    role="agent",
                    parts=[TextPart(text=final_state["error"])],
                ),
            )
            return task

        if final_state.get("needs_input"):
            task.status = TaskStatus(
                state=TaskState.INPUT_REQUIRED,
                message=Message(
                    role="agent",
                    parts=[TextPart(text=final_state.get("input_prompt", ""))],
                ),
            )
            # Persist state for next turn — read back by base_a2a_server
            task.metadata.update(final_state.get("metadata", {}))
            task.metadata["__langgraph_state__"] = {
                k: v for k, v in final_state.items()
                if k not in ("message", "history")
            }
            return task

        result_text = final_state.get("result", "")
        result_data = final_state.get("result_data")

        artifacts = []
        if result_data:
            artifacts.append(
                Artifact(
                    name="result",
                    parts=[DataPart(data=result_data)],
                )
            )

        task.status = TaskStatus(
            state=TaskState.COMPLETED,
            message=Message(
                role="agent",
                parts=[TextPart(text=result_text)],
            ),
        )
        task.artifacts = artifacts
        task.metadata.update(final_state.get("metadata", {}))
        return task


    def add_node(self, name: str, func) -> None:
        self.graph.add_node(name, func)

    def add_edge(self, source: str, target: str) -> None:
        self.graph.add_edge(source, target)

    def add_conditional_edges(
        self, source: str, condition, mapping: dict
    ) -> None:
        self.graph.add_conditional_edges(source, condition, mapping)

    def set_entry(self, node: str) -> None:
        self.graph.set_entry_point(node)

    def finish(self, node: str) -> None:
        self.graph.add_edge(node, END)
