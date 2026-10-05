"""/zoom/... 엔드포인트. 얇은 층, 옮기지 않는다."""

import json
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse, Response
from pydantic import AwareDatetime, BaseModel

from app.core.config import Settings, get_settings
from app.core.oauth import access_token_dependency
from app.services.zoom import usecases
from app.services.zoom.client import ZoomApiError, ZoomClient

router = APIRouter(prefix="/zoom", tags=["zoom"])

zoom_token = access_token_dependency("zoom")


def _zoom(token: str = Depends(zoom_token)) -> ZoomClient:
    return ZoomClient(token)


def _to_http(e: ZoomApiError) -> HTTPException:
    return HTTPException(e.status, {"api": "ZoomApiError", "code": e.code, "message": e.message, "rate_limit": e.is_rate_limit})


# ---------- 유즈케이스 1 ----------


@router.get("/host-profile")
async def host_profile(zoom: ZoomClient = Depends(_zoom)):
    try:
        p = await usecases.get_host_profile(zoom)
    except ZoomApiError as e:
        raise _to_http(e)
    return {"plan_type": p.plan_type, "timezone": p.timezone, "has_40_minute_limit": p.has_40_minute_limit}


# ---------- 유즈케이스 2 ----------


class Schedule(BaseModel):
    start_time: AwareDatetime  # 예: 2026-10-10T14:00:00+09:00
    duration_minutes: int = 40
    timezone: str = "Asia/Seoul"
    settings: dict | None = None  # Zoom settings 그대로(waiting_room, join_before_host …)


class GroupMeetingsRequest(Schedule):
    team_names: list[str]
    topic_template: str = "{{activity_name}} - {{team_name}}"
    activity_name: str = ""


@router.post("/create-group-meetings")
async def create_group_meetings(req: GroupMeetingsRequest, zoom: ZoomClient = Depends(_zoom)):
    return await usecases.create_group_meetings(
        zoom, req.team_names, req.topic_template, req.start_time, req.duration_minutes, req.timezone, req.activity_name, req.settings
    )


class BreakoutMeetingRequest(Schedule):
    topic: str
    rooms: dict[str, list[str]]  # {그룹명: [학생 이메일]}


@router.post("/create-breakout-meeting")
async def create_breakout_meeting(req: BreakoutMeetingRequest, zoom: ZoomClient = Depends(_zoom)):
    try:
        return await usecases.create_breakout_meeting(zoom, req.topic, req.start_time, req.duration_minutes, req.timezone, req.rooms, req.settings)
    except ZoomApiError as e:
        raise _to_http(e)


# ---------- 유즈케이스 3 ----------


class RecurringMeetingRequest(Schedule):
    topic: str
    weekly_days: list[int]  # 1=일 … 7=토
    end_date_time: AwareDatetime | None = None
    end_times: int | None = None


@router.post("/create-recurring-meeting")
async def create_recurring_meeting(req: RecurringMeetingRequest, zoom: ZoomClient = Depends(_zoom)):
    try:
        return await usecases.create_recurring_meeting(
            zoom, req.topic, req.start_time, req.duration_minutes, req.timezone, req.weekly_days, req.end_date_time, req.end_times, req.settings
        )
    except ZoomApiError as e:
        raise _to_http(e)
    except ValueError as e:
        raise HTTPException(422, str(e))


# ---------- 유즈케이스 4 ----------


class RescheduleRequest(BaseModel):
    start_time: AwareDatetime | None = None
    duration_minutes: int | None = None
    topic: str | None = None
    occurrence_id: str | None = None


@router.post("/reschedule/{meeting_id}")
async def reschedule(meeting_id: str, req: RescheduleRequest, zoom: ZoomClient = Depends(_zoom)):
    try:
        return await usecases.reschedule_meeting(zoom, meeting_id, req.start_time, req.duration_minutes, req.topic, req.occurrence_id)
    except ZoomApiError as e:
        raise _to_http(e)
    except ValueError as e:
        raise HTTPException(422, str(e))


@router.post("/cancel/{meeting_id}")
async def cancel(meeting_id: str, occurrence_id: str | None = Query(default=None), zoom: ZoomClient = Depends(_zoom)):
    """occurrence_id가 없으면 미팅 전체(반복이면 시리즈 전체)를 지운다."""
    try:
        await usecases.cancel_meeting(zoom, meeting_id, occurrence_id=occurrence_id)
    except ZoomApiError as e:
        raise _to_http(e)
    return {"meeting_id": meeting_id, "occurrence_id": occurrence_id, "deleted": True}


# ---------- 유즈케이스 5 ----------


@router.get("/start/{meeting_id}")
async def start(meeting_id: str, zoom: ZoomClient = Depends(_zoom)):
    """교수자 "시작" 버튼. start_url을 응답 본문에 싣지 않고 바로 리다이렉트한다."""
    try:
        return RedirectResponse(await usecases.get_start_url(zoom, meeting_id))
    except ZoomApiError as e:
        raise _to_http(e)


# ---------- 유즈케이스 6: 웹훅 + 출석 집계 ----------


class AttendanceRequest(BaseModel):
    meeting_id: str
    meeting_start: AwareDatetime
    roster: dict[str, str]  # {학번: 이름}
    min_minutes: int = 20
    late_after_minutes: int = 10


@router.post("/attendance")
async def attendance(req: AttendanceRequest):
    """웹훅으로 쌓아 둔 이벤트(EVENT_LOG_PATH)로 출석을 집계한다. 서비스 레포에서는 DB에서 이벤트를 읽는다."""
    events = [json.loads(line) for line in EVENT_LOG_PATH.read_text(encoding="utf-8").splitlines()] if EVENT_LOG_PATH.exists() else []
    return usecases.summarize_attendance(events, req.roster, req.meeting_id, req.meeting_start, req.min_minutes, req.late_after_minutes)

# 테스트용: 받은 이벤트를 원본 그대로 한 줄씩 쌓는다(이름·이메일 포함이라 .gitignore). 서비스 레포에서는 DB·큐로 바꾼다.
EVENT_LOG_PATH = Path(".webhooks/zoom_events.jsonl")


@router.post("/webhook")
async def webhook(request: Request, settings: Settings = Depends(get_settings)):
    secret = settings.zoom_webhook_secret_token
    if not secret:
        raise HTTPException(500, "ZOOM_WEBHOOK_SECRET_TOKEN 이 .env에 없습니다")

    raw = await request.body()  # 서명은 원본 바이트로 검증하므로 JSON 파싱보다 먼저 읽는다
    ok = usecases.verify_signature(
        secret,
        request.headers.get("x-zm-request-timestamp", ""),
        raw,
        request.headers.get("x-zm-signature", ""),
    )
    if not ok:
        raise HTTPException(401, "x-zm-signature 불일치")

    body = json.loads(raw)
    if body.get("event") == "endpoint.url_validation":
        return usecases.url_validation_response(secret, body["payload"]["plainToken"])

    EVENT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with EVENT_LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"received_at": datetime.now(UTC).isoformat(), **body}, ensure_ascii=False) + "\n")
    return Response(status_code=204)
