from app.core.models import MeetingStatus
from app.services.zoom.mapper import meeting_from_zoom

SCHEDULED = {
    "id": 81234567890,
    "uuid": "abc/def==",
    "host_id": "h1",
    "topic": "과제1 - A조",
    "type": 2,
    "status": "waiting",
    "start_time": "2026-10-10T05:00:00Z",
    "duration": 40,
    "timezone": "Asia/Seoul",
    "join_url": "https://zoom.us/j/81234567890",
    "start_url": "https://zoom.us/s/secret",
}


def test_meeting_from_zoom_scheduled():
    m = meeting_from_zoom(SCHEDULED)
    assert m.id == "81234567890"  # int64 → str
    assert m.status == MeetingStatus.SCHEDULED
    assert m.start_time.isoformat() == "2026-10-10T05:00:00+00:00"
    assert m.duration_minutes == 40 and m.timezone == "Asia/Seoul" and m.uuid == "abc/def=="
    assert "start_url" not in m.model_dump()  # 호스트 권한 링크는 모델에 넣지 않는다


def test_meeting_from_zoom_recurring_and_unknown_status():
    m = meeting_from_zoom(
        {
            "id": 1,
            "topic": "수업",
            "status": "ended?",
            "occurrences": [
                {"occurrence_id": 1791000000000, "start_time": "2026-10-12T05:00:00Z", "duration": 40, "status": "available"},
                {"occurrence_id": 1791600000000, "start_time": "2026-10-19T05:00:00Z", "duration": 40, "status": "deleted"},
            ],
        }
    )
    assert m.status == MeetingStatus.UNKNOWN
    assert [o.id for o in m.occurrences] == ["1791000000000", "1791600000000"]
    assert [o.deleted for o in m.occurrences] == [False, True]
