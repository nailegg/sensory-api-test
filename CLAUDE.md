# synsory-api

Synsory 서비스가 나중에 붙일 SaaS API(Google Drive · Docs · Sheets · Slides · Forms, Zoom)를 서비스 레포와 별개로 먼저 검증하고 사용 방식을 문서화하는 FastAPI 테스트 프로젝트다. 여기서 만든 `client.py` · `mapper.py` · `scopes.py` · `usecases.py`와 `docs/<service>.md`는 다른 개발자가 구축 중인 서비스 레포로 그대로 옮겨진다. 코드는 "옮겨 쓸 수 있게" 쓴다.

## 확정된 전제

- 인증: OAuth 2.0 사용자 동의 방식. Google 서비스 계정, Zoom Server-to-Server는 쓰지 않는다.
- 테스트 계정: 개인 Google 계정, 개인 Zoom 계정. KAIST Workspace 계정은 쓰지 않는다.
- 스택: Python 3.12, uv, FastAPI, httpx. Google 공식 SDK(`google-api-python-client`)는 쓰지 않고 REST를 직접 호출한다. SDK가 확실히 유리한 경우만 `docs/<service>.md` 10절에 근거를 적고 예외로 쓴다.
- 상대 서비스 레포의 Python 버전·패키지 도구가 확인되면 위 스택을 거기에 맞춘다.
- 로컬 서버는 포트 8000. OAuth 리다이렉트 URI는 `http://localhost:8000/auth/google/callback`, `http://localhost:8000/auth/zoom/callback`. Zoom이 https를 요구하면 Zoom만 ngrok 주소를 쓴다(웹훅 때문에 ngrok은 어차피 필요). 1단계에서 확인해 `.env.example`에 반영한다.

## 이름 규칙

- `<service>` = 서비스 폴더 이름이다: `google_drive`, `google_docs`, `google_sheets`, `google_slides`, `google_forms`, `zoom`. `samples/<service>/`, `tests/<service>/`, `docs/<service>.md`에 모두 이 이름을 쓴다(예: `docs/google_docs.md`).
- URL prefix만 `/google/docs`, `/google/drive`, `/zoom`처럼 provider/서비스로 나눈다.

## 폴더 구조

```
app/
  main.py                 # FastAPI 앱 생성 + 라우터 등록만. 로직 없음
  core/
    config.py             # .env 로드 (pydantic-settings)
    oauth.py              # 공통 OAuth 흐름: authorize URL, /auth/<provider>/callback, refresh.
                          #   등록된 서비스들의 scopes.py를 모아 provider별 한 번의 인가 요청으로 보낸다
    token_store.py        # 토큰 저장 (테스트는 로컬 JSON 파일)
    models.py             # Synsory 공통 모델 (Document, Meeting …). 여기서만 정의
  services/<service>/
    router.py             # /<provider>/<service>/... 시나리오 단위 엔드포인트. 얇은 층, 옮기지 않음
    picker.py             # (google_drive만) Google Picker 테스트 HTML 페이지 GET /google/picker. 옮기지 않음
    usecases.py           # 여러 client를 엮는 흐름 (FastAPI 의존성 없음). 옮겨지는 파일
    client.py             # 이 서비스의 외부 API 호출만. 옮겨지는 파일
    mapper.py             # API 응답 dict → core/models 순수 변환. 옮겨지는 파일
    scopes.py             # 이 서비스가 쓰는 scope 목록 + 각 scope의 사용 이유. 옮겨지는 파일
samples/<service>/        # 실제 요청·응답 캡처 (JSON, 시나리오별)
docs/
  PLAN.md                 # 진행 절차, 서비스별 예외, 진행 현황
  <service>.md            # 서비스별 연동 스펙 문서 (아래 목차)
tests/<service>/          # pytest. 주 대상은 usecases.py와 mapper.py
.env                      # 시크릿. 커밋 금지
.env.example              # 키 이름만
.gitignore                # .env, samples/**/raw/, __pycache__, .venv
```

## 계층 규칙

- `router.py`: 요청 파싱, `token_store`에서 토큰 꺼내기, `usecases` 호출, 응답 반환. 이것 외의 로직을 두지 않는다. 서비스 레포로 옮기지 않는다.
- `usecases.py`: "문서 만들기 → 폴더로 옮기기 → Drive 메타데이터 조회 → `Document`로 변환"처럼 여러 client와 mapper를 엮는 흐름. 다른 서비스의 client(예: `google_drive.client`)를 import하는 곳은 여기뿐이다. FastAPI를 import하지 않는다.
- `client.py`: 자기 서비스의 외부 API만 부른다. 다른 서비스의 client를 import하지 않는다. FastAPI를 import하지 않는다.
- `mapper.py`: 응답 dict(들)를 받아 `core/models`로 바꾸는 순수 함수. 네트워크 호출도, client import도 하지 않는다. Drive 메타데이터가 필요하면 usecases가 두 응답을 받아 mapper에 넘긴다.
- `scopes.py`: scope 문자열 목록과 각각의 사용 이유. `core/oauth.py`가 이를 모아 인가 요청을 만든다. 서비스가 추가되어 scope가 늘면 사용자가 재동의해야 한다는 점을 `docs/<service>.md` 2절에 적는다.

## 규칙

- 라우터는 시나리오 단위로 만든다. `POST /google/docs/create-from-text`처럼 "서비스가 할 동작" 이름을 쓰고, 외부 API 엔드포인트를 그대로 따라 만들지 않는다.
- 호출이 성공하면 요청·응답을 `samples/<service>/<scenario>.json`에 저장한다. 저장 전에 토큰, 이메일, 개인 식별 정보를 마스킹한다.
- 시크릿은 `.env`에만 둔다. 코드, 샘플, 문서에 시크릿을 쓰지 않는다. 새 키를 추가하면 `.env.example`에도 이름을 추가한다.
- 공통 모델은 `core/models.py`에서만 정의하고, 서비스별 필드는 mapper에서 매핑한다. 서비스 폴더 안에 별도 모델을 만들지 않는다.
- 새 서비스는 기존 서비스 폴더(`google_docs`)를 복사해서 시작한다. 등록은 두 줄이다: `main.py`에 `include_router`, `core/oauth.py`의 `REGISTERED_SCOPE_MODULES`에 그 서비스의 `scopes` 모듈. 후자를 빠뜨리면 scope가 인가 요청에 들어가지 않는다.
- Drive API 호출(파일 메타데이터 `files.get`, 폴더 지정, 목록·검색·삭제·공유, `files.export`, `changes.watch`)은 전부 `services/google_drive/client.py`에 둔다. Docs·Sheets·Slides·Forms 폴더 안에 Drive 호출을 넣지 않는다.
- `Document` 공통 모델의 `owner` · `created_at` · `modified_at` · `url`은 Drive `files.get`에서 온다. 각 서비스의 usecases가 자기 API 응답과 Drive 메타데이터를 함께 mapper에 넘긴다.
- Docs·Sheets·Slides·Forms를 앱이 직접 만드는 시나리오는 `drive.file` scope만으로 될 수 있다. 그 경우 해당 서비스의 `scopes.py`는 비거나 짧고, 인가는 Drive scope로 이루어진다. 정확한 동작은 각 서비스 1단계에서 공식 문서로 확인한다.
- 서비스별 제약·함정(쿼터, 토큰 만료, 플랜 제한, 웹훅 방식)은 코드를 만지기 전에 `docs/<service>.md`의 8절·10절을 먼저 본다. 스펙 문서가 아직 없으면 `docs/PLAN.md`의 "서비스별 예외·특이사항" 표를 본다.

## 실행

```
uv sync                                   # 의존성 (Python 3.12, uv 필요)
cp .env.example .env                      # GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET 채우기 (콘솔 설정은 docs/google_docs.md 2절)
uv run uvicorn app.main:app --port 8000 --reload
```

브라우저에서 `http://localhost:8000/auth/google/login`으로 로그인하면 토큰이 `.tokens/tokens.json`에 저장된다. `http://localhost:8000/docs`(Swagger)에서 엔드포인트를 눌러볼 수 있다. 테스트는 `uv run pytest`. 실측 때 만든 파일은 `POST /google/drive/move-to-trash/{id}`로 정리한다.

## 진행 절차

서비스 하나당 `docs/PLAN.md`의 1~7단계(API 탐색 → 유즈케이스 → 인증 → 환경 → 기능 테스트 → 스펙 문서 → 핸드오프)를 순서대로 밟는다. 단계 설명, 서비스별 예외, 현재 진행 상황은 모두 `docs/PLAN.md`에 있다. 어떤 서비스의 어느 단계 작업을 시작할 때는 그 문서에서 해당 단계와 그 서비스의 예외 행을 먼저 읽는다. 단계를 마치면 "진행 현황" 표를 갱신한다. 2단계 유즈케이스는 상현이 직접 정한다.

## 서비스별 연동 스펙 문서 목차 (`docs/<service>.md`)

1. 이 서비스로 하는 일 (유즈케이스)
2. 인증
3. scope 표
4. 엔드포인트 표
5. 요청·응답 샘플
6. 공통 모델 매핑
7. 에러와 예외 케이스
8. 쿼터 · rate limit · 플랜 제약
9. 웹훅 (해당 시)
10. 함정과 권장 패턴
11. 샘플 코드 (`usecases.py`의 흐름을 기준으로)
12. 미확인 · 보류 항목

목차 번호와 제목을 바꾸지 않는다. 서비스 간에 같은 위치에서 같은 정보를 찾을 수 있어야 한다.
