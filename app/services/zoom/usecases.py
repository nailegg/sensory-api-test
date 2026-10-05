"""Zoom 시나리오 흐름. FastAPI를 import하지 않는다.

유즈케이스(docs/zoom.md 1절, 2026-10-05 확정): 1 플랜 확인 · 2 그룹별 미팅 예약 · 3 정기 회의 · 4 일정 변경·취소 ·
5 호스트 시작 링크 · 6 출석 자동 집계(웹훅 participant_joined/left + 표시 이름의 학번 매칭).
지금은 6번의 웹훅 수신에 필요한 순수 함수만 있다. 나머지는 5단계에서 구현한다.
"""

import hashlib
import hmac


def _hmac_hex(secret: str, message: str) -> str:
    return hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()


def url_validation_response(secret_token: str, plain_token: str) -> dict[str, str]:
    """`endpoint.url_validation` 요청에 돌려줄 본문. 3초 안에 200으로 응답해야 한다(docs/zoom.md 9절)."""
    return {"plainToken": plain_token, "encryptedToken": _hmac_hex(secret_token, plain_token)}


def verify_signature(secret_token: str, timestamp: str, raw_body: bytes, signature: str) -> bool:
    """`x-zm-signature` 검증. 서명 대상은 JSON을 다시 직렬화한 것이 아니라 받은 그대로의 본문이다."""
    expected = "v0=" + _hmac_hex(secret_token, f"v0:{timestamp}:{raw_body.decode()}")
    return hmac.compare_digest(expected, signature)
