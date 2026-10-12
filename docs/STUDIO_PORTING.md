# synsory-studio 이식 공통 가이드

작성일: 2026-10-08 · 작성자: 상현 · 상태: **초안. 6절 연결 설계는 팀 승인(2026-10-09, studio 반영), 나머지는 studio 담당자 확인 전. 결정 대장은 10절**

synsory-api에서 실측한 Google·Zoom 연동을 synsory-studio(TypeScript)로 옮길 때 서비스와 무관하게 공통으로 적용하는 배치·형식·흐름을 적는다. 서비스별 내용(어떤 함수가 어느 파일로, 어떤 port 메서드가 필요한지)은 각 `docs/<service>.md` 11절 끝 "studio 이식" 하위절에 적는다.

studio에는 외부 도구 배치에 대한 가이드가 없다(현재 범위가 "제품 활동 도구 미등록"이라서). 그래서 이 문서는 **studio의 기존 규칙과 관례를 따른 제안**이다. 1절은 studio에 이미 정해진 것, 2절부터는 제안이고, 제안 중 studio 쪽 결정이 필요한 것은 **[결정 필요]**로 표시하고 10절에 모은다.

## 1. studio에 이미 정해진 규칙

이식 코드도 그대로 따라야 한다. 출처는 studio 레포 기준.

| 규칙 | 출처 |
| --- | --- |
| 유스케이스는 `packages/application`, I/O는 `packages/db`·`packages/infrastructure`, HTTP는 `apps/api` | `AGENTS.md` 아키텍처 |
| `domain`은 `domain`과 `zod`만, `application`은 `application`·`contracts`·`domain`과 `zod`만 import. 위반 시 `pnpm check:boundaries` 실패 | `scripts/boundary-rules.ts` |
| 웹·API는 `packages/contracts`의 Zod 계약 공유 | `AGENTS.md` |
| 오류는 `AppError(code, status, 한국어 message)`, API 응답 `{ error: { code, message, details? }, request_id }`. 화면 분기는 `code` 기준 | `AGENTS.md`, `packages/domain/src/index.ts` |
| 활동 도구 형식은 `ToolHandler`(`key`, `version`, `validateConfig`, `validateResponse`, `authorize`, `sourceKey`, `identity`, `dto`, `aggregate`, `aggregateDto`). 예시 구현은 `tests/fixtures/tool.ts` 하나 | `packages/domain/src/index.ts` |
| 새 도구는 설정·응답의 수업·배정 참조, 권한별 DTO·집계 DTO, 외부 인증 비밀·멱등 처리를 구현한 뒤 코드와 DB 허용 목록(`activity_type_allowed`)을 함께 바꾼다 | `docs/SECURITY_REVIEW.md` |
| 테스트 도구·가짜 구현은 `tests/fixtures`에만 | `AGENTS.md` |
| 스키마 변경은 `packages/db/src/schema.ts` + 새 Drizzle 마이그레이션·메타데이터를 같은 커밋에 | `AGENTS.md` |
| 제품 테이블은 `studio` 스키마 8개 유지. 인증·큐·마이그레이션은 비공개 `studio_auth`·`studio_queue`·`studio_migrations` | `AGENTS.md` |
| 토큰·비밀·원본 응답·개인정보를 로그에 남기지 않는다. 인증 토큰은 브라우저 저장소에 두지 않는다 | `AGENTS.md` |
| 네트워크 대기 중 저장 트랜잭션을 유지하지 않는다. 같은 리소스는 큐 group으로 묶고 checkpoint revision으로 중복 저장을 막는다 | studio `TODO.md` P5 |
| N+1 금지, 필요한 행·열만 조회, 배치 처리 | `AGENTS.md` |

기존 코드에서 드러나는 형식 관례:

- 패키지마다 `src/` 아래 **하위 폴더 없이 평평하게** 파일을 둔다(`courses.ts`, `invites.ts`, `queue.ts`). 바깥 노출은 `index.ts`의 `export * from './x.ts'`.
- port 인터페이스 파일은 `ports.ts`, `auth-ports.ts`처럼 `<영역>-ports.ts`.
- import는 상대 경로 + `.ts` 확장자(`'../../domain/src/index.ts'`).
- TypeScript는 `strict`, `noUncheckedIndexedAccess`, `exactOptionalPropertyTypes`, `any` 금지(ESLint error). 외부 JSON은 Zod로 파싱해서 타입을 얻는다.
- 큐 작업은 `packages/infrastructure/src/queue.ts`의 `auth-cleanup` 패턴: Zod 작업 스키마 → 업무 트랜잭션 연결로 `boss.send` 하는 enqueue 함수 → `apps/worker/src/main.ts`에서 `boss.work` 등록.
- 테스트: `tests/unit`(vitest, DB 없음), `tests/db`(로컬 `studio_test`), `tests/e2e`(Playwright).
- 의존성은 `package.json`에 정확한 버전으로 고정한다. 런타임 Node 24.21, TypeScript 6.0, Zod 4.6, vitest 5.0.

## 2. 층 나누기 원칙

synsory-api의 파일 4종을 studio 층에 나누는 기준이다.

| 질문 | 답이 "예"면 |
| --- | --- |
| Google·Zoom의 URL, 요청 본문 모양, 응답 JSON 모양을 아는 코드인가 | `infrastructure` |
| 외부 서비스를 몰라도 성립하는 Synsory 규칙인가(집계, 출석 판정, 템플릿 변수, 응답 payload 형식) | `domain` |
| 여러 외부 호출과 DB(수업·팀·명단·활동)를 엮는 순서인가 | `application` |
| 웹 화면과 주고받는 형식인가 | `contracts` |

그래서 synsory-api 파일은 이렇게 갈라진다.

| synsory-api | studio |
| --- | --- |
| `client.py` + usecases 안의 요청 본문 생성 함수(`replace_tag_requests`, `build_setup_requests`, `protect_range_requests` 등) + mapper의 **응답 형식 변환** | `infrastructure`의 서비스 어댑터. application에는 "태그 치환", "폼 만들기"처럼 의미 단위 메서드만 보인다. 예외: Forms `peer_review_items`는 `domain`(동료평가 폼 구조가 Synsory 규칙이고 application이 만들어 port에 넘겨야 해서, `docs/google_forms.md` 11.1절) |
| mapper·usecases 안의 **순수 Synsory 규칙**(`summarize`, `summarize_peer_reviews`, `summarize_attendance`, `render_template`) | `domain` |
| usecases의 **흐름**(그룹마다 복사→치환→공유, 미게시 생성→게시→응답자 제한, 수집 커서) | `application` |
| `core/models.py` | 저장 형식(payload, `external_refs` 항목) Zod 스키마는 `domain`, 화면 DTO는 `contracts` |

**[결정 필요 A]** 응답 형식 변환(mapper)을 infrastructure에 두는 이 안은 `CLAUDE.md` 대응표("mapper → infrastructure + domain")와 같다(2026-10-09 표 정리). domain은 `contracts`를 import할 수 없으므로 `ToolHandler.validateResponse`가 쓰는 payload 스키마는 domain에 있어야 하고, Google 응답 모양은 바깥 층에 가두는 편이 경계가 깔끔하다.

## 3. 파일 배치안

기존 관례(평평한 파일, `<영역>-ports.ts`)를 따른다. **[결정 필요 B]** 하위 폴더(`infrastructure/src/google/`)를 쓸지 여부.

```
packages/domain/src/
  integrations.ts          # 외부 자원 참조(external_refs 항목) Zod 스키마: Document·Meeting 대응, render_template
  google-forms-tool.ts     # Forms payload 스키마(FormSubmission), ToolHandler, 응답 집계·동료평가 집계
  google-files-tool.ts     # Docs·Slides·Sheets 그룹 파일 도구의 ToolHandler (응답 없음, external_refs 중심)
  zoom-tool.ts             # Zoom 미팅 도구 ToolHandler, 출석 집계(summarize_attendance)
  index.ts                 # productTools registry에 위 도구 등록 (registry가 이미 여기 있음)

packages/application/src/
  integration-ports.ts     # GoogleDrivePort, GoogleDocsPort, …, ZoomPort, ConnectionStore, IntegrationFactory
  connections.ts           # 외부 계정 연결 시작·콜백·해제, 유효 access token 얻기(갱신 포함)
  google-files.ts          # Drive 공통 흐름: 그룹 파일 생성, 마감(권한 낮추기), 복원, 내보내기
  google-forms.ts          # Forms 흐름: 생성·게시·응답자 제한·수집 작업 처리
  zoom-meetings.ts         # Zoom 흐름: 그룹 미팅, 반복, 변경·취소, 웹훅 이벤트 처리

packages/infrastructure/src/
  oauth-providers.ts       # Google·Zoom 인가 URL, 코드 교환, refresh (core/oauth.py의 PROVIDERS)
  external-http.ts         # 공통 fetch 래퍼, 외부 오류 분류(status·reason·rate limit)
  google-drive.ts          # GoogleDrivePort 구현 (google_drive/client.py + 응답 변환)
  google-docs.ts
  google-slides.ts
  google-sheets.ts         # A1·GridRange 헬퍼 포함
  google-forms.ts
  zoom.ts                  # CRC 응답·서명 검증(node:crypto)도 이 파일에 둠(zoom-webhook.ts로 나누지 않음)
  integration-jobs.ts      # 수집·웹훅 처리 큐 작업 스키마와 enqueue (queue.ts 패턴)

packages/contracts/src/index.ts   # 연결 상태, 도구 설정 입력, 결과 DTO
packages/db/src/schema.ts         # studio_auth.external_accounts + 마이그레이션
apps/api/src/app.ts               # 연결 라우트, Zoom 웹훅 라우트, 도구 동작 라우트
apps/worker/src/main.ts           # 수집·웹훅 작업 등록
tests/fixtures/                   # synsory-api samples/*.json, 가짜 port
tests/unit/                       # pytest 케이스의 vitest 번역
```

**현황(2026-10-10, studio `feat/google-tools`)**: 위 계획 중 studio에 **있는 것** — domain `errors.ts`(AppError·invariant 분리) · `integrations.ts` · `google-forms-tool.ts` · `google-tools.ts`(ToolHandler 4개, external_refs 스키마), application `integration-ports.ts` · `google-files.ts` · `google-forms.ts` · `google-picker.ts` · `concurrency.ts` · `connections.ts`(연결) · `google-activities.ts`(생성·마감·재개·수집·상태), infrastructure `external-http.ts` · `google-*.ts` 어댑터 · `google-oauth.ts` · `google-jobs.ts`(작업 스키마·보내기 전용 큐·port 묶음), contracts·ui `google-picker.ts`, `apps/api/app.ts`(연결 4 + Picker 2 + 상태 1 라우트, 상태 전환 훅), `apps/worker/main.ts`(작업 3종), 마이그레이션 0010·0011. 계획과 다른 이름: `connections.ts`가 `oauth-providers.ts`·`ConnectionStore`·`IntegrationFactory`를 대신하고, `zoom-webhook.ts`·`integration-jobs.ts`는 Zoom 브랜치 몫. 없는 것: 웹 화면(G1), Zoom.

## 4. port 설계

- port는 서비스 단위 인터페이스이고, 메서드는 **의미 단위**다. 예: `GoogleDocsPort.replaceTags(docId, vars) → Record<string, number>`, `GoogleFormsPort.listResponses(formId, since) → { submissions, cursor }`. Google 요청 본문 모양은 port 뒤로 숨는다.
- 토큰은 메서드 인자로 넘기지 않는다. application이 `IntegrationFactory.google(profileId)`로 그 교수자의 토큰이 묶인 port 묶음을 받는다. 토큰 꺼내기·갱신은 팩토리 안(infrastructure)에서 `connections`를 통해 한다.
- 반환값은 domain 타입(또는 단순 객체)이다. Google 응답 원문을 application으로 올리지 않는다.
- synsory-api 테스트의 `FakeDrive`·`FakeForms` 등이 곧 이 port의 가짜 구현이다(`tests/fixtures`).

## 5. 오류 변환

synsory-api의 `XApiError(status, body, is_rate_limit, reason)`는 infrastructure의 `ExternalApiError`로 옮긴다. `ExternalApiError`는 domain `AppError`를 상속한다(studio-port 구현, 2026-10-09). application은 infrastructure를 import할 수 없으므로 `AppError`로 외부 호출 실패를 알아보고 "기록하고 다음으로" 처리하며, 그 밖의 예외는 버그로 올린다. `details`(API 응답에 나감)에는 `status`·`reason`·`api_status`만 둔다. Google 원문 메시지는 원인 추적용으로 별도 필드 `externalMessage`에 둔다. 파일 ID·이메일이 섞일 수 있어 응답으로 내보내지 않고, 로그에는 **외부 오류 전용 구조화 필드로, 이메일·파일 ID를 가린 뒤** 남긴다(결정 31, 2026-10-09. studio 로거가 `err.message`를 redacted로 바꾸므로 별도 필드가 필요하다). 코드 이름 제안 **[결정 필요 C]** (Google 오류 중 아래 세 개만 구현, 연결 관련 두 개는 연결 흐름을 만들 때):

| 상황 | 판별 (synsory-api 근거) | AppError code · status |
| --- | --- | --- |
| rate limit | 429, Google `RESOURCE_EXHAUSTED`, Drive `reason` = `rateLimitExceeded`·`userRateLimitExceeded` (Drive는 403도 rate limit일 수 있음) | `EXTERNAL_RATE_LIMITED` 429 |
| 연결 없음 · refresh 실패 | 저장된 연결 없음, refresh 400 `invalid_grant`, Zoom code 124 | `EXTERNAL_RECONNECT_REQUIRED` 409 |
| 파일 접근 불가 | `drive.file`로 앱이 모르는 파일 → 404 (Picker로 고르기 전 템플릿) | `EXTERNAL_NOT_FOUND` 404 |
| 플랜 제한 | Zoom code 200 (유료 전용) | `EXTERNAL_PLAN_REQUIRED` 403 |
| 그 밖의 외부 오류 | 4xx/5xx | `EXTERNAL_FAILED` 502 |

외부 응답 본문 원문은 개인정보가 섞일 수 있어 `details`에 넣지 않는다.

## 6. 외부 계정 연결 (core/oauth.py · token_store.py 대체)

studio의 Google 로그인(Supabase, `openid email profile`)과 **별개 흐름**이다. Supabase는 provider refresh token을 저장·갱신하지 않기 때문이다. 교수자가 "Google 연결"·"Zoom 연결"을 따로 누른다.

1. **시작** `GET /api/connections/{platform}/start`: 교수자가 **첫 Google 활동을 저장할 때** 연결이 없으면 409 `EXTERNAL_RECONNECT_REQUIRED` + 이 URL을 돌려주고, 웹이 여기로 보낸다(결정 40, on-demand. 설정 화면의 "연결" 버튼도 같은 URL). state에 돌아갈 경로(작성 화면)를 담는다. state를 `studio_auth.requests`에 `purpose='connect-google'`(또는 `connect-zoom`), browser 해시, 10분 만료로 저장한다. studio Google 로그인이 이미 `purpose='google'`로 같은 방식을 쓴다(`application/src/auth.ts` `googleStart`). 인가 URL 파라미터는 synsory-api 그대로:
   - Google: `access_type=offline`, `prompt=consent`, `include_granted_scopes=true`, scope = Drive `drive.file` + `userinfo.email`(연결 계정 이메일 표시용, 결정 38. 2026-10-09 구현) (+ 이후 서비스 scope)
   - Zoom: scope는 앱 설정에서 정해지지만 URL에도 넣는다. client 인증은 Basic 헤더
2. **콜백** `GET /api/connections/{platform}/callback`: state를 1회 소비 → 코드 교환 → 받은 scope와 요청 scope 비교(누락 시 사용자에게 알림, synsory-api `missing_scopes`) → 저장.
3. **저장** — 교수자 × 플랫폼당 한 행 `studio_auth.external_accounts`(아래 6.1). 토큰은 provider마다 모양이 달라 **암호화한 JSON 하나**로 담고, 암호를 풀지 않고 알아야 하는 값만 일반 칸으로 둔다. **[결정 필요 D]**
4. **유효 access token 얻기** — 아래 6.2. access token은 메모리에만 두고 DB는 만료가 가까울 때만 읽는다.
5. **해제** — Google·Zoom 쪽 승인 취소(revoke) 호출 후 행 삭제(아래 6.4).

### 6.1 저장: `studio_auth.external_accounts` (2026-10-09 팀 승인, 이름·칸 확정)

- studio에 Google·Zoom refresh token을 오래 둘 자리는 없었다. `studio_auth.sessions.token_cipher`는 Supabase 로그인 토큰이고(Google 로그인도 `access_type: online`이라 Google refresh token을 받지 않는다) 로그아웃·7일·8시간 유휴로 폐기된다. `studio_auth.requests`는 10분 일회용이다. 연결은 로그인과 수명이 분리돼야 한다(로그아웃해도 새벽 마감 작업이 써야 한다).
- `studio_auth`(같은 PostgreSQL 안의 비공개 인증 스키마)라 "제품 테이블은 `studio` 8개" 규칙 안이다.
- 이름: 테이블 `external_accounts`(교수자가 연결한 외부 계정), 칸 `platform`(`'google'`·`'zoom'`). `provider`는 studio에서 이미 로그인 방식(`signInWithOAuth({ provider })`)을 뜻하고, `linked`·`identity`는 Supabase 로그인 계정 연결 기능과, `service`는 synsory-api의 Docs·Forms 단위와 겹쳐 쓰지 않는다.
- **칸은 세 개뿐**: `profile_id`·`platform`(기본키, 교수자 × 플랫폼 하나) · `token_cipher`(암호화한 JSON). 정의는 6.5.
  - 끊긴 연결은 표시하지 않고 **행을 지운다**(6.3). "끊겼어요"와 "아직 연결 안 했어요"를 화면에서 구분해야 하면 그때 `reconnect_required_at` 칸을 더한다.
  - `created_at`·`updated_at`·`version`은 두지 않는다. 기능이 읽지 않고, 동시 갱신은 Google은 문제가 없고 Zoom은 행 잠금으로 막는다(6.2).
- `token_cipher` 안의 JSON(플랫폼별 Zod로 검사):
  - google: `{ refresh_token, scope, account_email }`(`account_email`은 연결 계정 표시용, 결정 38). Google 안의 서비스(Drive·Docs·Sheets·Slides·Forms·Meet)는 refresh token 하나를 함께 쓴다(계정 × 앱 단위 승인).
  - zoom: `{ refresh_token, scope, api_url? }`. 갱신마다 refresh token이 바뀐다.
  - 새 플랫폼이 생겨도 테이블은 그대로다(`check` 값만 늘린다).
- 암호화는 studio 세션과 같은 `Secrets.encrypt`(AES-256-GCM, `base64url(IV 12B + 태그 16B + 암호문)`). 평문 `jsonb`는 쓰지 않는다(DB 백업·관리 화면에 토큰이 보인다).
- **키**: 지금은 `SESSION_ENCRYPTION_KEY` 하나다. 세션은 길어야 7일이라 키를 바꾸면 재로그인으로 끝나지만, 연결은 몇 달 살아서 키를 바꾸면 모든 교수자가 다시 연결해야 한다. 연결용 키를 따로 두거나(예: `CONNECTION_ENCRYPTION_KEY`) 암호문 앞에 키 번호를 붙여 옛 키도 읽게 한다. **[결정 필요 D의 일부]**
- 권한: studio는 `studio_auth` 권한을 테이블마다 따로 준다(`0001_integrity.sql`). `studio_api`는 읽기·쓰기·수정·삭제, `studio_worker`는 읽기·수정·삭제(Zoom 갱신 토큰 저장에 수정 필요, 결정 41. 0009는 읽기·삭제만이라 마이그레이션 추가)(갱신 거절 시 삭제). worker의 수정 권한은 Zoom refresh token 교체에만 필요해 Zoom을 붙일 때 더한다. 브라우저 역할 차단은 기존 기본 권한 회수가 적용된다.

### 6.2 토큰 공급: 메모리 캐시, DB는 가끔

- 어댑터는 토큰을 직접 받지 않고 `accessToken: () => Promise<string>`을 받는다(`createGoogleDrive(accessToken)` 등). 이 함수를 studio에서 아래처럼 만든다. 이미 만든 어댑터는 고칠 필요가 없다.
- 프로세스 메모리에 `(profile_id, platform) → { access_token, expires_at }`. 남은 수명이 1분보다 길면 그대로 쓴다(대부분). 아니면 DB에서 `token_cipher`를 읽어 풀고 → provider에 갱신 요청 → 메모리에 저장.
- DB 읽기는 프로세스마다 교수자 × 플랫폼당 대략 1시간에 1번. 그룹 10개 동료평가 폼(Google 호출 약 70회)에서 DB 읽기는 0~1회. 참고로 studio는 지금도 로그인 요청마다 세션 행을 읽는다.
- 한 프로세스 안의 동시 요청(그룹 4개 동시 처리 등)은 진행 중인 갱신 하나를 함께 기다린다(DB 잠금 불필요).
- access token은 DB에 저장하지 않는다(메모리에만). refresh token은 메모리에 오래 들고 있지 않고 필요할 때 DB에서 읽는다(DB가 유일한 원본).
- **Google은 갱신해도 refresh token이 바뀌지 않으므로 갱신 때 DB에 쓰지 않는다.** 그래서 프로세스 간 동시 갱신이 겹쳐도(같은 마감 시각의 작업 여러 개, API와 worker 동시, 서버 여러 대) Google 호출이 한 번 늘 뿐 꼬이지 않는다 → **Google만 붙이는 단계에서는 행 잠금이 필요 없다.**
- **[결정 E] Zoom은 갱신마다 refresh token이 바뀌어 DB에 다시 써야 한다.** 두 곳이 같은 옛 토큰으로 동시에 갱신하면 새 토큰이 두 개 나오고 남은 쪽이 무효일 수 있어 멀쩡한 연결을 끊김으로 잘못 판정할 수 있다. Zoom 갱신 경로에만 행을 `FOR UPDATE`로 잠그고 → 다시 읽어 아직 필요하면 갱신 → 새 refresh token 저장 → 해제한다(studio 세션 갱신과 같은 방식, 교수자당 대략 1시간에 1초 안팎). 잠금은 행 단위 기능이라 칸이 필요 없고 Zoom을 붙일 때 추가하면 된다. 교수자가 다시 연결하는 순간 worker가 갱신 중인 경우도 같은 잠금으로 순서가 정해진다.

### 6.3 다시 연결이 필요한지 판정

교수자가 Google·Zoom 쪽에서 앱 연결을 끊어도 DB의 refresh token은 그대로 있다. 알 수 있는 때는 그 토큰을 쓸 때뿐이다.

| 신호 | 원인 | 처리 |
| --- | --- | --- |
| Google 갱신 400 `invalid_grant` | 사용자가 계정 설정에서 연결 끊음, 테스트 상태 앱 7일, 미사용 6개월, 계정 × 앱 100개 초과(`docs/google_docs.md` 2절) | `external_accounts` 행 삭제 → `EXTERNAL_RECONNECT_REQUIRED` |
| Google API 403 `insufficientPermissions` | 동의 화면에서 Drive 권한을 해제하고 허용 | 같음(권한 부족 사유를 함께 안내) |
| Zoom 갱신 실패(401, `invalid_grant` 계열) | 앱 제거, 90일 미사용 | 같음 |
| API 401(Zoom 본문 `code 124` 포함) | access token 만료·무효 | 메모리 토큰을 버리고 **한 번만** 갱신 후 재시도. 갱신이 위 신호로 실패하면 기록 |
| 429 · `RESOURCE_EXHAUSTED` · 5xx · 네트워크 오류 | 일시적 | **끊김으로 판정하지 않는다.** 기다렸다 재시도 |

- 다시 연결하면 행을 새로 넣는다(이미 있으면 `token_cipher`를 덮어쓴다).
- 끊긴 즉시는 모른다(다음 사용 때 안다). 즉시 알림은 Google Cross-Account Protection(수신 서버 등록·서명 검증 필요), Zoom `app_deauthorized`(게시 앱만, `docs/zoom.md` 9절)로만 가능해 지금은 쓰지 않는다.
- `invalid_grant`가 실제로 오는지는 공식 문서 기준이고 연결을 끊어 실측하지는 않았다(연결을 끊고 갱신해 보면 바로 확인된다).

### 6.4 연결의 수명

| 상황 | 연결 |
| --- | --- |
| 로그아웃, 모든 기기 로그아웃, 세션 만료 | 유지(작업이 계속 돈다) |
| "연결 해제" 버튼, 계정 삭제 | Google·Zoom 쪽 승인 취소(revoke) 후 행 삭제 |
| 수업에서 빠짐 | 연결은 개인 것이라 유지. 그 교수자가 만든 활동은 결정 N에 따라 다른 교수자가 못 다룰 수 있다 |
| 갱신 거절(6.3) | 행 삭제(화면은 "연결하세요") |
| 로그인 이메일과 연결한 Google 계정이 다름 | 허용하되 화면에 연결 계정 이메일을 표시(결정 38). 이메일은 `token_cipher` 안 `account_email` |

### 6.5 테이블 정의(studio `packages/db/src/schema.ts`, 마이그레이션 `0009_external_accounts`)

```ts
export const externalAccounts = internal.table(
  'external_accounts',
  {
    profile_id: uuid()
      .notNull()
      .references(() => profiles.id),
    platform: text().notNull(),
    token_cipher: text().notNull(),
  },
  (t) => [
    primaryKey({ columns: [t.profile_id, t.platform] }),
    check('external_account_platform', sql`${t.platform} in ('google','zoom')`),
  ],
);
```

- `schema.ts`에는 주석을 달지 않는다(파일 관례). 설명은 이 절과 마이그레이션에 둔다.
- 마이그레이션은 `pnpm db:generate`로 만든 SQL·스냅샷·저널에 권한 부여를 덧붙인다(6.1 권한). `schema.ts`와 같은 커밋.
- `check`에 `'zoom'`을 미리 넣었다(Zoom은 팀원 담당으로 확정, 나중에 제약 변경 마이그레이션이 필요 없게).

알아둘 제약(synsory-api 실측·공식 문서):

- Google 동의 화면이 "테스트" 상태면 refresh token 7일 만료. refresh token은 계정 × 클라이언트당 100개, 초과 시 오래된 것부터 무효.
- Zoom 리다이렉트 URI는 https 필수(`http://localhost` 불가). studio 로컬(`localhost:5173`)에서 Zoom 연결을 받으려면 ngrok 같은 터널이 필요. **[결정 필요 F]**
- Drive 연결용 Google client secret은 Supabase가 아닌 앱 env에 둬야 한다. studio `.env.dev.local.example`의 "Google secret은 Supabase에만" 원칙의 예외. **[결정 필요 G]**
- Picker는 브라우저에 access token이 필요하다(`docs/google_drive.md` 2.1절). **결정 H 확정(2026-10-09, 상현): Picker를 열 때만 서버가 그 교수자의 짧은 수명 access token을 내려준다.** studio-port 이식분: `contracts` `pickerSession`·`pickedFiles`, `application` `acceptPickedFiles`(서버가 볼 수 있는지·템플릿 종류인지 확인), `infrastructure` `pickerAppId`, `ui` `pickGoogleFiles`(브라우저, 토큰은 인자로만). studio에서 할 것과 지킬 것:
  - 세션 API(예: `GET /api/connections/google/picker-session`)는 교수자 세션·CSRF 확인 뒤 응답하고 `Cache-Control: no-store`. 남은 수명이 짧으면(예: 5분 미만) 갱신 후 준다. refresh token은 절대 내려주지 않는다.
  - 브라우저는 토큰을 메모리에만 두고 Picker를 닫으면 버린다(웹 저장소 금지). revoke하지 않는다(같은 프로젝트의 서버 refresh token까지 무효가 된다는 보고, `docs/google_drive.md` 2.1절).
  - 고른 ID(한 파일)는 서버로 보내 `acceptPickedFile`로 확인한 뒤에만 템플릿으로 쓴다.
  - ~~**미확인 위험**~~ → 확인(2026-10-09): studio API는 웹 HTML을 서빙하지 않아 helmet은 API 응답에만 붙는다. CSP·Referrer-Policy는 웹을 서빙하는 쪽의 몫(아래 내용은 그쪽에 적용). 원문: studio API는 `@fastify/helmet`을 전역으로 등록한다. 웹 페이지에도 helmet 헤더가 붙는다면 ① 기본 CSP가 `apis.google.com` 스크립트와 `docs.google.com` iframe을 막고, ② `referrerPolicy: no-referrer` 때문에 Referer 제한을 건 API 키가 "API developer key is invalid"로 거부될 수 있다. 웹을 어떻게 서빙하는지 확인하고, 필요하면 CSP에 두 출처를 추가하고 Picker 페이지의 Referrer-Policy를 `strict-origin-when-cross-origin`으로 둔다(API 키 제한은 앱 도메인 + `https://docs.google.com/*`).
  - GCP: Google Picker API 사용 설정, API 키(웹사이트 제한·Picker API만), `setAppId`는 프로젝트 번호.

## 7. 활동 도구 매핑

| 도구(`activity_type`, 26번 확정) | 근거 서비스 | `external_refs` 항목 | `activity_responses` |
| --- | --- | --- | --- |
| `google_docs` · `google_slides` · `google_sheets` | Docs·Slides·Sheets 유즈케이스 2~4 | 팀마다 `{ id: fileId, provider: 'google', kind, team_id, url, checkpoint_revision }` | 거의 안 씀(파일 배포형). 마감·복원은 `external_refs`를 돌며 권한 변경 |
| `google_forms` (설문·퀴즈·동료평가는 `config.mode`로 구분, 26번 확정) | Forms | 폼마다 `{ id: formId, team_id?, responder_url, reviewees?, cursor, checkpoint_revision }` | `source_key` = Forms `responseId`, `payload` = FormSubmission, `identity` = `respondent_email` → 명단 이메일로 매칭 |
| `zoom_meeting` | Zoom | 미팅마다 `{ id: meetingId, team_id?, join_url, occurrences? }` | `source_key` = `participant_uuid`(또는 미팅 uuid + participant_uuid), `identity` = 표시 이름 속 학번 |

- 팀 정보는 studio의 팀 스냅샷(`activities.config.team_snapshot` = `{ id, name, student_ids }[]`)에서 온다. 스냅샷에는 이메일이 없으므로 공유·응답자 지정 때 `course_members`에서 한 번에 조회한다(N+1 금지).
- studio의 `canChangeStructure`는 `external_refs`가 비어 있을 때만 구조 변경을 허용한다. 외부 파일을 만든 뒤에는 팀 구성을 바꿀 수 없다는 synsory-api 전제와 맞는다.
- Zoom 출석의 학번 매칭은 studio 명단에 학번이 있어야 한다. 현재 `studio.profiles`에는 `display_name`만 있다. **[결정 필요 J]**

## 8. 큐 · 수집 · 웹훅

- **Forms 응답 수집**: 작업 `google-forms-collect`, group = 폼 ID. 작업이 `listResponses(formId, since=cursor)` → **100개씩** `CollectionService.commit(…, { resource_id, checkpoint_revision, payloads, next_cursor, page_complete })`. 100은 studio `packages/application/src/collection.ts`의 제약이다(`payloads.length <= 100`, 합계 1MB, 초과 시 `BATCH_TOO_LARGE` 413). Drive 공유 배치의 100(요청 하나에 permissions 100개)과는 다른 숫자다. `since`는 `>=`라 경계 응답이 다시 오지만 `unique(activity_id, source_key)`가 멱등 처리한다.
- **퀴즈 점수**: `lastSubmittedTime`이 채점 변경을 반영하지 않으므로 커서 없이 전체 재조회한다. 같은 `source_key`로 다시 저장되면 studio가 `revision`을 올린다.
- **폴링 주기**: Forms 응답 목록은 "비싼 읽기"(사용자당 분당 180). 활동이 `open`인 동안만 돌린다. 주기 **[결정 필요 K]**.
- **Zoom 웹훅**: `POST /api/webhooks/zoom`. 이 라우트만 Fastify JSON 파싱 전 **원본 바이트**를 받아 서명 검증(`v0:{ts}:{raw body}` HMAC-SHA256, 상수 시간 비교) → `endpoint.url_validation`이면 CRC 응답(3초 안) → 그 밖은 큐에 넣고 즉시 204. 처리는 worker에서. 72시간마다 재검증, 6회 연속 실패 시 구독 중지.
- 외부 HTTP 호출은 DB 트랜잭션 밖에서 한다. 결과 저장만 짧은 트랜잭션으로.
- **Google 활동 작업(2026-10-10 구현)**: 큐 하나 `google-activity`, 작업 종류는 `data.kind`(provision·close·reopen), group = 활동 ID. pg-boss의 그룹 동시성은 **큐 이름 단위**이고, 전역(`groupConcurrency`) 필터는 동시 fetch에 **원자적이지 않다**(2차 검토 실측). 그래서 `localGroupConcurrency: 1`(프로세스 안 직렬화)을 쓰고 refs 쓰기는 행 잠금 안에서 병합하며, worker는 1개 인스턴스를 전제한다. `singletonKey`는 standard 큐에서 효과가 없어 쓰지 않는다. 상태 전환과 같은 트랜잭션에서 enqueue(`ActivityJobs` 훅), 재시도 3회·30초, 실패는 `jobFailure` 구조화 로그.

### 8.1 동시 처리 (2026-10-09 실측·반영)

- 서로 다른 파일·미팅을 만드는 일(그룹마다·파일마다)은 동시에 4개씩 처리한다(`application/src/concurrency.ts` `mapConcurrently`). 6개 조 실측: Forms 동료평가 순차 86.7초 → 동시 3개 27.8초 → 동시 6개 14.7초, Docs 그룹 문서 34.3초 → 14.0초 → 6.3초. 호출당 평균 1.2~2초는 동시 수와 무관했고 한도 오류는 없었다.
- **같은 파일의 권한 변경은 동시에 하지 않는다**(Drive 공식: 동시 수정 미지원, 마지막 쓰기만 남음). 조원 공유는 Drive 배치 요청 하나, 권한 낮추기·되돌리기는 순서대로. 배치는 한 명만 실패해도 전체가 실패해 실패한 사람만 단건 재시도한다(`docs/google_drive.md` 10절).
- 그래도 조가 많으면 수십 초~분 단위라, 그룹 생성은 HTTP 요청 안이 아니라 worker 작업으로 돌리는 것을 권한다(브랜치 작업 전 결정 ③).

## 9. Python → TypeScript 변환표

| Python (synsory-api) | TypeScript (studio) |
| --- | --- |
| pydantic `BaseModel`, `StrEnum` | Zod 스키마 + `z.infer`, 문자열 유니온 |
| `@dataclass` 결과 객체 | `type` 별칭(객체 리터럴) |
| `httpx.AsyncClient` | `fetch` (Node 24 내장). 타임아웃은 `AbortSignal.timeout(ms)` |
| `XApiError(Exception)` | `class ExternalApiError extends Error` → 경계에서 `AppError` |
| `datetime.fromisoformat`, aware datetime | `new Date(iso)`. Zoom `start_time`은 UTC `Z` 문자열 + `timezone` 필드 |
| `hmac.new(...).hexdigest()`, `hmac.compare_digest` | `createHmac('sha256', secret).update(raw).digest('hex')`, `timingSafeEqual` (`node:crypto`, infrastructure에서만) |
| `re` 정규식 | JS 정규식 (학번 `\d{8}`, 템플릿 `{{ key }}`) |
| `openpyxl` (xlsx 내보내기) | 옮기지 않는다. Forms 12는 CSV만(결정 30, 2026-10-09). Python 쪽 xlsx도 삭제 |
| FastAPI `Depends`, `HTTPException` | 없음. application 함수가 port를 인자로 받고 `AppError`를 던진다 |
| `dict.get("a", {}).get("b")` | Zod 파싱 후 접근, 또는 `?.` + `noUncheckedIndexedAccess` 대응 |

## 10. 결정 대장 (확정 · 미정 · 보류)

2026-10-09 정리. studio 이식에 관련된 결정을 정해진 것까지 한 곳에 모은다. 상태는 **확정** / **제안·미승인**(이 레포가 한 방향으로 구현했고 studio 담당자 승인만 남음) / **미정** / **보류**(필요해질 때까지 안 정함). 서비스별 유즈케이스·동작 방식의 상세는 각 `docs/<service>.md` 1절·10절, 진행 상황은 `docs/PLAN.md`. 결정이 바뀌면 이 표의 행을 고치고 날짜를 적는다.

### 10.1 전제·범위

| # | 항목 | 상태 | 내용 |
| --- | --- | --- | --- |
| 1 | 인증 방식 | 확정 | OAuth 2.0 사용자 동의. 서비스 계정·Server-to-Server 안 씀 |
| 2 | 스택 | 확정(2026-10-08) | synsory-api는 Python 유지, studio에 TS로 재작성. Google SDK 미사용, REST를 `fetch`로 직접 호출 |
| 3 | Drive scope | 확정 | `drive.file` 하나. Docs·Sheets·Slides·Forms 전 메서드가 이걸로 동작(실측). `drive`(제한 scope)는 안 씀 |
| 4 | 기존 파일 접근 | 확정(2026-10-04) | Google Picker로 사용자가 고름. 원본 템플릿은 수정하지 않고 복사본만 치환 |
| 5 | 담당 분담 | 확정(2026-10-09 팀) | Google 도구는 상현, Zoom 등 비 Google은 팀원. 상현이 studio 브랜치를 열고 PR 회의로 결정 |
| 6 | studio 외부 도구 범위 | 확정(2026-10-09) | studio `TODO.md` 1절에 "외부 도구 작업 시작" 명시. `activity_type_allowed`는 아직 빈 배열(26번과 함께 변경) |
| 7 | Google Meet | 확정(방향, 2026-10-06) | Calendar 없이 Meet 단독, 출석 포함. 유즈케이스 초안 4개는 상현 확인 대기 |
| 8 | Google Calendar | 보류 | Meet 단독으로 가기로 해서 1단계만 하고 중단 |
| 9 | Sheets 성적표 동기화 | 보류 | 성적 원본은 Synsory DB. 교수자 요구가 확인되면 내보내기부터(`docs/google_sheets.md` 1.3절) |
| 9a | 명단 이메일은 Google 계정 | 확정(2026-10-09 상현) | Drive 공유는 알림 없이 하고(`shareWithUsers` 옵션 없음) 비 Google 주소는 그 사람만 실패로 기록한다. studio 명단 안내 문구 필요. 비 Google 주소가 실제로 들어오면 알림 켜기(`sendNotificationEmail=true`)를 실측한 뒤 재검토 |

### 10.2 유즈케이스·동작 방식

| # | 항목 | 상태 | 내용 |
| --- | --- | --- | --- |
| 10 | Docs 유즈케이스 | 확정 | 4개(텍스트로 생성·그룹 문서·마감·내보내기) + Google Doc 템플릿 경로(Picker, `template_document_id`) |
| 11 | Docs 마감 방식 | 확정(2026-10-03) | `permissions.update`로 학생 권한 낮추기. `contentRestrictions` 잠금은 소유자 API도 막혀 제외 |
| 12 | Docs 본문 생성 | 확정 | Markdown 변환 업로드(Drive). `batchUpdate` 인덱스 방식보다 우월 |
| 13 | Slides 유즈케이스 | 확정(2026-10-04) | Docs와 같은 4개. pptx 1회 변환 업로드 → 그룹마다 `files.copy` → `replaceAllText` |
| 14 | Sheets 유즈케이스 | 확정(2026-10-04, 2026-10-09 축소) | Docs·Slides와 같은 4개("마감 후 값 읽기" 5번은 2026-10-09 삭제: 당장 불필요). xlsx 변환 → `files.copy` → `findReplace`(수식 포함). 값 쓰기 기본 `RAW`(학번 앞자리 0 보존) |
| 15 | Sheets 보호 범위 | 확정 | `editors.users`를 항상 명시(생략 시 학생도 편집 가능) |
| 16 | Forms 유즈케이스 | 확정(2026-10-06) | 13개. 항상 `unpublished=true`로 만들고 질문을 넣은 뒤 게시. 자동 부여되는 `anyoneWithLink` 삭제. 응답은 폴링, 시트는 사본 내보내기 |
| 17 | 0 시작 척도 | 확정(버그 수정) | `low` 생략 시 기본 0. Python·TS 모두 수정(`docs/google_forms.md` 10절 20항) |
| 18 | 그룹 파일 공통 흐름 | 확정(2026-10-09) | 서비스별 함수 없이 `createGroupFilesFromTemplate` + 각 port의 `replaceTags`, 텍스트 템플릿은 `createGroupFilesFromContent` |
| 19 | 호출 효율 | 확정(2026-10-09 실측, 8.1절) | 파일·그룹 생성은 동시 4개. 같은 파일 권한 변경은 순차, 조원 공유는 Drive 배치 1회, 배치 실패 시 실패한 사람만 단건 재시도 |
| 20 | Sheets 유즈케이스 5의 `source_key` | 삭제(2026-10-09 상현) | 유즈케이스 5 자체를 뺐다(14번). `readValues`·`SheetValues`·`read_sheet_values`·`get_values`를 TS·Python에서 제거. 원래 메모: | "파일 ID"로 가정만(`docs/google_sheets.md` 11.x) |
| 21 | Forms 12 xlsx 내보내기 | 확정(2026-10-09 상현) | **CSV만.** Python·TS 모두 xlsx 제거(30번). 이전 메모: | 30번(xlsx 라이브러리) 뒤. CSV만 쓸 거면 닫을 수 있음 |

### 10.3 studio 배치·코드 구조

| # | 항목 | 상태 | 내용 |
| --- | --- | --- | --- |
| 22 | 층 대응 | 확정(studio-port 구현, 2026-10-09 표현 수정) | client → infrastructure 어댑터, usecases의 흐름 → application(port 주입), mapper는 형식 변환 → infrastructure · Synsory 규칙·payload 스키마 → domain으로 갈림, `core/models.py` → **domain**(`externalDocument`·`FormSubmission`·`Meeting`). contracts에는 브라우저가 보는 것만(Picker 세션 23줄이 전부). 근거: I/O는 infrastructure(AGENTS.md), `ToolHandler`가 domain에 있어 payload·집계는 domain, 흐름은 HTTP·worker 양쪽이 공유해야 해서 application(2~4절) |
| 23 | A. mapper 위치 | 확정(2026-10-09 상현) | **현행 유지**: 응답 형식 변환은 infrastructure 어댑터 안(Google JSON 모양은 바깥 층에 가둠, application·domain은 깨끗한 타입만 봄), 계산·규칙은 domain. 이유: Google에는 "문서 하나"를 통째로 주는 API가 없어 Docs+Drive 응답을 합친 모양은 우리 것, Google 함정(빈 grade·`low` 생략·휴지통 200)을 한 곳에서 보정, 이메일 등 개인정보를 걸러 저장, studio도 경계에서 자기 모양으로 바꾸는 방식(`ToolHandler.validateResponse`). **단, 필드는 studio가 실제 쓰는 것만 남긴다**: `externalDocument` 13개 중 application이 쓰는 건 `title`·`kind`·`trashed`뿐이고 `text`·`mime_type`·`created_at`·`modified_at`은 미사용. studio에 넣을 때 `external_refs` 항목(7절)에 맞춰 줄인다. 시점: 2단계는 원본 그대로 복사했고 축소는 5단계(흐름이 쓰는 필드 확정 뒤) |
| 24 | B. 하위 폴더 | 제안·미승인 | 평평한 파일(studio 관례, 3절). 현행 유지 가능 |
| 25 | C. 외부 오류 코드 이름 | 제안·미승인 | `ExternalApiError extends AppError`, `details`는 `status`·`reason`·`api_status`만(5절). 코드도 같다(2026-10-09 `zoom_code`를 details에서 뺌. `zoomCode` 속성은 연결 계층의 401 판정용으로 남김) |
| 26 | I. `activity_type` 이름 · Forms 분할 | 확정(2026-10-09 상현) | **서비스마다 도구 하나, 4개**: `google_docs` · `google_slides` · `google_sheets` · `google_forms`(설문·퀴즈·동료평가는 `config.mode`로 구분). 이유: 확장성·통일성. 이름은 `zoom_meeting`과 같은 snake_case. `activity_type_allowed` 마이그레이션에 이 4개 + Zoom. 이전 안:  `google_docs`·`google_slides`·`google_sheets`·`google_forms` 가칭(7절). 설문·퀴즈·동료평가를 도구로 나눌지 `config`로 구분할지. `activity_type_allowed` 마이그레이션에 바로 들어감 |
| 27 | N. 외부 파일·미팅을 누구 계정으로 다루나 | 확정(2026-10-09 상현) | **활동을 만든 교수자의 연결로 실행**(`external_refs`에 `profile_id` 기록, 이후 마감·수정도 그 연결). 교수자가 수업에서 빠지거나 연결을 끊는 상황은 지금 상정하지 않고 **기획 회의**에서 정한다. 원래 분석:  studio는 한 수업에 교수자가 여럿이고 권한이 같은데, 교수자 A의 연결로 만든 파일은 A 소유다. `drive.file`은 "이 사용자가 이 앱으로 만들었거나 고른 파일"에만 적용되므로 B의 토큰으로는 마감·수정이 안 될 가능성이 높다(Google 계정 2개 실측 미완). 방안: ① 활동마다 만든 교수자의 연결(`profile_id`)을 `external_refs`에 기록하고 이후 작업도 그 연결로 실행(**추천**. 그 교수자가 연결을 끊거나 수업에서 빠지면 `EXTERNAL_RECONNECT_REQUIRED` 안내 필요) ② 수업마다 공용 연결 하나(관리 화면·새 개념 필요) ③ 누르는 사람 계정으로 실행(남이 만든 파일에서 실패) |
| 28 | O. 오래 걸리는 생성 작업의 위치 | 확정(2026-10-09 상현): **worker(pg-boss)**. 요청은 작업 등록만, 그룹 하나 = 작업 하나, 화면은 진행 상태. 미팅 하나 수정 같은 짧은 동작은 요청 안에서. (맥락: 다른 세션에서 논의한 "배치 요청"은 Drive 공유 배치(요청 하나에 permissions 100개)이고 8.1절 실측 수치는 이미 그 배치 + 동시 4개를 적용한 값이다. 즉 배치로는 더 줄일 수 없고, 남는 것은 그룹당 복사 1 + 치환 1 + 공유 1 호출의 지연이다) | 실측(6개 조, 8.1절): 호출당 1.2~2초, 순차면 Forms 동료평가 87초·Docs 34초, 동시 6개로도 15초·6초. 조가 많으면 분 단위. 방안: ① 요청 안에서 처리(단순. 타임아웃·중간 실패 시 일부만 생성·새로고침 중복 위험) ② 요청은 작업 등록만 하고 worker(pg-boss)가 처리, 화면은 진행 상태(**추천**. 재시도·중복 방지는 큐가 맡고, 그룹 하나를 작업 하나로 나누면 흐름 코드는 그대로. 미팅 하나 수정처럼 짧은 동작은 요청 안에서) |
| 29 | K. Forms 응답 폴링 주기 | 확정(방향, 2026-10-09 상현) | **실시간(on-demand 리더보드)은 범위 밖.** 그래서 짧은 주기 폴링이 필요 없다. 제안: 마감 시각 작업에서 전체 재조회 1회 + 교수자가 결과 화면을 열 때 "새로고침"으로 수동 수집, open 중 주기 폴링은 두지 않거나 길게(예: 30분, 가정). 수치는 studio 화면 설계 때. 원래 메모:  open 활동만 돌린다는 원칙만(8절). 수치 없음. 응답 목록은 비싼 읽기(사용자당 분당 180) |
| 30 | L. xlsx 라이브러리 | 확정(2026-10-09 상현) | **추가하지 않는다.** Forms 12는 CSV(UTF-8 BOM, Excel에서 바로 열림)만, 스프레드시트는 13번 시트 내보내기로. 9절 변환표 반영 |
| 31 | M. 외부 오류 원문 로그 | 확정(2026-10-09 상현) | **외부 오류만 구조화 로그로 남긴다**: `request_id`(worker는 job id)·provider·`status`·`reason`·`api_status`·`external_message`(이메일·파일 ID를 가린 뒤). studio 로거는 `err.message`를 `'redacted'`로 바꾸므로 이 필드를 따로 찍어야 원인을 볼 수 있다. API 응답 `details`에는 지금처럼 넣지 않는다. studio 쪽 구현(오류 핸들러·worker). 원래 질문: | `ExternalApiError.externalMessage`를 남길지, 이메일을 가린 뒤 남길지. studio 규칙은 "원본 응답·개인정보 로그 금지"(5절) |

### 10.4 외부 계정 연결·토큰

| # | 항목 | 상태 | 내용 |
| --- | --- | --- | --- |
| 32 | 연결 흐름 | 확정(설계, 6절) | Supabase 로그인과 별개 "Google/Zoom 연결" 흐름. `studio_auth.requests`에 state 10분, `access_type=offline&prompt=consent` |
| 33 | D. 토큰 저장 | 확정(2026-10-09 팀 승인, studio 반영) | `studio_auth.external_accounts(profile_id, platform, token_cipher)` 3칸(6.1·6.5). studio 커밋 a03a27f 마이그레이션 `0009_external_accounts`. 읽고 쓰는 코드는 아직 없음 |
| 34 | 끊김 판정 | 확정(6.3) | `invalid_grant`·403 `insufficientPermissions`면 행 삭제 → `EXTERNAL_RECONNECT_REQUIRED`. 429·5xx는 끊김 아님. 다음 사용 때 알게 되면 재연결 안내 |
| 35 | E. 갱신 동시성 | 확정(2026-10-09) | access token은 메모리 캐시(6.2). Google은 잠금 불필요(refresh token이 안 바뀜), Zoom 갱신 경로에만 `FOR UPDATE` 행 잠금. 경과: 낙관적 갱신 → 행 잠금 → Google·Zoom 구분 |
| 36 | H. Picker 토큰 | 확정(2026-10-09) | 서버가 Picker를 열 때만 짧은 수명 access token 전달, 브라우저는 메모리만, revoke 안 함, 고른 ID는 `acceptPickedFiles`로 검증(6절 Picker 항목) |
| 37 | D 잔여: 암호화 키 분리 | 확정(2026-10-09 상현) | **분리하지 않는다.** `SESSION_ENCRYPTION_KEY` 하나로 세션과 연결 토큰을 같이 잠근다. 키를 바꿀 계획이 생기면 그때 암호문에 키 번호를 붙이는 방식을 더한다. 원래 메모: | 세션 키(`SESSION_ENCRYPTION_KEY`)를 같이 쓸지, 연결용 키를 따로 둘지(키 교체 시 전원 재연결, 6.1) |
| 38 | D 잔여: 로그인 이메일 ≠ 연결 계정 | 확정(2026-10-09 상현) | **허용하되 화면에 연결 계정 이메일을 표시한다.** 그래서 연결 계정 이메일을 저장한다: `token_cipher.google.account_email`(암호문 안, 6.1에 다시 넣음). 거절하면 KAIST 메일이 Google 계정이 아닐 때 막히고, 조용히 허용하면 어느 Drive에 파일이 생겼는지 모른다 |
| 39 | G. client secret 위치 | 확정(2026-10-09 상현) | **앱 env에 둔다.** studio 앱 env에는 이미 더 위험한 `SUPABASE_SECRET_KEY`·`SESSION_ENCRYPTION_KEY`가 있고, "Google secret은 Supabase에만"은 로그인용 secret의 중복 저장 금지라 Drive 연결용(다른 OAuth 클라이언트)은 해당 없음. 조건: ① **환경별 OAuth 클라이언트**(local·dev·prod 각각 자기 ID·secret·리다이렉트 URI. 하나가 새도 그 환경만, prod에는 localhost 미등록) ② `.env.dev.local.example` 문구를 "로그인용은 Supabase, Drive 연결용은 앱 env"로 ③ 교체 절차(새 secret 추가 → env 교체 → 옛것 비활성화) 한 줄. 검토한 대안: Supabase Edge Function(코드가 갈라지고 worker 갱신마다 호출), 로그인에 scope 얹기(갱신에 결국 secret 필요), PKCE(서버형 불가), 비밀 관리 서비스(배포 방식 미정, 주입처만 바뀜) |
| 40 | GCP 프로젝트·동의 화면 공유 | 확정(2026-10-09 상현) | **로그인용과 같은 GCP 프로젝트**에 "Drive 연결용" OAuth 클라이언트(39번대로 환경별)와 Picker API 키를 만든다. 확인할 것: 로그인용 프로젝트 소유(상현 개인/Synsory 조직). 실측용 프로젝트는 synsory-api에 그대로. 교수자가 실제로 쓰기 전에 프로젝트를 프로덕션으로 전환(`drive.file`은 비민감이라 심사 없음. 테스트 상태면 refresh token 7일 만료·테스트 사용자 100명). 경과: ~~공유하면 로그인 사용자도 재동의 영향~~ → 틀림: 동의 화면은 **그 요청이 묻는 scope만** 보여주고, Drive는 교수자가 첫 Google 활동을 만들 때 따로 요청하므로(on-demand) 학생 로그인 화면에는 Drive가 나오지 않는다. 남는 차이는 관리뿐: 같은 프로젝트면 브랜드·동의 화면·프로덕션 전환이 한 곳(그 안에 "Drive 연결용" OAuth 클라이언트를 따로 만든다), 다른 프로젝트면 두 곳. 어느 쪽이든 **첫 Google 활동 생성 때 동의**(409 `EXTERNAL_RECONNECT_REQUIRED` → 연결 시작 URL → 콜백 → 작성 화면 복귀) |
| 41 | worker 권한 | 확정(2026-10-09 상현, 2026-10-12 보강) | **`studio_worker`에 `external_accounts` UPDATE**(0010, Zoom 갱신 토큰 저장용, 35번). 추가로 수집이 `courses.member()`의 `FOR SHARE`를 거쳐 **`course_members`의 `updated_at` 열 하나에만 UPDATE**(0011). 행 잠금은 한 열의 UPDATE로 충분함을 실측. 근본 대안(수집 경로에서 사람 Actor 전제를 없애는 `commit` 시스템 호출자 경로)은 PR 회의 안건 |
| 42 | F. Zoom https 리다이렉트 로컬 수신 | 팀원 파트(2026-10-09 상현) | 상현 범위 밖. ngrok 고정 도메인·학교망 차단·앱 재설치 뒤 웹훅 수신 경험만 전달(`docs/zoom.md` 2.1절) |
| 43 | J. 명단 학번 필드 | 팀원 파트(2026-10-09 상현) | Zoom 출석용이라 상현 범위 밖. `studio.profiles`는 `display_name`만이고 공용 테이블이라 PR 회의 안건(7절) |

### 10.5 실측·확인 보류 (결정이 아니라 확인)

| # | 항목 | 시점 |
| --- | --- | --- |
| 44 | helmet CSP·`no-referrer`가 Picker를 막는지 | 브랜치 작업 중. studio `apps/api/src/app.ts`에 전역 `referrerPolicy: no-referrer` 확인됨(6절 Picker 항목) |
| 45 | Picker 후 Sheets·Docs 템플릿 복사, 태그 든 원본 재복사 | 다음 Picker 실측(`docs/google_drive.md` 12절) |
| 46 | Picker 접근 권한의 며칠 뒤 장기 유지 | 핸드오프 전 |
| 47 | `invalid_grant` 실제 발생 | 연결 끊고 갱신 1회(6.3) |
| 48 | 2026년 쿼터 초과 과금 시행 | 핸드오프 직전(Docs·Sheets·Forms 공통) |
| 49 | Drive 일일 공유 횟수 제한 | 대규모 액티비티 전 |
| 50 | 교수자가 웹에서 만든 사본·옮긴 파일의 앱 접근 | 필요 시(`docs/google_docs.md` 12절) |

브랜치를 열기 전에 정할 것은 코드 골격을 가르는 26·27·28번이다. 24·25번은 "현행 유지" 승인만 받으면 닫힌다. 나머지 미정은 PR 회의 안건으로 넘긴다.

### 10.6 karpathy 재검토(2026-10-09) 처리 현황

이식 코드에서 "Python에 있어서 따라왔지만 아무도 안 쓰는 것"을 찾아 정리했다. 기준은 application 흐름의 호출 유무(grep).

- **① 삭제 완료**(vitest 92 → 87, 동작 불변): Sheets `lockRanges`·`unlockRanges`와 GridRange 헬퍼(보류 기능), Drive `listFiles`(디버그용)·`listPermissions`의 `includePublishedView`(미구현 흐름용), Zoom `createBreakoutMeeting`(B 비교안)·`MeetingSchedule.settings`; 한 값으로만 쓰던 인자 `removeLinkAccess`·`excludeSelf`·`includeEmail`·`studentIdPattern`·`toRole`·`mapConcurrently(limit)`·`timeoutMs`·`shareWithUsers(role)`·`Sheets.create(sheetTitles)`; 읽지 않는 필드 `FormStructure.linked_sheet_id`·`revision_id`, `DrivePermission.display_name`·`view`, `Meeting.status`·`timezone`·`host_id`, `SheetInfo.hidden`, `SheetValues.range`; `ExternalApiError.rateLimited` getter와 `details.zoom_code`(5절과 불일치); 어댑터 내부 함수 export 8개. 각 서비스 문서 11.x에 반영.
- **② 문서·규칙 수정**: (완료 2026-10-09) `CLAUDE.md` 규칙 3개 수정, Python 미사용 코드 삭제(Drive client 5개 메서드 + `expiration_time`·`from_folder_id` 인자, Sheets 2개, Forms 1개, `Meeting.has_recording`·`has_transcript`. pytest 91 통과. `list_app_files`·`create_empty_native_file`은 실측 보조라 유지, Docs 비교용 B는 ③). (완료) 문서의 추측값 2개(`account_email` 선저장, "하루 전 갱신 점검")와 zoom.md 1절의 "대기실·호스트 전 입장"(코드·샘플에 없던 문구)을 삭제. "100개씩 commit"은 재검토 보고가 "근거 없음"이라 했으나 studio `collection.ts`의 실제 제약(≤100, 1MB)이어서 지웠다가 되돌렸다(8절). 원래 목록: `CLAUDE.md`의 "Document의 owner·created_at·modified_at·url은 Drive files.get에서 온다"(13필드 모델의 근원 → "흐름이 쓰는 필드가 필요할 때만 조회"로), "google_docs 폴더를 복사해서 시작"(미사용 client 메서드를 퍼뜨림 → "유즈케이스가 부르는 메서드만 남긴다" 추가), Drive 호출 목록의 `changes.watch`; 6.1 `account_email` 선저장(38번 미정인데 데이터 먼저), 6.3 "하루 전 갱신 점검"(요구 없는 선제 기능), 8절 "100개씩 commit"(근거 없음); 7절 `external_refs` 항목(`checkpoint_revision`·`cursor` 등은 studio 확인 전 가정); zoom.md 1절 유즈케이스 2 "대기실·호스트 전 입장" 기본값이 코드에 없음(구현할지 문서를 고칠지). Python 쪽 미사용 코드: Drive client `rename_file`·`delete_file`·`set_read_only`·`get_start_page_token`·`list_changes`·`share_with_user(expiration_time)`·`move_file(from_folder_id)`, Sheets `batch_update_values`·`append_values`, Forms `get_response`, `Meeting.has_recording`·`has_transcript`, Docs 비교용 B `create_document_with_docs_api`.
- **③ 확인(2026-10-09 상현)**: (완료) Picker는 한 파일(`pickGoogleFile`·`pickedFile`·`acceptPickedFile`), `ExportFormat`은 각 서비스 1절 표대로 10종(Docs md·html·txt 삭제), Drive `docx` 업로드는 Docs 템플릿 경로로 **지원**(google_docs.md 1절), `FormSubmission.created_at`은 TS·Python 모두 삭제. 공유 `notify`·`shareMessage` 옵션은 **삭제**(상현: 명단 이메일은 Google 계정 전제. 비 Google 주소는 그 사람만 실패로 기록. 비 Google 주소가 실제로 들어오면 그때 알림 켜기를 실측). ③ 완료.

## 11. 서비스별 "studio 이식" 하위절 형식

각 `docs/<service>.md` 11절 끝에 아래 형식으로 붙인다.

```
### 11.x studio 이식

1. 파일 대응: 이 서비스의 Python 함수 → studio 파일·함수 (3절 배치안 기준)
2. port 메서드: 인터페이스 이름, 메서드 시그니처, 대응하는 synsory-api client 메서드와 외부 엔드포인트
3. 도구 매핑: activity_type, config 키, external_refs 항목, source_key·identity (7절 표의 이 서비스 행 상세)
4. 큐 작업: 작업 이름, group 키, 주기·트리거, 커서 위치
5. 테스트: samples → tests/fixtures 목록, pytest 케이스 → vitest 케이스 목록
```
