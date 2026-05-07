import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class Actor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    email: EmailStr | None
    source: Literal["header", "body"]
    role: Literal["sender", "recipient", "cc", "mentioned"] | None = None


class ConcludedDiscussion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: str
    resolution: str
    resolved_at: datetime
    resolved_in_thread_id: str | None = None


class OpenActionItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item: str
    owner: str = Field(description='Name or "unassigned"')
    context: str
    raised_at: datetime


class GeminiSummarySchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actors: list[Actor]
    concluded_discussions: list[ConcludedDiscussion]
    open_action_items: list[OpenActionItem]


class SummaryResponse(GeminiSummarySchema):
    client_id: uuid.UUID
    emails_analyzed_count: int
    last_refreshed_at: datetime
    gemini_model_version: str


class RefreshSummaryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    force: bool = False

