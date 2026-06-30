"""Typed-empty domain read routes for the Artemis client."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from artemis.api.auth import Principal, require_session

router = APIRouter(prefix="/app")


class CalendarEvent(BaseModel):
    id: str
    title: str
    start: str
    end: str
    kind: Literal["event", "held_tentative"]
    attendees: list[str] | None = None
    rsvp: Literal["yes", "no", "maybe"] | None = None


class CalendarTaskDue(BaseModel):
    title: str
    task_id: str


class CalendarRead(BaseModel):
    events: list[CalendarEvent] = Field(default_factory=list)
    tasksDueByDay: dict[str, list[CalendarTaskDue]] = Field(default_factory=dict)  # noqa: N815


class TaskItem(BaseModel):
    title: str
    task_id: str
    due: str | None = None


class TaskSuggestion(BaseModel):
    title: str
    suggestion_id: str


class TasksRead(BaseModel):
    overdue: list[TaskItem] = Field(default_factory=list)
    today: list[TaskItem] = Field(default_factory=list)
    upcoming: list[TaskItem] = Field(default_factory=list)
    suggestions: list[TaskSuggestion] = Field(default_factory=list)


class ProjectItem(BaseModel):
    id: str
    name: str
    status: Literal["active", "blocked", "done"]
    target: str | None = None
    openTasks: int  # noqa: N815


class ProjectsRead(BaseModel):
    projects: list[ProjectItem] = Field(default_factory=list)


class GmailNeed(BaseModel):
    id: str
    sender: str
    subject: str
    why: str


class GmailSignal(BaseModel):
    id: str
    sender: str
    subject: str
    ts: str


class GmailRead(BaseModel):
    needsYou: list[GmailNeed] = Field(default_factory=list)  # noqa: N815
    signal: list[GmailSignal] = Field(default_factory=list)


class FinanceDaily(BaseModel):
    weekday: str
    date: str
    amount: float | None
    is_today: bool


class FinanceCategory(BaseModel):
    name: str
    amount: float
    pct: float
    color: str


class FinanceTransaction(BaseModel):
    date: str
    merchant: str
    category: str
    amount: float


class FinanceBill(BaseModel):
    name: str
    when: str
    overdue: bool
    amount: float
    is_sub: bool
    paid: bool


class FinanceRead(BaseModel):
    week_total: float = 0
    mtd_total: float = 0
    daily: list[FinanceDaily] = Field(default_factory=list)
    categories: list[FinanceCategory] = Field(default_factory=list)
    transactions: list[FinanceTransaction] = Field(default_factory=list)
    bills: list[FinanceBill] = Field(default_factory=list)
    unusual: object | None = None
    duplicate: object | None = None
    ambiguous: object | None = None


class ReviewItem(BaseModel):
    name: str
    description: str
    status: str
    action_class: str
    safety: str
    explanation: str


class PendingActionResponse(BaseModel):
    id: str
    module: str
    tool: str
    summary: str
    action_class: str
    status: str
    created_at: datetime
    expires_at: datetime
    result: dict[str, object] | None


class ReviewNameRequest(BaseModel):
    name: str


class ActionIdRequest(BaseModel):
    id: str


class TaskSuggestionAcceptRequest(BaseModel):
    suggestion_id: str
    due_at: str | None = None
    project_id: str | None = None


class TaskSuggestionAcceptResponse(BaseModel):
    task: dict[str, object]


class TaskSuggestionRejectRequest(BaseModel):
    suggestion_id: str


class OkResponse(BaseModel):
    ok: bool


@router.get("/calendar", response_model=CalendarRead)
async def calendar_read(_principal: Principal = Depends(require_session)) -> CalendarRead:
    return CalendarRead()


@router.get("/tasks", response_model=TasksRead)
async def tasks_read(_principal: Principal = Depends(require_session)) -> TasksRead:
    return TasksRead()


@router.get("/projects", response_model=ProjectsRead)
async def projects_read(_principal: Principal = Depends(require_session)) -> ProjectsRead:
    return ProjectsRead()


@router.get("/email", response_model=GmailRead)
async def email_read(_principal: Principal = Depends(require_session)) -> GmailRead:
    return GmailRead()


@router.get("/finance", response_model=FinanceRead)
async def finance_read(_principal: Principal = Depends(require_session)) -> FinanceRead:
    return FinanceRead()


@router.get("/review/pending", response_model=list[ReviewItem])
async def review_pending(_principal: Principal = Depends(require_session)) -> list[ReviewItem]:
    return []


@router.get("/review/auto-enabled", response_model=list[ReviewItem])
async def review_auto_enabled(
    _principal: Principal = Depends(require_session),
) -> list[ReviewItem]:
    return []


@router.post("/review/approve", response_model=ReviewItem)
async def review_approve(
    body: ReviewNameRequest,
    _principal: Principal = Depends(require_session),
) -> ReviewItem:
    return _settled_review_item(body.name, "approved")


@router.post("/review/reject", response_model=ReviewItem)
async def review_reject(
    body: ReviewNameRequest,
    _principal: Principal = Depends(require_session),
) -> ReviewItem:
    return _settled_review_item(body.name, "rejected")


@router.get("/actions/pending", response_model=list[PendingActionResponse])
async def actions_pending(
    _principal: Principal = Depends(require_session),
) -> list[PendingActionResponse]:
    return []


@router.post("/actions/approve", response_model=PendingActionResponse)
async def actions_approve(
    _body: ActionIdRequest,
    _principal: Principal = Depends(require_session),
) -> PendingActionResponse:
    raise HTTPException(status_code=404, detail="action not found")


@router.post("/actions/reject", response_model=PendingActionResponse)
async def actions_reject(
    _body: ActionIdRequest,
    _principal: Principal = Depends(require_session),
) -> PendingActionResponse:
    raise HTTPException(status_code=404, detail="action not found")


@router.post("/tasks/suggestion/accept", response_model=TaskSuggestionAcceptResponse)
async def task_suggestion_accept(
    _body: TaskSuggestionAcceptRequest,
    _principal: Principal = Depends(require_session),
) -> TaskSuggestionAcceptResponse:
    raise HTTPException(status_code=404, detail="suggestion not found")


@router.post("/tasks/suggestion/reject", response_model=OkResponse)
async def task_suggestion_reject(
    _body: TaskSuggestionRejectRequest,
    _principal: Principal = Depends(require_session),
) -> OkResponse:
    return OkResponse(ok=True)


def _settled_review_item(name: str, status: str) -> ReviewItem:
    return ReviewItem(
        name=name,
        description="",
        status=status,
        action_class="",
        safety="",
        explanation="",
    )
