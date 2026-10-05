"""Zoom 시나리오 흐름. FastAPI를 import하지 않는다.

유즈케이스(docs/zoom.md 1절, 2026-10-05 확정): 1 플랜 확인 · 2 그룹별 미팅 예약 · 3 정기 회의 · 4 일정 변경·취소 ·
5 호스트 시작 링크 · 6 출석 자동 집계(웹훅 participant_joined/left + 표시 이름의 학번 매칭).
"""

import hashlib
import hmac
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from app.core.models import Meeting
from app.services.zoom.client import ZoomApiError, ZoomClient
from app.services.zoom.mapper import meeting_from_zoom

SCHEDULED, RECURRING_FIXED = 2, 8  # Zoom 미팅 type


def render_topic(template: str, variables: dict[str, str]) -> str:
    """`{{name}}`을 값으로 바꾼다. 모르는 이름은 그대로 둔다."""
    return re.sub(r"\{\{\s*(\w+)\s*\}\}", lambda m: variables.get(m.group(1), m.group(0)), template)


def _zoom_time(dt: datetime) -> str:
    """Zoom은 UTC `yyyy-MM-ddTHH:mm:ssZ`를 받고, 표시 시간대는 `timezone` 필드로 따로 준다."""
    if dt.tzinfo is None:
        raise ValueError("start_time에는 시간대가 있어야 한다(예: datetime(..., tzinfo=ZoneInfo('Asia/Seoul')))")
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _meeting_body(topic: str, start_time: datetime, duration_minutes: int, timezone: str, settings: dict | None) -> dict:
    body = {"topic": topic, "type": SCHEDULED, "start_time": _zoom_time(start_time), "duration": duration_minutes, "timezone": timezone}
    if settings:
        body["settings"] = settings
    return body


# ---------- 유즈케이스 1: 교수자 플랜 확인 ----------


@dataclass
class HostProfile:
    plan_type: int  # 1 Basic · 2 Licensed · 4 Unassigned
    timezone: str | None

    @property
    def has_40_minute_limit(self) -> bool:
        """Basic 호스트의 미팅은 참가자가 1명 이상이면 40분에 끊긴다(docs/zoom.md 8절)."""
        return self.plan_type == 1


async def get_host_profile(zoom: ZoomClient) -> HostProfile:
    me = await zoom.get_me()
    return HostProfile(plan_type=me["type"], timezone=me.get("timezone"))


# ---------- 유즈케이스 2: 그룹별 미팅 예약 ----------


@dataclass
class GroupMeetingResult:
    team_name: str
    meeting: Meeting | None = None
    error: str | None = None


async def create_group_meetings(
    zoom: ZoomClient,
    team_names: list[str],
    topic_template: str,
    start_time: datetime,
    duration_minutes: int,
    timezone: str,
    activity_name: str = "",
    settings: dict | None = None,
) -> list[GroupMeetingResult]:
    """A 방식: 그룹마다 예약 미팅 하나. 그룹 수만큼 호출하므로 하루 100회(생성+수정 합산)를 넘지 않게 호출자가 센다.
    한 그룹이 실패해도 나머지를 계속한다. 학생에게 나눠줄 링크는 각 meeting.join_url."""
    results: list[GroupMeetingResult] = []
    for team in team_names:
        topic = render_topic(topic_template, {"team_name": team, "activity_name": activity_name})
        try:
            m = await zoom.create_meeting(_meeting_body(topic, start_time, duration_minutes, timezone, settings))
            results.append(GroupMeetingResult(team, meeting_from_zoom(m)))
        except ZoomApiError as e:
            results.append(GroupMeetingResult(team, error=str(e)))
    return results


async def create_breakout_meeting(
    zoom: ZoomClient,
    topic: str,
    start_time: datetime,
    duration_minutes: int,
    timezone: str,
    rooms: dict[str, list[str]],
    settings: dict | None = None,
) -> Meeting:
    """B 방식(비교용): 미팅 하나 + 그룹별 소회의실 사전 배정. rooms = {그룹명: [학생 이메일]}.
    학생이 그 이메일의 Zoom 계정으로 로그인해야 자동 배정된다(docs/zoom.md 10절 10항)."""
    breakout = {"enable": True, "rooms": [{"name": name, "participants": emails} for name, emails in rooms.items()]}
    m = await zoom.create_meeting(_meeting_body(topic, start_time, duration_minutes, timezone, {**(settings or {}), "breakout_room": breakout}))
    return meeting_from_zoom(m)


# ---------- 유즈케이스 3: 정기 회의 ----------


async def create_recurring_meeting(
    zoom: ZoomClient,
    topic: str,
    first_start_time: datetime,
    duration_minutes: int,
    timezone: str,
    weekly_days: list[int],
    end_date_time: datetime | None = None,
    end_times: int | None = None,
    settings: dict | None = None,
) -> Meeting:
    """매주 반복(type 8) 미팅 하나. weekly_days는 1=일 … 7=토. 끝은 end_date_time 또는 end_times(≤60) 중 하나.
    join_url은 모든 회차가 같고, 회차별 변경·취소는 Meeting.occurrences[].id로 한다."""
    if (end_date_time is None) == (end_times is None):
        raise ValueError("end_date_time과 end_times 중 하나만 준다")
    recurrence: dict = {"type": 2, "repeat_interval": 1, "weekly_days": ",".join(map(str, weekly_days))}
    if end_date_time:
        recurrence["end_date_time"] = _zoom_time(end_date_time)
    else:
        recurrence["end_times"] = end_times
    body = {**_meeting_body(topic, first_start_time, duration_minutes, timezone, settings), "type": RECURRING_FIXED, "recurrence": recurrence}
    return meeting_from_zoom(await zoom.create_meeting(body))


# ---------- 유즈케이스 4: 일정 변경·취소 ----------


async def reschedule_meeting(
    zoom: ZoomClient,
    meeting_id: str,
    start_time: datetime | None = None,
    duration_minutes: int | None = None,
    topic: str | None = None,
    occurrence_id: str | None = None,
) -> Meeting:
    """주어진 값만 바꾼다. occurrence_id를 주면 반복 미팅의 그 회차만. 하루 100회에 포함된다.
    PATCH는 204라 바뀐 값을 GET으로 다시 읽어 돌려준다."""
    body: dict = {}
    if start_time is not None:
        body["start_time"] = _zoom_time(start_time)
    if duration_minutes is not None:
        body["duration"] = duration_minutes
    if topic is not None:
        body["topic"] = topic
    if not body:
        raise ValueError("바꿀 값이 없다")
    await zoom.update_meeting(meeting_id, body, occurrence_id=occurrence_id)
    return meeting_from_zoom(await zoom.get_meeting(meeting_id))


async def cancel_meeting(zoom: ZoomClient, meeting_id: str, *, occurrence_id: str | None) -> None:
    """occurrence_id=None이면 미팅 전체(반복이면 시리즈 전체)를 지운다. 실수로 시리즈를 지우지 않도록 인자를 꼭 적게 했다."""
    await zoom.delete_meeting(meeting_id, occurrence_id=occurrence_id)


# ---------- 유즈케이스 5: 호스트 시작 링크 ----------


async def get_start_url(zoom: ZoomClient, meeting_id: str) -> str:
    """교수자가 "시작"을 누를 때마다 새로 받는다. 2시간 만료 + 받은 사람은 누구나 호스트로 들어가므로 저장·로그 금지."""
    return (await zoom.get_meeting(meeting_id))["start_url"]


# ---------- 유즈케이스 6: 웹훅 수신 + 출석 집계 ----------


def _hmac_hex(secret: str, message: str) -> str:
    return hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()


def url_validation_response(secret_token: str, plain_token: str) -> dict[str, str]:
    """`endpoint.url_validation` 요청에 돌려줄 본문. 3초 안에 200으로 응답해야 한다(docs/zoom.md 9절)."""
    return {"plainToken": plain_token, "encryptedToken": _hmac_hex(secret_token, plain_token)}


def verify_signature(secret_token: str, timestamp: str, raw_body: bytes, signature: str) -> bool:
    """`x-zm-signature` 검증. 서명 대상은 JSON을 다시 직렬화한 것이 아니라 받은 그대로의 본문이다."""
    expected = "v0=" + _hmac_hex(secret_token, f"v0:{timestamp}:{raw_body.decode()}")
    return hmac.compare_digest(expected, signature)


@dataclass
class AttendanceEntry:
    student_id: str
    name: str  # 명단의 이름
    status: str  # "present" | "late" | "absent"
    attended_seconds: int = 0  # 겹치는 접속은 합쳐서 센 실제 체류 시간
    first_join: datetime | None = None
    display_names: list[str] = field(default_factory=list)  # Zoom에 입력한 표시 이름(명단 이름과 다르면 확인 필요)
    overlapping_sessions: bool = False  # 같은 학번으로 동시에 두 접속 → 기기 두 대 또는 대리 출석


@dataclass
class UnmatchedSession:
    user_name: str
    join_time: datetime
    leave_time: datetime | None


@dataclass
class AttendanceSummary:
    entries: list[AttendanceEntry]
    unmatched: list[UnmatchedSession]  # 학번을 못 찾았거나 명단에 없는 접속. 교수자가 직접 짝짓는다


def _sessions(events: list[dict], meeting_id: str) -> list[tuple[str, datetime, datetime | None]]:
    """접속(participant_uuid)마다 (표시 이름, 입장, 퇴장). 도착 순서가 바뀔 수 있어 이벤트 안의 시각만 쓴다.
    퇴장이 없으면 그 회차(uuid)의 meeting.ended 시각으로 닫고, 그것도 없으면 None으로 둔다."""
    ended: dict[str, datetime] = {}
    joins: dict[str, tuple[str, str, datetime]] = {}
    leaves: dict[str, datetime] = {}
    for e in events:
        obj = e.get("payload", {}).get("object", {})
        if str(obj.get("id")) != str(meeting_id):
            continue
        p = obj.get("participant", {})
        key = p.get("participant_uuid") or f"{obj.get('uuid')}:{p.get('user_id')}"
        if e["event"] == "meeting.ended":
            ended[obj["uuid"]] = datetime.fromisoformat(obj["end_time"].replace("Z", "+00:00"))
        elif e["event"] == "meeting.participant_joined":
            joins[key] = (p.get("user_name", ""), obj.get("uuid", ""), datetime.fromisoformat(p["join_time"].replace("Z", "+00:00")))
        elif e["event"] == "meeting.participant_left":
            leaves[key] = datetime.fromisoformat(p["leave_time"].replace("Z", "+00:00"))
    return [(name, start, leaves.get(key) or ended.get(uuid)) for key, (name, uuid, start) in joins.items()]


def _merged_seconds(intervals: list[tuple[datetime, datetime]]) -> tuple[int, bool]:
    """겹치는 구간을 합친 총 초, 겹침이 있었는지."""
    total, overlap, cur_start, cur_end = 0, False, None, None
    for start, end in sorted(intervals):
        if cur_end is not None and start < cur_end:
            overlap = True
            cur_end = max(cur_end, end)
            continue
        if cur_end is not None:
            total += int((cur_end - cur_start).total_seconds())
        cur_start, cur_end = start, end
    if cur_end is not None:
        total += int((cur_end - cur_start).total_seconds())
    return total, overlap


def summarize_attendance(
    events: list[dict],
    roster: dict[str, str],
    meeting_id: str,
    meeting_start: datetime,
    min_minutes: int,
    late_after_minutes: int,
    student_id_pattern: str = r"\d{8}",
) -> AttendanceSummary:
    """웹훅 participant_joined/left를 학생별 출석으로 바꾼다. roster = {학번: 이름}.
    학생은 표시 이름을 `학번 이름`으로 넣고 들어온다(개인 계정 학생은 이메일이 빈 값이라, docs/zoom.md 1절 6번).
    판정: 체류 ≥ min_minutes면 출석, 그중 첫 입장 > 시작 + late_after_minutes면 지각, 나머지는 결석."""
    by_student: dict[str, list[tuple[str, datetime, datetime | None]]] = {}
    unmatched: list[UnmatchedSession] = []
    for name, start, end in _sessions(events, meeting_id):
        m = re.search(student_id_pattern, name)
        if m and m.group(0) in roster:
            by_student.setdefault(m.group(0), []).append((name, start, end))
        else:
            unmatched.append(UnmatchedSession(name, start, end))

    late_after = meeting_start + timedelta(minutes=late_after_minutes)
    entries: list[AttendanceEntry] = []
    for sid, name in roster.items():
        sessions = by_student.get(sid, [])
        seconds, overlap = _merged_seconds([(s, e) for _, s, e in sessions if e is not None])
        first = min((s for _, s, _ in sessions), default=None)
        if not sessions or seconds < min_minutes * 60:
            status = "absent"
        else:
            status = "late" if first > late_after else "present"
        entries.append(AttendanceEntry(sid, name, status, seconds, first, sorted({n for n, _, _ in sessions}), overlap))
    return AttendanceSummary(entries, unmatched)
