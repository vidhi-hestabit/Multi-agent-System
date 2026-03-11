from __future__ import annotations
from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, Field

class NewsArticle(BaseModel):
    title: str
    description: Optional[str] = None
    url: str
    source: str
    published_at: Optional[datetime] = None
    content: Optional[str] = None

class WeatherData(BaseModel):
    city: str
    country: str
    temperature: float
    feels_like: float
    humidity: int
    wind_speed: float
    description: str
    icon: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)

class ReportSection(BaseModel):
    heading: str
    content: str

class Report(BaseModel):
    title: str
    summary: str
    sections: list[ReportSection] = []
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: dict[str, Any] = {}

class AgentResult(BaseModel):
    agent: str
    success: bool
    data: Any = None
    error: Optional[str] = None
    duration_ms: Optional[float] = None

class OrchestratorResponse(BaseModel):
    query: str
    intent: str
    results: list[AgentResult]
    summary: str
    generated_at: datetime = Field(default_factory=datetime.utcnow)
