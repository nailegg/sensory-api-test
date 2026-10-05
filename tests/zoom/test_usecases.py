import hashlib
import hmac
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.services.zoom import usecases
from app.services.zoom.client import ZoomApiError
from app.services.zoom.usecases import url_validation_response, verify_signature

SECRET = "test-secret"


def test_url_validation_response_is_hmac_of_plain_token():
    res = url_validation_response(SECRET, "abc")
    assert res["plainToken"] == "abc"
    assert res["encryptedToken"] == hmac.new(b"test-secret", b"abc", hashlib.sha256).hexdigest()


def test_verify_signature():
    body = b'{"event":"meeting.participant_joined","payload":{}}'
    sig = "v0=" + hmac.new(b"test-secret", b"v0:1700000000:" + body, hashlib.sha256).hexdigest()
    assert verify_signature(SECRET, "1700000000", body, sig)
    assert not verify_signature(SECRET, "1700000001", body, sig)  # 타임스탬프가 다르면 실패
    assert not verify_signature(SECRET, "1700000000", body + b" ", sig)  # 본문이 1바이트라도 다르면 실패
    assert not verify_signature("other", "1700000000", body, sig)


# ---------- 유즈케이스 1~5 ----------

KST = ZoneInfo("Asia/Seoul")


class FakeZoom:
    """ZoomClient 흉내. 받은 요청을 기록하고 최소한의 응답을 돌려준다."""

    def __init__(self, fail_topic: str | None = None):
        self.calls: list[tuple] = []
        self.fail_topic = fail_topic

    async def get_me(self):
        return {"type": 1, "timezone": "Asia/Seoul"}

    async def create_meeting(self, body):
        self.calls.append(("create", body))
        if body["topic"] == self.fail_topic:
            raise ZoomApiError(429, {"code": None, "message": "daily limit"})
        return {"id": len(self.calls), "topic": body["topic"], "status": "waiting", "join_url": f"https://zoom.us/j/{len(self.calls)}"}

    async def get_meeting(self, meeting_id, occurrence_id=None):
        self.calls.append(("get", meeting_id))
        return {"id": meeting_id, "topic": "바뀐 주제", "status": "waiting", "start_url": "https://zoom.us/s/secret"}

    async def update_meeting(self, meeting_id, body, occurrence_id=None):
        self.calls.append(("patch", meeting_id, body, occurrence_id))

    async def delete_meeting(self, meeting_id, occurrence_id=None):
        self.calls.append(("delete", meeting_id, occurrence_id))


async def test_host_profile_basic_has_40_minute_limit():
    p = await usecases.get_host_profile(FakeZoom())
    assert p.plan_type == 1 and p.has_40_minute_limit and p.timezone == "Asia/Seoul"


async def test_create_group_meetings_renders_topic_converts_time_and_continues_on_error():
    zoom = FakeZoom(fail_topic="과제1 - B조")
    res = await usecases.create_group_meetings(
        zoom, ["A조", "B조", "C조"], "{{activity_name}} - {{team_name}}", datetime(2026, 10, 10, 14, 0, tzinfo=KST), 40, "Asia/Seoul", "과제1"
    )
    assert [r.team_name for r in res] == ["A조", "B조", "C조"]
    assert res[0].meeting.topic == "과제1 - A조" and res[1].meeting is None and "429" in res[1].error and res[2].meeting
    body = zoom.calls[0][1]
    assert body["start_time"] == "2026-10-10T05:00:00Z" and body["type"] == 2 and "settings" not in body


async def test_naive_start_time_is_rejected():
    with pytest.raises(ValueError):
        await usecases.create_group_meetings(FakeZoom(), ["A조"], "{{team_name}}", datetime(2026, 10, 10, 14, 0), 40, "Asia/Seoul")


async def test_create_breakout_meeting_body():
    zoom = FakeZoom()
    await usecases.create_breakout_meeting(
        zoom, "과제1", datetime(2026, 10, 10, 14, 0, tzinfo=KST), 40, "Asia/Seoul", {"A조": ["a@x.com"]}, settings={"waiting_room": True}
    )
    s = zoom.calls[0][1]["settings"]
    assert s["waiting_room"] is True
    assert s["breakout_room"] == {"enable": True, "rooms": [{"name": "A조", "participants": ["a@x.com"]}]}


async def test_create_recurring_meeting_body_and_end_validation():
    zoom = FakeZoom()
    await usecases.create_recurring_meeting(zoom, "수업", datetime(2026, 10, 12, 14, 0, tzinfo=KST), 40, "Asia/Seoul", [2, 4], end_times=8)
    body = zoom.calls[0][1]
    assert body["type"] == 8 and body["recurrence"] == {"type": 2, "repeat_interval": 1, "weekly_days": "2,4", "end_times": 8}
    with pytest.raises(ValueError):
        await usecases.create_recurring_meeting(zoom, "수업", datetime(2026, 10, 12, 14, 0, tzinfo=KST), 40, "Asia/Seoul", [2])


async def test_reschedule_sends_only_given_fields_then_reads_back():
    zoom = FakeZoom()
    m = await usecases.reschedule_meeting(zoom, "9", duration_minutes=30, occurrence_id="o1")
    assert zoom.calls[0] == ("patch", "9", {"duration": 30}, "o1")
    assert zoom.calls[1] == ("get", "9") and m.topic == "바뀐 주제"
    with pytest.raises(ValueError):
        await usecases.reschedule_meeting(zoom, "9")


async def test_cancel_and_start_url():
    zoom = FakeZoom()
    await usecases.cancel_meeting(zoom, "9", occurrence_id=None)
    assert zoom.calls[-1] == ("delete", "9", None)
    assert await usecases.get_start_url(zoom, "9") == "https://zoom.us/s/secret"


# ---------- 유즈케이스 6: 출석 집계 ----------

START = datetime(2026, 10, 12, 5, 0, tzinfo=ZoneInfo("UTC"))


def _ev(event, uuid="u1", meeting_id=111, name=None, puid=None, join=None, leave=None, end=None):
    obj = {"id": meeting_id, "uuid": uuid}
    if end:
        obj["end_time"] = end
    if name is not None:
        obj["participant"] = {"user_name": name, "participant_uuid": puid, "user_id": puid, "email": "", "participant_user_id": ""}
        if join:
            obj["participant"]["join_time"] = join
        if leave:
            obj["participant"]["leave_time"] = leave
    return {"event": event, "payload": {"object": obj}}


ROSTER = {"20231234": "홍길동", "20235678": "김철수", "20239999": "이영희"}


def test_summarize_attendance_rules():
    events = [
        # 홍길동: 정시 입장 → 나갔다 재입장, 두 번째 접속 중 기기 하나 더(겹침). 총 체류 = 05:00~05:20 + 05:25~05:40 = 35분
        _ev("meeting.participant_joined", name="20231234 홍길동", puid="a1", join="2026-10-12T05:00:00Z"),
        _ev("meeting.participant_left", name="20231234 홍길동", puid="a1", leave="2026-10-12T05:20:00Z"),
        _ev("meeting.participant_joined", name="20231234 홍길동", puid="a2", join="2026-10-12T05:25:00Z"),
        _ev("meeting.participant_joined", name="20231234 길동폰", puid="a3", join="2026-10-12T05:30:00Z"),
        _ev("meeting.participant_left", name="20231234 길동폰", puid="a3", leave="2026-10-12T05:35:00Z"),
        _ev("meeting.participant_left", name="20231234 홍길동", puid="a2", leave="2026-10-12T05:40:00Z"),
        # 김철수: 15분 늦게 입장, 퇴장 기록 없음 → 회차 종료 05:40에서 닫힘 = 25분. 도착 순서가 뒤바뀌어도 된다
        _ev("meeting.ended", end="2026-10-12T05:40:00Z"),
        _ev("meeting.participant_joined", name="김철수 20235678", puid="b1", join="2026-10-12T05:15:00Z"),
        # 명단에 없는 학번, 학번 없는 이름 → 미확인
        _ev("meeting.participant_joined", name="20230000 청강생", puid="c1", join="2026-10-12T05:01:00Z"),
        _ev("meeting.participant_joined", name="iPhone", puid="d1", join="2026-10-12T05:02:00Z"),
        # 다른 미팅 이벤트는 무시
        _ev("meeting.participant_joined", meeting_id=222, name="20239999 이영희", puid="e1", join="2026-10-12T05:00:00Z"),
    ]
    res = usecases.summarize_attendance(events, ROSTER, "111", START, min_minutes=20, late_after_minutes=10)
    by = {e.student_id: e for e in res.entries}
    assert by["20231234"].status == "present" and by["20231234"].attended_seconds == 35 * 60
    assert by["20231234"].overlapping_sessions and by["20231234"].display_names == ["20231234 길동폰", "20231234 홍길동"]
    assert by["20235678"].status == "late" and by["20235678"].attended_seconds == 25 * 60
    assert by["20239999"].status == "absent" and by["20239999"].attended_seconds == 0
    assert sorted(u.user_name for u in res.unmatched) == ["20230000 청강생", "iPhone"]
    assert all(u.leave_time.isoformat() == "2026-10-12T05:40:00+00:00" for u in res.unmatched)  # 퇴장 없으면 종료 시각


def test_summarize_attendance_short_stay_is_absent_even_if_on_time():
    events = [
        _ev("meeting.participant_joined", name="20231234 홍길동", puid="a1", join="2026-10-12T05:00:00Z"),
        _ev("meeting.participant_left", name="20231234 홍길동", puid="a1", leave="2026-10-12T05:05:00Z"),
    ]
    res = usecases.summarize_attendance(events, {"20231234": "홍길동"}, "111", START, min_minutes=20, late_after_minutes=10)
    assert res.entries[0].status == "absent" and res.entries[0].attended_seconds == 300
