# Synsory API 검증 진행 계획

작성일: 2026-09-30 · 작성자: 상현
살아있는 버전(코멘트·진행 현황 편집용): https://claude.ai/code/artifact/b956b711-3acf-44a8-8c73-385f43cd5e0e

## 전제와 목적

Synsory가 나중에 붙일 SaaS API(Google Docs · Sheets · Slides · Forms, Zoom)를 서비스 레포와 별개로 먼저 검증하고, 사용 방식을 문서로 확정하는 것이 이 작업의 목표다. 서비스 레포는 다른 개발자가 독립적으로 구축 중이므로, 여기서 나오는 산출물은 그 레포에 그대로 옮겨 쓸 수 있는 형태여야 한다.

확정된 전제:

- 인증은 OAuth 2.0 사용자 동의 방식이 기본이다. 서비스 이용자가 자기 Google/Zoom 계정을 연결하는 구조를 가정한다.
- 테스트 계정은 개인 Google 계정과 개인 Zoom 계정을 쓴다. KAIST Workspace 계정은 관리자 정책으로 외부 앱이 막힐 수 있어 쓰지 않는다.
- 기능 테스트는 FastAPI 프로젝트 하나에서 진행한다. 서비스별로 라우터를 나누고, 인증·설정·공통 모델은 공유한다.
- 아래 공통 단계를 서비스마다 한 바퀴씩 돈다. 서비스 특성상 건너뛰거나 바꿔야 하는 단계는 "서비스별 예외" 절에 적고, 적히지 않은 것은 공통 단계를 따른다.
- 유즈케이스는 API가 실제로 무엇을 할 수 있는지 훑어본 뒤에 확정한다. 그래서 API 탐색이 1단계, 유즈케이스 확정이 2단계다. 2단계는 상현이 직접 정한다.

## 공통 진행 단계

서비스 하나당 아래 1~7단계를 순서대로 밟는다. 각 단계는 "끝나면 남는 것"이 생겨야 다음으로 넘어간다.

1. **API 탐색** — 공식 문서를 훑어 이 API가 실제로 할 수 있는 일과 못 하는 일을 파악한다. 리소스 종류(문서, 시트, 미팅 등)와 대표 엔드포인트, 요금·플랜 제약, 웹훅 유무를 A4 한 장 분량으로 적는다. 결과: 서비스별 "할 수 있는 일 목록"과 "눈에 띄는 제약".
2. **유즈케이스 확정** — 1단계 결과를 보고 Synsory가 이 서비스로 할 동작을 3~10개 문장으로 적는다(예: "미팅이 끝나면 트랜스크립트를 가져온다"). 각 문장 옆에 필요한 엔드포인트를 붙인다. 결과: 시나리오 목록 = 5단계에서 테스트할 범위.
3. **인증·권한 설계** — OAuth 앱을 콘솔에 등록하고(리다이렉트 URI 기본값은 `CLAUDE.md`), 시나리오별 최소 scope를 골라 `scopes.py`에 사용 이유와 함께 적는다. `core/oauth.py`가 각 서비스의 `scopes.py`를 모아 provider별 한 번의 인가 요청으로 보내므로, 로그인 → 토큰 발급 → 만료 후 refresh까지 FastAPI에서 한 번 실제로 돌린다. 결과: 동작하는 인증 라우터, scope 표.
4. **테스트 환경 준비** — 개인 계정에 테스트용 문서·미팅을 만들고, 시크릿은 `.env`에만 둔다. 계정 플랜(무료/유료)을 기록한다. 결과: 실험용 자원 목록, 시크릿 관리 규칙.
5. **기능 테스트** — 시나리오별 흐름을 `usecases.py`에 구현하고 라우터는 그것을 부르기만 하게 한다. 실제 요청·응답을 파일로 저장한다. 그다음 실패 케이스(권한 없음, 삭제된 자원, 큰 파일, 빈 값)를 일부러 만들어 에러 형태를 기록한다. 쿼터·rate limit을 문서에서 확인하고, 필요하면 웹훅을 받아본다. 결과: 라우터 코드, 요청·응답 샘플, 에러 목록, 쿼터 표.
6. **연동 스펙 문서화** — 5단계 결과를 "산출물 템플릿" 목차대로 정리한다. 응답을 Synsory 공통 모델로 어떻게 매핑하는지 적는다. 결과: 서비스별 연동 스펙 문서 1부.
7. **핸드오프·검증** — 상대 개발자가 문서만 보고 처음부터 재현해본다. 빠진 설정(API 활성화, 리다이렉트 URI 등)을 문서에 보충한다. 옮기는 파일은 `client.py` · `mapper.py` · `scopes.py` · `usecases.py`와 `docs/<service>.md`로 고정하고, 라우터는 옮기지 않는다. `usecases.py`와 `mapper.py`를 pytest로 남겨 회귀 확인에 쓴다. 결과: 재현 확인된 문서, 테스트 코드.

1~2단계와 3~4단계는 서비스마다 며칠이면 끝난다. 시간은 대부분 5~6단계에 들어간다. 여러 서비스를 병렬로 하기보다 한 서비스를 6단계까지 끝내 문서 형식을 굳힌 뒤 다음 서비스로 가는 편이 빠르다. Google 4종은 3단계(인증)를 공유하므로, Docs를 먼저 끝내면 나머지 세 개는 3단계를 건너뛴다.

## FastAPI 테스트 프로젝트 구조

프로젝트 구조와 운영 규칙은 레포 루트의 `CLAUDE.md`에 있다. 이 문서는 절차와 배경만 다룬다.

## 서비스별 예외·특이사항

공통 단계를 따르되, 아래 표의 항목만 다르게 한다. 표에 없는 것은 공통 단계 그대로다. 진행하며 새로 발견한 예외는 이 표에 행을 추가하고, 해당 서비스의 `docs/<service>.md` 8절·10절로 옮긴다.

| 서비스 | 달라지는 단계 | 내용 |
| --- | --- | --- |
| Google 공통 | 3 인증 | GCP 프로젝트 하나, OAuth 동의 화면 하나를 4종이 공유한다. Docs에서 한 번 구축하면 Sheets/Slides/Forms는 3단계를 건너뛰고 scope만 추가한다. 동의 화면은 "테스트" 상태로 두고 개인 계정을 테스트 사용자로 등록한다. |
| Google 공통 | 3 인증 | refresh token은 첫 동의 때만 발급된다. 인가 URL에 `access_type=offline&prompt=consent`를 반드시 붙이고, 테스트 상태 앱의 refresh token은 7일 후 만료되므로 재로그인이 필요한 것을 오류로 착각하지 않는다(7일 만료는 "외부 사용자 유형 + 테스트 상태" 조건으로 공식 문서 확인, 2026-09-30). refresh token은 계정 × 클라이언트 ID당 100개까지이고 초과하면 가장 오래된 것이 조용히 무효가 되므로, `prompt=consent`로 로그인을 반복해도 token_store에는 최신 것 하나만 둔다. |
| Google 공통 | 3 인증 | 파일 목록·검색·삭제·공유는 Docs/Sheets/Slides API가 아니라 Drive API다. Drive는 `drive` 대신 `drive.file`(앱이 만들거나 사용자가 선택한 파일만) scope를 기본으로 한다. `drive`는 제한 scope라 나중에 CASA 보안 평가가 따라온다. 기존 파일 접근이 시나리오에 필요하면 Google Picker로 사용자가 고르게 하는 방안을 같이 검토한다. 실측(2026-10-02): `drive.file`로도 사용자 폴더 ID만 알면 그 안에 생성·이동은 된다. 안 되는 것은 그 폴더·파일의 조회뿐이다(`docs/google_drive.md` 10절). **Picker 탐색 완료(2026-10-04, `docs/google_drive.md` 2.1절)**: 교수자가 Drive에 이미 가진 Docs·Slides·Sheets를 템플릿으로 쓰는 경로는 Picker(API 키 + `setAppId`=프로젝트 번호 + `drive.file` 토큰 + 로그인된 브라우저)로 scope 추가 없이 가능. 테스트 페이지 `GET /google/picker`. 콘솔에 Google Picker API 사용 설정·API 키가 추가로 필요. |
| Google 공통 | 8 쿼터 | Docs API는 요청 수(쓰기: 사용자당 분당 60회), Drive API는 쿼터 단위(읽기 5, 목록 100, 다운로드 200, 편집 50)로 센다. 두 API 모두 현재 무료지만 공식 문서에 "2026년 중 한도 초과분 과금 계획"이 적혀 있다. 핸드오프 때 알린다. Drive는 403도 rate limit일 수 있어 `reason`으로 분기한다. |
| Google 공통 | 5 테스트 | Docs/Sheets/Slides 자체에는 웹훅이 없다. 변경 감지는 Drive `changes.watch`(push) 또는 `changes.list` 폴링으로 한다. 웹훅 테스트는 `google_drive` 서비스에서 한 번만 한다. 채널 수명은 `changes` 최대 1주, `files` 최대 1일이고 자동 갱신이 없다. 알림 본문은 비어 있어 `changes.list`로 다시 조회해야 한다. 폴링을 먼저 검토한다. |
| Google Drive | 1~7 전체 | 별도 단계를 밟지 않는다. Drive는 단독 유즈케이스가 거의 없고 Docs·Sheets·Slides·Forms가 공통으로 기대는 레이어다(파일 메타데이터, 폴더 지정, 목록·검색·삭제·공유, `files.export`, `changes.watch`). Docs를 진행하면서 필요한 Drive 호출을 그때그때 `services/google_drive/`에 채우고, Docs 6단계를 마칠 때 `docs/google_drive.md`를 함께 마감한다. 이후 서비스에서 새 Drive 호출이 생기면 같은 폴더와 문서에 추가한다. scope는 `drive.file` 하나로 시작한다. |
| Google Docs | 5 테스트 | 본문 편집은 `batchUpdate` 하나로 하고, 위치를 문자 인덱스로 지정한다. 삽입할수록 뒤쪽 인덱스가 밀리므로 뒤에서 앞으로 수정하는 순서를 샘플에 남긴다. "편집" 시나리오는 이 인덱스 문제를 반드시 에러 케이스로 다룬다. 인덱스는 UTF-16 코드 단위(이모지는 2)이므로 이모지 포함 케이스도 넣는다. `tabId`를 생략하면 대부분 첫 탭에만 적용되고(`replaceAllText` 등 일부는 모든 탭), `documents.get`도 `includeTabsContent=true` 없이는 첫 탭만 돌려준다. `documents.create`는 제목 외 필드를 무시해 폴더 지정은 Drive로 한다. 텍스트를 서식과 함께 넣는 시나리오는 Drive Markdown 변환 방식과 비교한다. 댓글·제안 API는 2026-07 Developer Preview라 유즈케이스에 넣을 때 사용 가능 여부부터 확인한다. 유즈케이스 3(마감)은 `permissions.update`로 학생 권한을 낮추는 방식으로 확정. `contentRestrictions.readOnly` 잠금은 소유자 API 편집도 막혀 제외, `expirationTime`은 개인 계정 불가. 공유·잠금 실측에는 교수자 계정 외 테스트용 Google 이메일이 필요하다. |
| Google Sheets | 5 테스트 | 값 읽기/쓰기(`values.*`, A1 표기)와 서식·구조 변경(`batchUpdate`, GridRange 0 기반 인덱스)이 다른 API다. 쿼터는 읽기·쓰기 모두 **사용자당 분당 60회**(요청 수 기준, 셀 수 무관. 2026-10-04 공식 문서 확인)라 한 행씩 append하지 말고 `values.batchUpdate`로 모아서 보내는 패턴을 샘플로 남긴다. 페이로드 2MB 권장, 180초 타임아웃. `drive.file`로 모든 Sheets 메서드가 동작한다(scope 추가 없음). 폴더 지정은 Drive로. Docs의 `requiredRevisionId` 같은 낙관적 잠금이 없어 사용자가 행을 끼우면 A1 범위가 어긋난다. 학번처럼 앞자리 0이 있는 값은 `USER_ENTERED`가 숫자로 바꾸므로 `RAW` 기본. CSV 내보내기는 첫 시트만. 실측(2026-10-04): 변환 업로드·복사된 파일의 `sheetId`는 0이 아니므로 `list_sheets`로 얻어 저장한다. `addProtectedRange`는 `editors`를 생략하면 현재 편집자 전원(학생 포함)이 편집 가능으로 들어가 보호가 무의미해진다 → `editors.users=[]`(소유자만) 또는 명시. 보호는 소유자 API 쓰기를 막지 않는다. 세부는 `docs/google_sheets.md` 8절·10절. |
| Google Slides | 5 테스트 | Docs와 같은 `batchUpdate` 방식이지만 인덱스가 아니라 객체 ID(슬라이드, 도형)로 지정한다. 템플릿 복사(Drive `files.copy` 또는 pptx 변환 업로드) 후 `replaceAllText`로 태그 치환이 주 패턴이고, 공식 가이드도 요소 ID 대신 텍스트 태그를 권장한다. 쿼터(2026-10-04 공식 문서 확인): 읽기 사용자당 분당 600, 쓰기 60, **썸네일은 "비싼 읽기"로 따로 60**. `drive.file`로 모든 Slides 메서드가 동작한다(Sheets 차트 연결만 `spreadsheets` scope 필요). 이미지 삽입은 공개 URL만(바이트 업로드 불가). 텍스트를 바꾸면 도형의 autofit이 꺼져 긴 치환 텍스트가 넘친다 → 긴 팀명을 에러 케이스로. 썸네일 URL은 30분 수명·요청자 계정 꼬리표라 서버가 받아 저장한다. `files.export`에 이미지 형식이 없어 슬라이드 이미지는 `getThumbnail`뿐. 세부는 `docs/google_slides.md` 8절·10절. |
| Google Forms | 3 인증 | scope가 설문 본문(`forms.body`)과 응답(`forms.responses.readonly`)으로 나뉜다. 응답은 읽기만 되고 API로 응답을 제출하거나 수정할 수 없다. 이 제약을 2단계 유즈케이스에 반영한다. |
| Google Forms | 5 테스트 | 응답 알림은 Forms `watches`로 받지만 Cloud Pub/Sub 토픽이 필요하다. 폴링으로 충분한지 먼저 판단하고, Pub/Sub은 필요할 때만 테스트한다. 설문 생성 후 질문 추가는 별도 `batchUpdate`다. |
| Zoom | 3 인증 | Marketplace에서 General App(User-managed OAuth)으로 만든다. 액세스 토큰은 1시간, refresh token은 갱신할 때마다 새로 발급되고 이전 것은 무효가 된다. 갱신 직후 저장에 실패하면 재로그인해야 하므로 token_store를 먼저 확실히 만든다. scope는 세분화(granular) 방식으로 고른다. |
| Zoom | 4 환경 | 개인 무료 계정은 클라우드 녹화와 트랜스크립트가 없고 미팅이 40분으로 제한된다. 녹화·트랜스크립트 시나리오가 필요하면 Pro 플랜을 한 달 결제해 테스트하거나 그 시나리오를 보류로 표시한다. 플랜 결정은 2단계에서 한다. |
| Zoom | 5 테스트 | 웹훅(미팅 종료, 녹화 완료)은 앱 설정의 Event Subscriptions에서 켜고, 공개 URL이 필요하므로 ngrok으로 로컬 FastAPI를 노출한다. 등록 시 Zoom이 보내는 URL 검증 챌린지에 응답해야 하고, 이후 모든 이벤트는 서명을 검증한다. 이 두 처리를 라우터로 남긴다. rate limit은 엔드포인트별 등급(Light/Medium/Heavy)이 다르므로 쓰는 엔드포인트마다 등급을 적는다. |
| Zoom | 7 핸드오프 | 문서에 "다른 Zoom 계정 사용자에게 열려면 앱 리뷰가 필요"하다는 점과 예상 소요를 명시한다. 리뷰 전까지는 개발자 계정만 인가할 수 있다. |

공통 주의: 위 제약 중 플랜·쿼터·토큰 만료 수치는 기억에 의존한 값이다. 각 서비스의 1단계(API 탐색)에서 공식 문서로 확인하고 틀리면 이 표를 고친다. Google 공통·Drive·Docs 행은 2026-09-30에, Sheets 행은 2026-10-04에 공식 문서로 확인했다(출처는 각 `docs/<service>.md` 끝). Slides·Forms·Zoom 행은 아직 미확인이다.

## 참고: 심사 절차

Google 앱 검증과 Zoom 앱 리뷰는 개발 중에는 필요 없다. 서비스가 우리 계정 밖 사용자의 Google/Zoom 계정을 연결하는 시점에 필요하며, 각각 수 주가 걸린다. Google은 scope 등급(비민감 / 민감 / 제한)에 따라 검증 수준이 달라지고, 제한 scope는 CASA 외부 보안 평가가 추가된다. Zoom은 General App을 우리 계정 밖 사용자에게 배포(공개든 비공개든)하려면 리뷰를 통과해야 한다. 3단계에서 scope별 사용 이유를 기록해두면 그대로 심사 제출 자료가 된다.

## 진행 현황

공통 준비(한 번만):

- [ ] 상대 개발자에게 Python 버전·패키지 도구·HTTP 클라이언트 선택 확인
- [x] `synsory-api` FastAPI 골격 생성 (`core/`, `services/`, `samples/`, `docs/`, `.env.example`, `.gitignore`, git init) — 2026-10-02. uv + Python 3.12. `core/oauth.py`(login/callback/status/refresh/scopes), `token_store.py`, Drive·Docs client/mapper/usecases/router 배관, pytest 13개
- [x] GCP 프로젝트 + OAuth 동의 화면(테스트 상태) + 개인 계정 테스트 사용자 등록 — 2026-10-02. 웹 애플리케이션 클라이언트, Drive·Docs API 활성화
- [ ] Zoom Marketplace General App 생성 (개인 계정)
- [x] `app/core/models.py`에 Document, Meeting 초안 — 2026-10-02. Meeting 필드는 Zoom 1단계 후 확정

서비스별 현황:

| 서비스 | 현재 단계 | 상태 | 메모 |
| --- | --- | --- | --- |
| Google Drive | 6 문서화 | 1차 마감(2026-10-03), Picker 추가(2026-10-04) | `docs/google_drive.md` 전 절 작성. Sheets·Slides·Forms에서 새 Drive 호출이 생기면 추가. **Picker**(2026-10-04): 1단계 탐색, 테스트 페이지 `GET /google/picker`, 공통 함수 `create_group_files_from_template`(복사→치환→공유. Slides·Docs가 사용, Sheets는 전환 가능), 실측 완료 — Picker 전 404 → Picker 후 Slides 복사·치환·공유 성공, 토큰 refresh·서버 재시작 뒤 유지. 보류: Sheets·Docs 템플릿 Picker 후 실측, 태그 든 원본 재복사(`docs/google_drive.md` 2.1절·12절) |
| Google Docs | 6 문서화 | 완료 → 7 핸드오프 대기 | 유즈케이스 4개 실측·문서화 완료(2026-10-03). `docs/google_docs.md` 12절 전부 작성. 2026-10-04: 유즈케이스 2에 Google Doc 템플릿 경로(`template_document_id`, Picker) 추가(상현 승인). Picker 후 실측은 보류. 다음: 상대 개발자가 2절·11절만 보고 재현, 빠진 것 보충, 옮길 파일 4개 확정 |
| Google Sheets | 6 문서화 | 완료(2026-10-04) → 7 핸드오프 대기 | 유즈케이스 Docs·Slides와 같은 4개 + 마감 후 값 읽기(상현 확정). 템플릿은 xlsx 1회 변환 업로드 → `files.copy` → `findReplace`(수식 안 태그 포함) 실측·채택. 실측·샘플 11개, `docs/google_sheets.md` 12절 전부 작성. 발견: 복사본 `sheetId`≠0, 보호 범위 `editors` 생략 시 학생도 편집 가능(항상 명시), 소유자 API 쓰기는 보호 무시, `RAW`/`USER_ENTERED` 학번 0 소실, csv 내보내기 첫 시트만. **성적표 동기화는 검토 후 보류**(성적 원본은 Synsory DB, 1.2~1.3절). 다음: 상대 개발자 재현, 옮길 파일 4개 확정 |
| Google Slides | 6 문서화 | 완료(2026-10-04) → 7 핸드오프 대기 | 유즈케이스는 Docs와 같은 4개(상현 확정). 템플릿은 pptx 1회 변환 업로드 → 그룹마다 Drive `files.copy` → `replaceAllText`. 실측·샘플 10개, `docs/google_slides.md` 12절 전부 작성. 공유·마감·내보내기 함수는 `google_drive/usecases.py`로 옮겨 Docs와 공유. Drive `files.copy` 추가 |
| Google Forms | 0 시작 전 | 대기 | 응답 쓰기 불가 제약을 2단계에 반영 |
| Zoom | 0 시작 전 | 대기 | 녹화 시나리오 필요 시 플랜 결정 |

## 열린 질문

- 상대 레포의 Python 버전·패키지 도구·SDK 사용 여부 (확인 전까지 Python 3.12 + uv + httpx)
- Zoom 녹화 시나리오 필요 시 Pro 플랜 결제 여부
