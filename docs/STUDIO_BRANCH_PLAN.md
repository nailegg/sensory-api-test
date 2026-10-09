# studio `feat/google-tools` 브랜치 작업 계획

작성일: 2026-10-09 · 작성자: 상현 · 상태: 가정 G1~G5 확정(2026-10-09 상현), 1단계 진행 중. 브랜치는 studio `main`(a03a27f)에서 `feat/google-tools`로 열었다(파일 변경 없음).

결정 근거는 `docs/STUDIO_PORTING.md` 10절 결정 대장(번호로 인용), 서비스별 대응은 각 `docs/<service>.md` 11.x. 이 문서는 "무엇을 어떤 순서로, 어떻게 확인하며" 넣는지만 적는다.

## 0. 전제와 가정 (틀리면 계획이 바뀌는 것)

studio를 읽고 확인한 사실:

- 활동 라우트·활동 화면이 **아직 없다**(`apps/api/src/app.ts` 46개 라우트는 인증·수업·명단·팀뿐, `apps/web/src`에 활동 페이지 없음). `ActivityService`(create·state·structure·save·responses·aggregate)와 `CollectionService.commit`은 있다.
- 마감 시각(`closes_at`) 스케줄러가 **없다.** 상태 전환은 `ActivityService.state(actor, …, 'open'|'closed')`를 사람이 부른다.
- `external_refs`를 쓰는 코드는 `CollectionService.commit`(checkpoint·cursor 갱신)뿐이다.
- worker는 `auth-cleanup` 작업 하나만 등록돼 있다(pg-boss, `retryLimit 3`).
- `productTools`는 빈 registry이고 DB `activity_type_allowed`는 빈 배열이다.
- `packages/ui`가 있다(studio-port의 `ui/google-picker.ts`가 들어갈 자리).

가정(상현 확인 전):

- **G1.** 웹 화면은 이 브랜치 범위 밖. API·worker·도구까지 만들고 화면은 별도 브랜치. (활동 화면 자체가 없어서 "Google 활동 만들기 화면"은 활동 화면 전체를 만드는 일이 된다.)
- **G2.** Google 파일·폼 생성(provision)은 **교수자가 활동을 `open`으로 바꿀 때** worker 작업으로 시작한다. 마감 작업은 **`closed`로 바꿀 때** 시작한다. 스케줄러를 새로 만들지 않는다(없는 기능을 미리 만들지 않음). `closes_at` 자동 마감이 필요해지면 그때 별도 결정.
- **G3.** PR은 단계 묶음으로 낸다: PR-A(1·2), PR-B(3), PR-C(4·5), PR-D(6). 각 PR이 혼자서도 `pnpm verify`를 통과한다.
- **G4.** 실제 Google 호출 확인은 상현 개인 계정으로 로컬에서 1회씩만 한다(원격 dev·prod 미접속, studio `README` 범위와 같음).
- **G5.** Zoom은 넣지 않는다(팀원 파트). 단 1단계 마이그레이션의 worker UPDATE는 Zoom을 위한 것이라 지금 넣는다(결정 41).

만들지 않는 것(karpathy): `IntegrationFactory`·`ConnectionStore` 같은 추상 계층(함수 + `Store`로 충분), 범용 작업 프레임워크(작업 종류마다 함수 하나), 폴링 스케줄러(결정 29), 재시도 로직(pg-boss 기본), 성적·Zoom·화면.

## 1. 단계

각 단계는 커밋 하나 이상. "검증"이 통과해야 다음으로 간다. 공통 검증은 `pnpm typecheck && pnpm lint && pnpm check:boundaries && pnpm test && pnpm test:db`(e2e·build·bundle은 PR 전 `pnpm verify`에서).

### 1단계. 마이그레이션 0010 (결정 26·41)

- 바꾸는 것: `packages/db/src/schema.ts`의 `activity_type_allowed`를 `('google_docs','google_slides','google_sheets','google_forms')`로. `pnpm db:generate`로 SQL·스냅샷·저널 생성 후 SQL 끝에 `GRANT UPDATE ON studio_auth.external_accounts TO studio_worker;`를 덧붙인다(0009와 같은 방식).
- 함께 고치는 문서: studio `AGENTS.md` 7행 "제품 활동 도구는 등록하지 않는다", `TODO.md` 1절 표 "실제 도구 등록 없음" → Google 4개 등록으로. `docs/SECURITY_REVIEW.md` 외부 계정 행에 worker UPDATE 사유.
- 검증: `tests/db/integration.test.ts`의 "keeps the product activity allowlist empty"를 "allows exactly the four google tools"로 바꾸고(4개는 create 성공, `peer_review`는 `INVALID_ARGUMENT`), 0009 권한 테스트에 `worker_update: true` 추가. `pnpm test:db` 통과.
- 안 하는 것: Zoom 도구 이름(팀원이 자기 마이그레이션으로), 다른 테이블 변경.

### 2단계. studio-port 파일 복사 (동작 변화 0)

- 바꾸는 것: `studio-port/packages/{domain,application,infrastructure,contracts,ui}/src/*.ts`를 studio 같은 경로로 복사. `index.ts`에 `export *` 추가(domain은 `index.ts` 한 파일이므로 끝에 export 줄만). `studio-stand-ins.ts`는 복사하지 않고 import를 studio의 `AppError`로 바꾼다. `tests/unit/*.test.ts`·`tests/fixtures/*`도 복사(이름 충돌 시 `google-` 접두사).
- 검증: 복사 전 synsory-api에서 `pnpm verify` 86개 통과를 기록 → 복사 후 studio에서 같은 86개 + 기존 24개 통과, `check:boundaries` 통과, `check:bundle`(웹 번들에 서버 코드 미포함) 통과.
- 안 하는 것: 코드 수정. 복사하면서 "개선"하지 않는다. 필요한 수정은 3단계 이후 각 단계에서.

### 3단계. 외부 계정 연결 (6절, 결정 32~40)

- 바꾸는 것:
  - infrastructure `google-oauth.ts`: 인가 URL(`access_type=offline&prompt=consent&include_granted_scopes=true`, scope `drive.file`), 코드 교환, refresh. synsory-api `core/oauth.py`의 Google 부분만.
  - application `connections.ts` `ConnectionService(db, secrets, env)`: `start(profileId, browser, returnTo)` → state를 `studio_auth.requests`에 `purpose='connect-google'`로(`AuthService.googleStart`와 같은 방식); `callback(...)` → 코드 교환 → 받은 scope 확인 → `external_accounts` upsert(`token_cipher` = `Secrets.encrypt(JSON{refresh_token, scope, account_email})`, 결정 38); `accessToken(profileId)` → 메모리 캐시, 만료 5분 전 갱신, `invalid_grant`면 행 삭제 + `EXTERNAL_RECONNECT_REQUIRED`(6.3); `disconnect(profileId)` → revoke 후 행 삭제.
  - env: `GOOGLE_CONNECT_CLIENT_ID`·`GOOGLE_CONNECT_CLIENT_SECRET`·`GOOGLE_CONNECT_REDIRECT_URI`·`GOOGLE_PICKER_API_KEY`(결정 39·40). `.env.dev.local.example` 문구 수정.
  - apps/api 라우트 3개: `GET /api/connections/google/start`, `GET /api/connections/google/callback`, `DELETE /api/connections/google`. 상태 조회는 기존 세션 응답에 `connections: { google: { account_email } | null }` 한 칸(화면이 "연결됨"을 보여줄 수 있게. G1 때문에 지금은 API만).
- 검증: 단위 테스트(가짜 fetch·가짜 Store): 코드 교환 저장, 캐시 재사용, 만료 임박 갱신, `invalid_grant` → 행 삭제 + 409, scope 누락 거절. DB 테스트: upsert·삭제, 브라우저 역할 접근 불가. 라이브 1회: 로컬 studio에서 상현 계정 연결 → 행 생성 → `accessToken`으로 Drive `files.get` 성공 → 해제.
- 안 하는 것: Zoom 연결, 다중 계정, "하루 전 점검", 키 분리(결정 37).

### 4단계. ToolHandler 4개 (결정 26, 7절)

- 바꾸는 것: domain `google-tools.ts`에 `google_docs`·`google_slides`·`google_sheets`(파일 배포형: `validateConfig`가 `kind`·템플릿 ID 또는 본문·제목 템플릿·`due`를 검사, 응답 없음이라 `validateResponse`는 거절, `aggregate`는 팀별 파일 수)와 `google_forms`(`config.mode` = survey·quiz·peer_review, `validateResponse` = `FormSubmission`, `sourceKey` = 응답 ID, `identity` = `respondent_email`, `aggregate`·`dto`는 기존 `summarize`·`summarizePeerReviews`·`submissionStatus` 재사용). `productTools`에 4개 등록.
- 검증: domain 단위 테스트 — `samples/google_forms/*.json`을 fixture로 `validateResponse`·`identity`·`sourceKey`, 잘못된 config 거절. DB 테스트 — `activities.create`가 4개 타입을 받고 `test_fixture_tool`은 거절. `tests/fixtures/tool.ts`는 그대로(테스트 전용).
- 안 하는 것: 결과 화면 DTO 다듬기(화면이 없으므로 `summary`·`detail` 최소), 퀴즈 재채점 정책.

### 5단계. 생성·마감 작업 + 라우트 (결정 27·28·29, 8절)

- 바꾸는 것:
  - `ActivityService.setExternalRefs(tx, activityId, refs)` 하나 추가(지금은 쓰는 곳이 없어서 없다). `external_refs` 항목에 `created_by_profile_id`(결정 27).
  - worker 작업 3종(infrastructure `google-jobs.ts` 스키마 + enqueue, worker `main.ts`에 `boss.work` 등록. group = activity id):
    - `google-provision`: `ActivityService.state(…, 'open')` 안에서 Google 도구면 enqueue(G2). 작업은 만든 교수자의 `accessToken`으로 폴더 생성 → `createGroupFilesFromTemplate`/`createGroupFilesFromContent`/`createForm`/`createGroupForms` → `setExternalRefs`. 실패한 그룹은 `external_refs`에 `error`로 남긴다(흐름이 이미 그렇게 돌려줌).
    - `google-close`: `state(…, 'closed')`에서 enqueue. `closeSubmissions` 또는 `closeForm`.
    - `google-forms-collect`: `google-close` 끝에 1회(결정 29). `collectResponses` → 100개씩 `CollectionService.commit`.
  - `google-reopen`: `state(…, 'open')`인데 이미 provision된 활동이면 enqueue. `restoreEditors`(external_refs에 저장된 조원 이메일만) 또는 `openForm`.
  - 라우트: 작업 상태 조회 `GET /api/courses/:c/activities/:a/google/status`(`external_refs` 요약). 수동 재수집은 보류.
  - 연결 없으면 `state(…, 'open')`이 409 `EXTERNAL_RECONNECT_REQUIRED` + start URL(결정 40, on-demand 동의).
- 검증: 단위 — 작업 핸들러를 가짜 port·가짜 Store로(그룹 2개 중 1개 실패 → 나머지 저장, 재실행 멱등). DB — `external_refs` 저장 후 `canChangeStructure`가 false, commit 100개 제한. 라이브 1회 — 조 2개 Docs 활동: open → Drive에 파일 2개·공유 → closed → commenter 강등. Forms 1회 — 설문 open → 브라우저로 응답 1건 제출(상현) → closed → `activity_responses` 1행.
- 안 하는 것: `closes_at` 자동 마감, 주기 폴링, 재개(`closed`→`open`) 시 복원(`restoreEditors`는 있지만 요구 확인 뒤), Zoom.

### 6단계. Picker 세션 (결정 36·40, 6절 Picker 항목)

- 바꾸는 것: `GET /api/connections/google/picker-session`(교수자 세션·CSRF 확인, `Cache-Control: no-store`, 남은 수명 5분 미만이면 갱신 후), `POST /api/connections/google/picked-file` → `acceptPickedFile`. helmet: Picker 페이지가 쓰는 출처(`apis.google.com` 스크립트, `docs.google.com` iframe)와 `Referrer-Policy` 확인·조정(미확인 위험, 6절).
- 검증: 단위 — 응답에 refresh token 없음, 헤더 no-store, 학생 세션 403. 라이브 1회 — 임시 HTML(테스트 전용, 커밋 안 함)로 Picker 열어 파일 고르고 `picked-file`이 200.
- 안 하는 것: 화면(G1).

### 7단계. 마무리

- studio `TODO.md`에 이 브랜치 범위·검증 기록, `docs/VERIFICATION.md`에 라이브 확인 결과(토큰·이메일 없이).
- synsory-api: `docs/PLAN.md` 7단계 완료 표시, `docs/STUDIO_PORTING.md` 3절 현황 갱신, 팀원 전달 목록(worker UPDATE, Zoom 소회의실·`Meeting` 필드·대기실 삭제, 42·43).

## 2. 브랜치 뒤 후속 1순위: 호출 최적화 (물결 배치, 2026-10-09 상현)

5단계는 지금 방식(조끼리 동시 4개, 호출마다 왕복)으로 만들고, 브랜치가 끝나면 **가장 먼저** 이것을 한다. 생성 작업이 조 수에 비례해 느려지는 것(6개 조 6~15초, 30개 조 분 단위)을 줄이려는 것이고, worker 결정(28)과는 무관한 어댑터 안 최적화다.

- 방식: 복사 → 치환 → 공유를 조마다 순서대로 돌리는 대신 **단계(물결)마다 조 N개를 한 HTTP로 묶는다.** 1물결 `files.copy` N개를 Drive 배치 하나로, 2물결 치환, 3물결 공유 N개를 Drive 배치 하나로. 왕복이 3×N에서 3회가 된다.
- 먼저 잴 것(synsory-api 실측 스크립트, 상현 계정): 조 6개·20개, pptx 복사 경로에서 "동시 4개" 대 "물결 배치" 소요 시간. Drive 배치가 안쪽 요청을 병렬로 처리하는지는 공식 문서에 없어 재 봐야 안다.
- 확인할 것: ① Docs·Slides·Sheets에 파일 여러 개의 `batchUpdate`를 한 HTTP에 묶는 배치 엔드포인트가 있는지(없으면 2물결은 동시 호출 유지) ② 파일 여러 개의 `permissions.create`를 한 Drive 배치에 섞어도 되는지(지금은 파일 하나당 배치 1회만 실측) ③ 배치 안 하나가 실패할 때 나머지의 동작(공유는 전체 실패 실측 있음, 복사는 미실측).
- 안 되는 것: 업로드 경로(Markdown·CSV `createFromContent`)는 Google 배치 제외. Forms 생성은 배치 엔드포인트 미확인.
- 결과가 좋으면 `GoogleDrivePort`에 `copyFiles(batch)` 같은 묶음 메서드를 넣고 `createGroupFilesFromTemplate`를 물결 순서로 바꾼다. 흐름의 입력·출력(`GroupFileResult[]`)은 그대로.

## 3. 상현이 확인할 것 (코드 전)

1. G1(화면 범위 밖)·G2(open/closed 때 작업 시작)·G3(PR 묶음)이 맞는지.
2. 5단계 라우트: `…/google/status`(진행 상태)는 넣고, `…/google/collect`(수동 재수집)는 요구가 생길 때 추가(2026-10-09 상현 "1로 가자"). "재개 시 복원"은 **포함**(2026-10-09 상현): `closed → open`이면 `google-reopen` 작업으로 `restoreEditors`(처음 공유한 조원만 writer로)·`openForm`.
3. 3단계 env 이름 4개와 로그인용 GCP 프로젝트에 "Drive 연결용" 클라이언트·Picker API 키를 누가 만드는지(상현 콘솔 작업).
