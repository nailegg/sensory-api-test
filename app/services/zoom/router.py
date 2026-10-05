"""/zoom/... 엔드포인트. 얇은 층, 옮기지 않는다."""

import json
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response

from app.core.config import Settings, get_settings
from app.services.zoom import usecases

router = APIRouter(prefix="/zoom", tags=["zoom"])

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
