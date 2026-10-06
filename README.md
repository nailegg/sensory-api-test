# synsory-api

Synsory가 나중에 붙일 SaaS API(Google Drive · Docs · Sheets · Slides · Forms · Meet, Zoom)를 서비스 레포와 별개로 먼저 검증하고, 사용 방식을 문서로 확정하는 FastAPI 테스트 프로젝트다.

여기서 만든 `client.py` · `mapper.py` · `scopes.py` · `usecases.py`와 `docs/<service>.md`는 서비스 레포로 그대로 옮겨진다. 라우터는 실측용이라 옮기지 않는다.

- 인증: OAuth 2.0 사용자 동의 방식(Google 서비스 계정, Zoom Server-to-Server는 쓰지 않음)
- 테스트 계정: 개인 Google 계정, 개인 Zoom 무료(Basic) 계정
- 스택: Python 3.12, uv, FastAPI, httpx. Google 공식 SDK 없이 REST 직접 호출

## 진행 현황 (2026-10-06 기준)

서비스마다 [docs/PLAN.md](docs/PLAN.md)의 1~7단계(API 탐색 → 유즈케이스 → 인증 → 환경 → 기능 테스트 → 스펙 문서 → 핸드오프)를 밟는다.

| 서비스 | 단계 | 유즈케이스 | 스펙 문서 |
| --- | --- | --- | --- |
| Google Drive | 6 완료 (공통 레이어) | 폴더·메타데이터·공유·마감·내보내기·Picker 템플릿 복사 | [google_drive.md](docs/google_drive.md) |
| Google Docs | 6 완료 → 7 대기 | 4개: 폴더 생성, 그룹별 문서 생성·공유, 마감(권한 낮추기), 내보내기 | [google_docs.md](docs/google_docs.md) |
| Google Sheets | 6 완료 → 7 대기 | 5개: Docs와 같은 4개 + 마감 후 값 읽기 | [google_sheets.md](docs/google_sheets.md) |
| Google Slides | 6 완료 → 7 대기 | 4개: Docs와 같은 4개(pptx 템플릿 변환 + 복사 + 치환) | [google_slides.md](docs/google_slides.md) |
| Google Forms | 6 완료 → 7 대기 | 13개: 설문·퀴즈·조별 동료평가 생성, 응답자 제한, 제출 현황, 마감·재개, 응답 집계·점수·내보내기 | [google_forms.md](docs/google_forms.md) |
| Zoom | 6 완료 → 7 대기 | 6개: 플랜 확인, 그룹별 미팅, 정기 회의, 변경·취소, 시작 링크, 출석 집계(웹훅) | [zoom.md](docs/zoom.md) |
| Google Meet | 2 유즈케이스 초안 | 4개 초안: 그룹별 링크, 명단 잠금, 출석 집계, 링크 회수. 개인 Gmail에서 API 동작 여부는 3단계 첫 확인 | [google_meet.md](docs/google_meet.md) |
| Google Calendar | 1 탐색 후 보류 | Meet 단독 사용으로 결정해 보류 | [google_calendar.md](docs/google_calendar.md) |

- 테스트: `uv run pytest` 90개 통과
- 실측 샘플: `samples/<service>/*.json` (토큰·이메일 마스킹)
- 7단계 핸드오프(상대 개발자가 문서 2절·11절만 보고 재현)는 아직 진행 전이다.
- 한눈에 보는 요약: [docs/verification-overview.html](docs/verification-overview.html)

## 실행

```bash
uv sync
```

```bash
cp .env.example .env
```

`.env`에 채울 값:

- Google: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` (콘솔 설정은 [docs/google_docs.md](docs/google_docs.md) 2절). Picker를 쓰면 `GOOGLE_PICKER_API_KEY`, `GOOGLE_PROJECT_NUMBER` ([docs/google_drive.md](docs/google_drive.md) 2.1절)
- Zoom: `ZOOM_CLIENT_ID`, `ZOOM_CLIENT_SECRET`, `ZOOM_PUBLIC_BASE_URL`(ngrok https 주소), `ZOOM_WEBHOOK_SECRET_TOKEN` ([docs/zoom.md](docs/zoom.md) 2절·9절)

```bash
uv run uvicorn app.main:app --port 8000 --reload
```

1. `http://localhost:8000/auth/google/login` 또는 `${ZOOM_PUBLIC_BASE_URL}/auth/zoom/login`으로 로그인하면 토큰이 `.tokens/tokens.json`에 저장된다.
2. `http://localhost:8000/docs`(Swagger)에서 시나리오 엔드포인트를 호출한다.
3. 실측 때 만든 Google 파일은 `POST /google/drive/move-to-trash/{id}`로 정리한다.

Zoom은 리다이렉트 URI와 웹훅 수신 URL 모두 https가 필요해 ngrok 고정 도메인 하나로 받는다.

## 엔드포인트 개요

| prefix | 내용 |
| --- | --- |
| `/auth/{google,zoom}` | `login` · `callback` · `status` · `refresh` · `scopes` |
| `/google/drive` | 폴더 생성, 메타데이터, 앱 파일 목록, 휴지통 |
| `/google/picker` | Picker 테스트 페이지 |
| `/google/docs` · `/google/sheets` · `/google/slides` | 그룹별 파일 생성, 마감·복구, 권한 조회, 내보내기 (Sheets는 값 쓰기·읽기, 범위 잠금 추가) |
| `/google/forms` | 폼 생성·복사·게시, 응답자 제한, 마감·재개, 제출 현황, 응답·요약·퀴즈 점수·동료평가, 파일·시트 내보내기 |
| `/zoom` | 호스트 정보, 그룹별·소회의실·반복 미팅, 변경·취소, 시작 링크, 출석 집계, 웹훅 |

엔드포인트는 외부 API가 아니라 "Synsory가 할 동작" 단위로 만든다. 각 서비스의 외부 API 호출 목록은 스펙 문서 4절에 있다.

## 구조

```
app/
  main.py                  # 라우터 등록만
  core/                    # config, oauth(공통 인가), token_store, models(공통 모델)
  services/<service>/
    router.py              # 얇은 층. 옮기지 않음
    usecases.py            # 여러 client·mapper를 엮는 흐름     ┐
    client.py              # 이 서비스의 외부 API 호출만        │ 서비스 레포로
    mapper.py              # 응답 dict → core/models 순수 변환  │ 옮기는 파일
    scopes.py              # scope 목록과 사용 이유             ┘
samples/<service>/         # 실측 요청·응답
docs/                      # PLAN.md, 서비스별 스펙 문서
tests/<service>/           # usecases·mapper 테스트
```

계층 규칙, 이름 규칙, 새 서비스 추가 방법은 [CLAUDE.md](CLAUDE.md)에 있다.

## 스펙 문서 읽는 법

`docs/<service>.md`는 모두 같은 12절 목차를 쓴다. 연동을 시작할 때는 2절(인증), 8절(쿼터·플랜 제약), 10절(함정과 권장 패턴), 11절(샘플 코드)을 먼저 본다.

1. 유즈케이스 · 2. 인증 · 3. scope 표 · 4. 엔드포인트 표 · 5. 요청·응답 샘플 · 6. 공통 모델 매핑 · 7. 에러와 예외 케이스 · 8. 쿼터 · rate limit · 플랜 제약 · 9. 웹훅 · 10. 함정과 권장 패턴 · 11. 샘플 코드 · 12. 미확인 · 보류 항목

## 핸드오프 때 알릴 것

- Google은 Docs·Sheets·Slides·Forms 모두 `drive.file` scope 하나로 동작한다. Meet을 붙이면 민감 scope(`meetings.space.created`)가 추가되어 앱 검증 대상이 되고 기존 사용자 전원이 재동의해야 한다.
- OAuth 동의 화면이 "테스트" 상태면 Google refresh token은 7일 뒤 만료된다. 오류가 아니다.
- Google Docs·Drive API는 현재 무료지만 공식 문서에 한도 초과분 과금 계획이 적혀 있다.
- Zoom 앱은 미공개 상태라 개발자 계정 사용자만 인가할 수 있다. 다른 계정에 열려면 공유 요청 또는 게시 심사가 필요하다.
- 상대 레포의 Python 버전·패키지 도구는 아직 확인 전이다. 확인되면 스택을 거기에 맞춘다.

열린 질문 전체는 [docs/PLAN.md](docs/PLAN.md) "열린 질문" 절에 있다.
