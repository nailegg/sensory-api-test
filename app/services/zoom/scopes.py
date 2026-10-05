"""Zoom scope 목록과 사용 이유. docs/zoom.md 3절.

Zoom은 scope를 인가 URL이 아니라 Marketplace 앱 설정(Scopes 화면)에서 정한다.
여기 적은 이유는 그 화면의 설명 칸과 심사 자료에 그대로 쓴다. 토큰 응답의 `scope`와 대조하는 기준이기도 하다.
1절 유즈케이스 1~6(무료 계정 범위)에 필요한 것만 둔다. 추가하면 사용자가 재인가해야 한다.
"""

PROVIDER = "zoom"

SCOPES: dict[str, str] = {
    "user:read:user": "교수자 본인의 플랜 유형(무료면 40분 제한 경고)과 시간대를 확인한다. GET /users/me",
    "meeting:write:meeting": "그룹별 미팅과 매주 반복 수업 미팅을 교수자 계정에 예약한다. POST /users/me/meetings",
    "meeting:read:meeting": "예약한 미팅의 참가 링크·일정을 다시 읽고, 교수자가 시작을 누를 때 호스트 시작 링크를 받는다. GET /meetings/{id}",
    "meeting:update:meeting": "예약한 미팅(또는 반복 미팅의 한 회차)의 일정·설정을 바꾼다. PATCH /meetings/{id}",
    "meeting:delete:meeting": "취소된 미팅(또는 반복 미팅의 한 회차)을 지운다. DELETE /meetings/{id}",
    "meeting:read:participant": (
        "출석 집계: 교수자 미팅의 참가자 입장·퇴장 이벤트(meeting.participant_joined/left)를 웹훅으로 받는다. "
        "표시 이름의 학번으로 수강생과 맞춘다"
    ),
}
