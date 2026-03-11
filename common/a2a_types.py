from __future__ import annotations
from enum import Enum
from typing import Any, Literal, Optional, Union
from pydantic import BaseModel, Field
import uuid

class TextPart(BaseModel):
    type: Literal["text"] = "text"
    text: str

class DataPart(BaseModel):
    type: Literal["data"] = "data"
    data: dict[str, Any]
    mime_type: str = "application/json"

Part = Union[TextPart, DataPart]

class Message(BaseModel):
    role: Literal["user", "agent"]
    parts: list[Part]

    def text(self) -> str:
        return " ".join(p.text for p in self.parts if isinstance(p, TextPart))

class TaskState(str, Enum):
    SUBMITTED = "submitted"
    WORKING = "working"
    INPUT_REQUIRED = "input-required"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"

class TaskStatus(BaseModel):
    state: TaskState
    message: Optional[Message] = None
    timestamp: Optional[str] = None

class Artifact(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    parts: list[Part]
    index: int = 0
    append: Optional[bool] = None
    last_chunk: Optional[bool] = None

class Task(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: Optional[str] = None
    status: TaskStatus = Field(
        default_factory=lambda: TaskStatus(state=TaskState.SUBMITTED)
    )
    history: list[Message] = []
    artifacts: list[Artifact] = []
    metadata: dict[str, Any] = {}

class TaskSendRequest(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: Optional[str] = None
    message: Message
    metadata: dict[str, Any] = {}

class TaskSendResponse(BaseModel):
    id: str
    status: TaskStatus
    artifacts: list[Artifact] = []

class TaskGetResponse(BaseModel):
    id: str
    status: TaskStatus
    artifacts: list[Artifact] = []
    history: list[Message] = []

class AgentSkill(BaseModel):
    id: str
    name: str
    description: str
    input_modes: list[str] = ["text"]
    output_modes: list[str] = ["text"]
    tags: list[str] = []
    examples: list[str] = []

class AgentCapabilities(BaseModel):
    streaming: bool = True
    push_notifications: bool = False
    state_transition_history: bool = True

class AgentCard(BaseModel):
    name: str
    description: str
    url: str
    version: str = "1.0.0"
    capabilities: AgentCapabilities = Field(default_factory=AgentCapabilities)
    skills: list[AgentSkill] = []
    default_input_modes: list[str] = ["text"]
    default_output_modes: list[str] = ["text"]