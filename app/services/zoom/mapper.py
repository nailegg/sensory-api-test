"""Zoom 응답 dict → core/models 순수 변환."""

from datetime import datetime

from app.core.models import Meeting, MeetingOccurrence, MeetingStatus

# Zoom `status`에는 ended가 없다. 종료는 웹훅으로만 안다(docs/zoom.md 10절 7항).
_STATUS = {"waiting": MeetingStatus.SCHEDULED, "started": MeetingStatus.STARTED}


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def meeting_from_zoom(m: dict) -> Meeting:
    """`POST /users/me/meetings` · `GET /meetings/{id}` 응답 → Meeting."""
    return Meeting(
        id=str(m["id"]),
        topic=m.get("topic", ""),
        status=_STATUS.get(m.get("status", ""), MeetingStatus.UNKNOWN),
        start_time=_dt(m.get("start_time")),
        duration_minutes=m.get("duration"),
        timezone=m.get("timezone"),
        join_url=m.get("join_url"),
        host_id=m.get("host_id"),
        uuid=m.get("uuid"),
        occurrences=[
            MeetingOccurrence(
                id=str(o["occurrence_id"]),
                start_time=_dt(o.get("start_time")),
                duration_minutes=o.get("duration"),
                deleted=o.get("status") == "deleted",
            )
            for o in m.get("occurrences", [])
        ],
    )
