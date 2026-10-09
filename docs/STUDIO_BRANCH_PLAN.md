# studio `feat/google-tools` 브랜치 작업 계획

작성일: 2026-10-09 · 작성자: 상현 · 상태: 가정 G1~G5 확정(2026-10-09 상현), 1·2단계 완료, 3단계 코드 완료(라이브 확인 대기), 6단계까지 완료(라이브 확인 포함), 7단계 전. 브랜치는 studio `main`(a03a27f)에서 `feat/google-tools`로 열었다(파일 변경 없음).

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

### 1단계. 마이그레이션 0010 (결정 26·41) — 완료 2026-10-09 (studio 커밋 1개)

결과: `0010_google_tools.sql`(DROP IF EXISTS + 4개 허용 CHECK + worker UPDATE). 발견: studio 테스트 하네스(`tests/fixtures/database.ts`, 마이그레이션 회귀 테스트 2개)가 `test_fixture_tool` 행을 넣으려고 `activity_type_allowed`를 직접 지우고 바꿔 끼운다. 그래서 DROP은 `IF EXISTS`, 회귀 테스트 2개의 기존 행은 `google_docs`로(0010이 기존 행을 검사하므로), 4개 허용·worker UPDATE 확인은 격리 DB 테스트 `tests/db/google-tools-migration.test.ts`로. DB 테스트 38개·단위 24개·경계 통과.

- 바꾸는 것: `packages/db/src/schema.ts`의 `activity_type_allowed`를 `('google_docs','google_slides','google_sheets','google_forms')`로. `pnpm db:generate`로 SQL·스냅샷·저널 생성 후 SQL 끝에 `GRANT UPDATE ON studio_auth.external_accounts TO studio_worker;`를 덧붙인다(0009와 같은 방식).
- 함께 고치는 문서: studio `AGENTS.md` 7행 "제품 활동 도구는 등록하지 않는다", `TODO.md` 1절 표 "실제 도구 등록 없음" → Google 4개 등록으로. `docs/SECURITY_REVIEW.md` 외부 계정 행에 worker UPDATE 사유.
- 검증: `tests/db/integration.test.ts`의 "keeps the product activity allowlist empty"를 "allows exactly the four google tools"로 바꾸고(4개는 create 성공, `peer_review`는 `INVALID_ARGUMENT`), 0009 권한 테스트에 `worker_update: true` 추가. `pnpm test:db` 통과.
- 안 하는 것: Zoom 도구 이름(팀원이 자기 마이그레이션으로), 다른 테이블 변경.

### 2단계. studio-port 파일 복사 (동작 변화 0) — 완료 2026-10-09 (studio 커밋 1개)

결과: Google 파일 17개 + 테스트 6개·fixture 3개를 수정 없이 복사, index 5개에 export 추가. 복사 전 Zoom port를 `zoom-ports.ts`로 분리해(synsory-api b7bf657) Zoom 파일은 한 줄도 넣지 않았다. 검증: studio에서 typecheck·lint·boundaries·unit 95개(기존 24 + 복사 71, Zoom 테스트 15개 제외)·build·bundle·design·secrets 통과.

- 바꾸는 것: `studio-port/packages/{domain,application,infrastructure,contracts,ui}/src/*.ts`를 studio 같은 경로로 복사. `index.ts`에 `export *` 추가(domain은 `index.ts` 한 파일이므로 끝에 export 줄만). `studio-stand-ins.ts`는 복사하지 않고 import를 studio의 `AppError`로 바꾼다. `tests/unit/*.test.ts`·`tests/fixtures/*`도 복사(이름 충돌 시 `google-` 접두사).
- 검증: 복사 전 synsory-api에서 `pnpm verify` 86개 통과를 기록 → 복사 후 studio에서 같은 86개 + 기존 24개 통과, `check:boundaries` 통과, `check:bundle`(웹 번들에 서버 코드 미포함) 통과.
- 안 하는 것: 코드 수정. 복사하면서 "개선"하지 않는다. 필요한 수정은 3단계 이후 각 단계에서.

### 3단계. 외부 계정 연결 (6절, 결정 32~40) — 코드 완료 2026-10-09 (studio 커밋 1개), 라이브 확인 대기

결과: application `connections.ts`(`ConnectionService`: start·callback·status·accessToken·disconnect, `GoogleOAuthPort`), infrastructure `google-oauth.ts`(인가 URL·코드 교환·갱신·userinfo·revoke), env 2개(`GOOGLE_CONNECT_CLIENT_ID`·`_SECRET`, 없으면 연결 API 503), contracts `googleConnectionDto`, 라우트 4개(`POST /api/connections/google/start`, `GET …/callback`, `GET /api/connections/google`, `DELETE /api/connections/google`). 계획과 다른 점: ① 연결 계정 이메일(결정 38)을 받으려고 scope에 `userinfo.email`을 더했다(비민감). ② 콜백은 연결을 시작한 교수자의 로그인 세션과 같은 브라우저만 받는다(state의 profile_id와 세션 일치 확인). ③ 상태 조회는 세션 응답 대신 별도 `GET /api/connections/google`. ④ `IntegrationFactory`·`ConnectionStore` 없이 `Store` + port 하나. 검증: 단위 4개(어댑터), DB 4개(저장·거절 4종·캐시/갱신/끊김·해제), 기존 검사 전부 통과. 남은 것: 콘솔 설정 뒤 상현 계정으로 연결 → 행 생성 → `accessToken`으로 Drive `files.get` → 해제 1회.

- 바꾸는 것:
  - infrastructure `google-oauth.ts`: 인가 URL(`access_type=offline&prompt=consent&include_granted_scopes=true`, scope `drive.file`), 코드 교환, refresh. synsory-api `core/oauth.py`의 Google 부분만.
  - application `connections.ts` `ConnectionService(db, secrets, env)`: `start(profileId, browser, returnTo)` → state를 `studio_auth.requests`에 `purpose='connect-google'`로(`AuthService.googleStart`와 같은 방식); `callback(...)` → 코드 교환 → 받은 scope 확인 → `external_accounts` upsert(`token_cipher` = `Secrets.encrypt(JSON{refresh_token, scope, account_email})`, 결정 38); `accessToken(profileId)` → 메모리 캐시, 만료 5분 전 갱신, `invalid_grant`면 행 삭제 + `EXTERNAL_RECONNECT_REQUIRED`(6.3); `disconnect(profileId)` → revoke 후 행 삭제.
  - env: `GOOGLE_CONNECT_CLIENT_ID`·`GOOGLE_CONNECT_CLIENT_SECRET`·`GOOGLE_CONNECT_REDIRECT_URI`·`GOOGLE_PICKER_API_KEY`(결정 39·40). `.env.dev.local.example` 문구 수정.
  - apps/api 라우트 3개: `GET /api/connections/google/start`, `GET /api/connections/google/callback`, `DELETE /api/connections/google`. 상태 조회는 기존 세션 응답에 `connections: { google: { account_email } | null }` 한 칸(화면이 "연결됨"을 보여줄 수 있게. G1 때문에 지금은 API만).
- 검증: 단위 테스트(가짜 fetch·가짜 Store): 코드 교환 저장, 캐시 재사용, 만료 임박 갱신, `invalid_grant` → 행 삭제 + 409, scope 누락 거절. DB 테스트: upsert·삭제, 브라우저 역할 접근 불가. 라이브 1회: 로컬 studio에서 상현 계정 연결 → 행 생성 → `accessToken`으로 Drive `files.get` 성공 → 해제.
- 안 하는 것: Zoom 연결, 다중 계정, "하루 전 점검", 키 분리(결정 37).

### 4단계. ToolHandler 4개 (결정 26, 7절) — 완료 2026-10-09 (studio 커밋 1개)

결과: domain `google-tools.ts`에 핸들러 4개와 config 스키마(Docs: 템플릿 파일 또는 Markdown 중 하나, Slides: 템플릿 파일, Sheets: 템플릿 파일 또는 CSV, Forms: `mode` survey·quiz·peer_review), 수집 payload 스키마 `formSubmission`, 5단계가 쓸 external_refs 항목 스키마 `googleFileRef`(조별 파일 + `member_emails`·`created_by_profile_id`)·`googleFormRef`(폼 + `questions`·`reviewees`). `productTools`에 등록. 집계: 파일 도구는 조별 파일 목록, Forms는 mode별로 `summarize`·점수표·`summarizePeerReviews`. 검증: 단위 8개(config 4종, 응답 없음, 집계, authorize, Forms 검증·키·dto·설문·동료평가 집계) + 기존 `productTools` 테스트를 4개 등록으로 수정, 전 검사 통과(단위 107, DB 42). 계획과 다른 점: "activities.create가 4개를 받는 DB 테스트"는 테스트 하네스가 허용 목록을 `test_fixture_tool`로 바꿔 끼워서 불가능해 생략(허용 목록은 1단계 격리 테스트, 등록은 단위 테스트가 증명). 주의: `google-tools.ts`와 `index.ts`가 서로 import한다(핸들러가 `invariant`를 쓰고 index가 등록). 모듈 평가 시점에는 안 쓰므로 안전하지만 domain 바깥은 항상 `index.ts`로 import할 것.

- 바꾸는 것: domain `google-tools.ts`에 `google_docs`·`google_slides`·`google_sheets`(파일 배포형: `validateConfig`가 `kind`·템플릿 ID 또는 본문·제목 템플릿·`due`를 검사, 응답 없음이라 `validateResponse`는 거절, `aggregate`는 팀별 파일 수)와 `google_forms`(`config.mode` = survey·quiz·peer_review, `validateResponse` = `FormSubmission`, `sourceKey` = 응답 ID, `identity` = `respondent_email`, `aggregate`·`dto`는 기존 `summarize`·`summarizePeerReviews`·`submissionStatus` 재사용). `productTools`에 4개 등록.
- 검증: domain 단위 테스트 — `samples/google_forms/*.json`을 fixture로 `validateResponse`·`identity`·`sourceKey`, 잘못된 config 거절. DB 테스트 — `activities.create`가 4개 타입을 받고 `test_fixture_tool`은 거절. `tests/fixtures/tool.ts`는 그대로(테스트 전용).
- 안 하는 것: 결과 화면 DTO 다듬기(화면이 없으므로 `summary`·`detail` 최소), 퀴즈 재채점 정책.

### 4.5 검수 (2026-10-09, karpathy·주석) — 완료 (studio 커밋 a7c5551)

별도 에이전트 검수 결과와 처리:
- **순환 import(중)**: `google-tools.ts` ↔ domain `index.ts`. 파일을 직접 import하면 `ReferenceError` 실측(index 경유만 안전). `AppError`·`invariant`를 `domain/src/errors.ts`로 빼서 순환을 없앴다(index는 재export). 직접 import 확인 통과.
- **주석(중)**: main은 주석 24줄·전부 영어·한 줄 "왜"인데 브랜치가 한국어 330줄을 더했다. 상현 결정: **기술적 선택의 이유만 영어 한 줄로 남기고 전부 삭제**(설명·유즈케이스 번호·이식 출처·구분선 제거). 이로써 studio 파일과 synsory-api `studio-port/`는 **주석만 다르다**(코드 본문 동일). "수정 없이 복사" diff 검증은 폐기(상현: 본문을 안 건드리면 동일성은 성립). 앞으로 코드 변경은 studio가 기준이고 studio-port는 참조용.
- 기록만(코드 변경 없음): 6.2절 "한 프로세스 안의 동시 갱신 공유"는 구현하지 않음(Google은 refresh token이 안 바뀌어 무해, 호출만 늘 수 있음. 5단계 실측에서 거슬리면 promise 공유 3줄). 결정 23(`externalDocument` 축소)은 5단계에서. 콜백 리다이렉트 쿼리 `?google=connected`·`/courses?google_error=<code>`는 화면 브랜치가 알아야 할 계약. 5단계 DB 테스트에서 `created_by_profile_id` 누락 시 집계가 조용히 비는 경로를 잡을 것. 6.3절 403 `insufficientPermissions` 재연결 처리는 5단계 작업 핸들러에서.
- 미룸(사소): `callback` 반환 `account_email` 미사용, survey·quiz 스키마 중복, 테스트 `toThrow()` 4곳 약한 단언, `refresh_token` 없는 토큰 응답 단위 케이스.

### 5단계. 생성·마감 작업 + 라우트 (결정 27·28·29, 8절) — 코드 완료 2026-10-09 (studio 커밋 1개), 라이브 확인 대기

결과: application `google-activities.ts`(`provisionGoogleActivity`·`closeGoogleActivity`·`reopenGoogleActivity`·`collectGoogleForms`·`googleStatus`·`requireTeams`), `ActivityService.state()`에 `ActivityJobs` 훅(같은 트랜잭션에서 enqueue) + `ActivityService.get()`, infrastructure `google-jobs.ts`(작업 스키마·`enqueueGoogleJob`·보내기 전용 `createJobSender`·`googlePorts`), `migrate.ts`에 큐 3개, worker `main.ts`에 핸들러 3개, API에 훅·상태 라우트 `GET …/activities/:id/google/status`. 계획과 다른 점: ① "만든 교수자"는 활동을 **처음 `open`한 교수자**(`activities`에 만든 사람 칸이 없음). provision이 폴더 ref에 `created_by_profile_id`로 적고 마감·재개·수집은 거기서 읽는다. ② 수집용 별도 큐 없음: 마감 작업 끝에 바로 수집(결정 29). ③ `setExternalRefs` 메서드 대신 job 모듈이 `external_refs`를 직접 쓴다(ActivityService 미수정). ④ 조 단위 실패는 ref에 `error`로, 마감·재개 실패는 `close_error`·`reopen_error`로 남기고 상태 라우트가 보여준다. 폼 하나짜리 생성 실패는 예외로 올려 pg-boss가 3회 재시도. ⑤ 폴더는 교수자 Drive 루트에 "수업 - 활동" 이름으로. 검증: DB 테스트 4개(조별 파일 생성·실패 격리·멱등·마감·재개·상태 DTO, 설문 생성·응답자 제한·수집·재수집 무변화, 동료평가 조별 폼, 팀 구성 요구·훅 트랜잭션 롤백), 전 검사 통과(DB 46, 단위 107). 남은 것: 라이브(조 2개 Docs 활동 open → 파일·공유 → closed → commenter, 설문 1개 응답 → 수집)와 6.3절 403 `insufficientPermissions` 재연결 처리.

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

### 6단계. Picker 세션 (결정 36·40, 6절 Picker 항목) — 코드 완료 2026-10-09 (studio 커밋 1개), 라이브 확인 대기

결과: `GET /api/connections/google/picker-session`(`ConnectionService.currentToken`: access token + 만료, 5분 미만이면 갱신. `developer_key` = `GOOGLE_PICKER_API_KEY`, `app_id` = `pickerAppId`(client ID 앞 숫자 또는 `GOOGLE_PROJECT_NUMBER`). 키 없으면 503), `POST …/picked-file`(`acceptPickedFile`로 서버 접근·종류 확인, 계약 `pickedFile`에 `kind` 추가, 응답 `pickedFileDto`). helmet 확인 결과: **API는 웹 HTML을 서빙하지 않는다**(정적 서빙 코드 없음). helmet 헤더는 API JSON 응답에만 붙으므로 Picker에 영향이 없고, 6절의 "미확인 위험"은 해소. 대신 웹을 서빙하는 쪽(Vite dev, 추후 배포 호스트)이 CSP를 걸 때 `apis.google.com` 스크립트·`docs.google.com` iframe 허용과 referrer 전송(`strict-origin-when-cross-origin`)이 필요하다는 점을 TODO.md에 적었다. `Cache-Control: no-store`는 API 전역 훅이 이미 붙인다. 검증: 단위(계약 `kind` 필수), DB(`currentToken` 만료·캐시), 전 검사 통과(DB 47, 단위 107). 남은 것: 임시 HTML로 Picker 열어 `picked-file` 200 확인(콘솔 키 뒤).

- 바꾸는 것: `GET /api/connections/google/picker-session`(교수자 세션·CSRF 확인, `Cache-Control: no-store`, 남은 수명 5분 미만이면 갱신 후), `POST /api/connections/google/picked-file` → `acceptPickedFile`. helmet: Picker 페이지가 쓰는 출처(`apis.google.com` 스크립트, `docs.google.com` iframe)와 `Referrer-Policy` 확인·조정(미확인 위험, 6절).
- 검증: 단위 — 응답에 refresh token 없음, 헤더 no-store, 학생 세션 403. 라이브 1회 — 임시 HTML(테스트 전용, 커밋 안 함)로 Picker 열어 파일 고르고 `picked-file`이 200.
- 안 하는 것: 화면(G1).

### 6.5 라이브 확인 (2026-10-10) — 완료 (studio 커밋 6d149e1)

로컬 Supabase + 상현 개인 Google 계정(연결용 클라이언트는 실측용과 다른 새 클라이언트). 결과는 studio `docs/VERIFICATION.md` 2026-10-10 항목.

| 확인 | 결과 |
| --- | --- |
| 연결(3단계) | 성공. `connected: true`, 계정 이메일, `external_accounts` 1행 |
| Picker 세션(6단계) | 200, `no-store`, refresh token 없음, 프로젝트 번호 추출 |
| Docs 활동 open → closed → open(5단계) | 8초 안에 폴더+문서 2개, 태그 치환, writer → commenter → writer |
| 설문 open → 응답 1건 → closed(5단계) | 폼 생성·응답자 제한, 수집 1행, 집계 평균 5 |

라이브에서 잡은 버그 2건(수정·테스트 추가·커밋): ① 재개 시 `validateConfig`가 서버가 넣는 `team_snapshot`을 strict 스키마로 거절 → 검증 전 분리. ② 수집이 `course_members` `FOR SHARE`에서 worker 권한 부족(Postgres는 행 잠금에 UPDATE 필요) → 마이그레이션 0011. DB 테스트가 이제 worker 역할로 수집을 돌린다.

알게 된 것(7단계·후속 결정): ① 사람별 공유 실패(예: 조원이 파일 소유자 본인)는 refs에 안 남아 상태 라우트에 안 보인다 → `share_errors`로 남길지 결정. ② 실패한 작업은 재시도 3회 뒤 `failed`로 멈추고, 재실행 경로는 교수자의 재개·재마감뿐 → 화면 설계 때 "다시 시도" 필요 여부. ③ Picker 자체(브라우저 모듈)는 아직 임시 HTML로 열어 보지 않았다(`picked-file`만 미확인). 실측 파일은 Drive 휴지통으로 정리했고 studio 로컬 DB의 수업 "Test" 데이터(학생 2·팀 구성·활동 2)는 남겨 두었다.

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
3. 3단계 콘솔 작업(상현, 로그인용 GCP 프로젝트에서. 결정 39·40):
   1. API 6개 사용 설정: Google Drive · Docs · Slides · Sheets · Forms · Picker API(안 켜면 403 `accessNotConfigured`. 실측 프로젝트에는 이미 켜져 있음).
   2. OAuth 클라이언트를 **새로 하나** 만든다(콘솔 › 사용자 인증 정보 › 만들기 › OAuth 클라이언트 ID, 유형 "웹 애플리케이션", 이름은 구별용으로 예: "Synsory Drive 연결(local)"). 만들 때 "승인된 리디렉션 URI" 칸에 `http://localhost:5173/api/connections/google/callback`을 넣는다(동의 뒤 Google이 일회용 코드를 돌려보낼 studio 주소. 코드가 `API_PUBLIC_ORIGIN + /api/connections/google/callback`으로 만들므로 env에는 안 넣음). 만들면 나오는 client ID·secret이 3-5의 두 값이다. 새로 만드는 이유: 로그인용 클라이언트는 Supabase 주소로, 실측용은 `localhost:8000`으로 돌려보내게 돼 있고 Drive 연결은 studio 주소로 와야 한다(용도·환경별 분리는 결정 39). 지금은 local 하나만, dev·prod 서버가 생기면 같은 방법으로 하나씩 더.
   3. Picker용 API 키: 애플리케이션 제한 = 웹사이트(`http://localhost:5173/*`, `https://docs.google.com/*`), API 제한 = Google Picker API.
   4. 동의 화면이 테스트 상태면 상현 계정을 테스트 사용자로. scope는 코드가 `drive.file`만 요청하므로 콘솔 추가 없음.
   5. studio env: `GOOGLE_CONNECT_CLIENT_ID` · `GOOGLE_CONNECT_CLIENT_SECRET`(비밀) · `GOOGLE_PICKER_API_KEY` · `GOOGLE_PROJECT_NUMBER`(비우면 client ID 앞 숫자).
   확인: 로그인용 프로젝트 소유 계정(Supabase › Auth › Providers › Google의 client ID 앞 숫자가 프로젝트 번호). 상현 권한이 없으면 실측 프로젝트를 임시로 쓰고 결정 40 재검토.
