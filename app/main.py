"""FastAPI 앱 생성 + 라우터 등록만. 로직 없음."""

from fastapi import FastAPI

from app.core import oauth
from app.services.google_docs import router as google_docs
from app.services.google_drive import picker as google_picker
from app.services.google_drive import router as google_drive
from app.services.google_sheets import router as google_sheets
from app.services.google_slides import router as google_slides
from app.services.zoom import router as zoom

app = FastAPI(title="synsory-api", description="Synsory SaaS API 검증용 테스트 서버")

app.include_router(oauth.router)
app.include_router(google_drive.router)
app.include_router(google_picker.router)  # Picker 테스트 페이지(GET /google/picker). 옮기지 않음
app.include_router(google_docs.router)
app.include_router(google_slides.router)
app.include_router(google_sheets.router)
app.include_router(zoom.router)
