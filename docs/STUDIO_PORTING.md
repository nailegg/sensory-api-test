# synsory-studio 이식 공통 가이드

작성일: 2026-10-08 · 작성자: 상현 · 상태: **초안. studio 담당자 확인 전**

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
| `client.py` + usecases 안의 요청 본문 생성 함수(`replace_tag_requests`, `build_setup_requests`, `protect_range_requests`, `peer_review_items` 등) + mapper의 **응답 형식 변환** | `infrastructure`의 서비스 어댑터. application에는 "태그 치환", "폼 만들기"처럼 의미 단위 메서드만 보인다 |
| mapper·usecases 안의 **순수 Synsory 규칙**(`summarize`, `summarize_peer_reviews`, `summarize_attendance`, `render_template`) | `domain` |
| usecases의 **흐름**(그룹마다 복사→치환→공유, 미게시 생성→게시→응답자 제한, 수집 커서) | `application` |
| `core/models.py` | 저장 형식(payload, `external_refs` 항목) Zod 스키마는 `domain`, 화면 DTO는 `contracts` |

**[결정 필요 A]** 응답 형식 변환(mapper)을 infrastructure에 두는 이 안은 `CLAUDE.md`의 첫 대응표("mapper → domain")를 구체화한 것이다. domain은 `contracts`를 import할 수 없으므로 `ToolHandler.validateResponse`가 쓰는 payload 스키마는 domain에 있어야 하고, Google 응답 모양은 바깥 층에 가두는 편이 경계가 깔끔하다.

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
  zoom.ts
  zoom-webhook.ts          # CRC 응답, 서명 검증 (node:crypto)
  integration-jobs.ts      # 수집·웹훅 처리 큐 작업 스키마와 enqueue (queue.ts 패턴)

packages/contracts/src/index.ts   # 연결 상태, 도구 설정 입력, 결과 DTO
packages/db/src/schema.ts         # studio_auth.provider_connections + 마이그레이션
apps/api/src/app.ts               # 연결 라우트, Zoom 웹훅 라우트, 도구 동작 라우트
apps/worker/src/main.ts           # 수집·웹훅 작업 등록
tests/fixtures/                   # synsory-api samples/*.json, 가짜 port
tests/unit/                       # pytest 케이스의 vitest 번역
```

## 4. port 설계

- port는 서비스 단위 인터페이스이고, 메서드는 **의미 단위**다. 예: `GoogleDocsPort.replaceTags(docId, vars) → Record<string, number>`, `GoogleFormsPort.listResponses(formId, since) → { submissions, cursor }`. Google 요청 본문 모양은 port 뒤로 숨는다.
- 토큰은 메서드 인자로 넘기지 않는다. application이 `IntegrationFactory.google(profileId)`로 그 교수자의 토큰이 묶인 port 묶음을 받는다. 토큰 꺼내기·갱신은 팩토리 안(infrastructure)에서 `connections`를 통해 한다.
- 반환값은 domain 타입(또는 단순 객체)이다. Google 응답 원문을 application으로 올리지 않는다.
- synsory-api 테스트의 `FakeDrive`·`FakeForms` 등이 곧 이 port의 가짜 구현이다(`tests/fixtures`).

## 5. 오류 변환

synsory-api의 `XApiError(status, body, is_rate_limit, reason)`는 infrastructure의 `ExternalApiError`로 옮기고, application 경계에서 `AppError`로 바꾼다. 코드 이름 제안 **[결정 필요 C]**:

| 상황 | 판별 (synsory-api 근거) | AppError code · status |
| --- | --- | --- |
| rate limit | 429, Google `RESOURCE_EXHAUSTED`, Drive `reason` = `rateLimitExceeded`·`userRateLimitExceeded` (Drive는 403도 rate limit일 수 있음) | `EXTERNAL_RATE_LIMITED` 429 |
| 연결 없음 · refresh 실패 | 저장된 연결 없음, refresh 400 `invalid_grant`, Zoom code 124 | `EXTERNAL_RECONNECT_REQUIRED` 409 |
| 파일 접근 불가 | `drive.file`로 앱이 모르는 파일 → 404 (Picker로 고르기 전 템플릿) | `EXTERNAL_NOT_FOUND` 404 |
| 플랜 제한 | Zoom code 200 (유료 전용) | `EXTERNAL_PLAN_REQUIRED` 403 |
| 그 밖의 외부 오류 | 4xx/5xx | `EXTERNAL_FAILED` 502 |

외부 응답 본문은 개인정보가 섞일 수 있어 로그·`details`에 원문을 넣지 않는다.

## 6. 외부 계정 연결 (core/oauth.py · token_store.py 대체)

studio의 Google 로그인(Supabase, `openid email profile`)과 **별개 흐름**이다. Supabase는 provider refresh token을 저장·갱신하지 않기 때문이다. 교수자가 "Google 연결"·"Zoom 연결"을 따로 누른다.

1. **시작** `GET /api/connections/{provider}/start`: state를 `studio_auth.requests`에 `purpose='connect-google'`(또는 `connect-zoom`), browser 해시, 10분 만료로 저장한다. studio Google 로그인이 이미 `purpose='google'`로 같은 방식을 쓴다(`application/src/auth.ts` `googleStart`). 인가 URL 파라미터는 synsory-api 그대로:
   - Google: `access_type=offline`, `prompt=consent`, `include_granted_scopes=true`, scope = Drive `drive.file` (+ 이후 서비스 scope)
   - Zoom: scope는 앱 설정에서 정해지지만 URL에도 넣는다. client 인증은 Basic 헤더
2. **콜백** `GET /api/connections/{provider}/callback`: state를 1회 소비 → 코드 교환 → 받은 scope와 요청 scope 비교(누락 시 사용자에게 알림, synsory-api `missing_scopes`) → 저장.
3. **저장** `studio_auth.provider_connections` **[결정 필요 D]**: `profile_id`, `provider`, `refresh_token_cipher`, `access_token_cipher`, `access_expires_at`, `granted_scopes`, `external_account_id`, `version`, 시각. 암호화는 기존 AES-256-GCM(`infrastructure/src/crypto.ts`).
4. **유효 토큰 얻기**: 만료 60초 전이면 갱신. 갱신은 그 행을 `FOR UPDATE`로 잠근 짧은 트랜잭션 안에서 하고, **Zoom은 새 refresh token을 즉시 저장**한다. Google refresh 응답에 refresh token이 없으면 기존 값을 유지한다(`TokenSet.from_token_response`). 동시 갱신이 겹쳐도 한 번만 갱신되도록 잠근 뒤 만료를 다시 확인한다.
   - 예외: 토큰 엔드포인트 HTTP 호출 동안 행 잠금을 잡는 것은 "네트워크 대기 중 트랜잭션 유지 금지" 규칙과 충돌한다. 대안은 `version` 낙관적 갱신(잠그지 않고 갱신 후 `where version=$n`으로 저장, 실패 시 다시 읽기). **[결정 필요 E]**
5. **해제**: provider revoke 호출 후 행 삭제.

알아둘 제약(synsory-api 실측·공식 문서):

- Google 동의 화면이 "테스트" 상태면 refresh token 7일 만료. refresh token은 계정 × 클라이언트당 100개, 초과 시 오래된 것부터 무효.
- Zoom 리다이렉트 URI는 https 필수(`http://localhost` 불가). studio 로컬(`localhost:5173`)에서 Zoom 연결을 받으려면 ngrok 같은 터널이 필요. **[결정 필요 F]**
- Drive 연결용 Google client secret은 Supabase가 아닌 앱 env에 둬야 한다. studio `.env.dev.local.example`의 "Google secret은 Supabase에만" 원칙의 예외. **[결정 필요 G]**
- Picker는 브라우저에 짧은 수명 access token이 필요하다(`docs/google_drive.md` 2.1절). studio "토큰을 웹에 두지 않는다" 원칙과 충돌. Picker 열 때만 내려주는 엔드포인트를 둘지. **[결정 필요 H]**

## 7. 활동 도구 매핑

| 도구(가칭 `activity_type`) **[결정 필요 I]** | 근거 서비스 | `external_refs` 항목 | `activity_responses` |
| --- | --- | --- | --- |
| `google_group_docs` · `google_group_slides` · `google_group_sheets` | Docs·Slides·Sheets 유즈케이스 2~4 | 팀마다 `{ id: fileId, provider: 'google', kind, team_id, url, checkpoint_revision }` | 거의 안 씀(파일 배포형). 마감·복원은 `external_refs`를 돌며 권한 변경 |
| `google_form` (설문·퀴즈·동료평가는 `config`로 구분할지 도구를 나눌지 결정) | Forms | 폼마다 `{ id: formId, team_id?, responder_url, reviewees?, cursor, checkpoint_revision }` | `source_key` = Forms `responseId`, `payload` = FormSubmission, `identity` = `respondent_email` → 명단 이메일로 매칭 |
| `zoom_meeting` | Zoom | 미팅마다 `{ id: meetingId, team_id?, join_url, occurrences? }` | `source_key` = `participant_uuid`(또는 미팅 uuid + participant_uuid), `identity` = 표시 이름 속 학번 |

- 팀 정보는 studio의 팀 스냅샷(`activities.config.team_snapshot` = `{ id, name, student_ids }[]`)에서 온다. 스냅샷에는 이메일이 없으므로 공유·응답자 지정 때 `course_members`에서 한 번에 조회한다(N+1 금지).
- studio의 `canChangeStructure`는 `external_refs`가 비어 있을 때만 구조 변경을 허용한다. 외부 파일을 만든 뒤에는 팀 구성을 바꿀 수 없다는 synsory-api 전제와 맞는다.
- Zoom 출석의 학번 매칭은 studio 명단에 학번이 있어야 한다. 현재 `studio.profiles`에는 `display_name`만 있다. **[결정 필요 J]**

## 8. 큐 · 수집 · 웹훅

- **Forms 응답 수집**: 작업 `google-forms-collect`, group = 폼 ID. 작업이 `listResponses(formId, since=cursor)` → 100개씩 `CollectionService.commit(…, { resource_id, checkpoint_revision, payloads, next_cursor, page_complete })`. `since`는 `>=`라 경계 응답이 다시 오지만 `unique(activity_id, source_key)`가 멱등 처리한다.
- **퀴즈 점수**: `lastSubmittedTime`이 채점 변경을 반영하지 않으므로 커서 없이 전체 재조회한다. 같은 `source_key`로 다시 저장되면 studio가 `revision`을 올린다.
- **폴링 주기**: Forms 응답 목록은 "비싼 읽기"(사용자당 분당 180). 활동이 `open`인 동안만 돌린다. 주기 **[결정 필요 K]**.
- **Zoom 웹훅**: `POST /api/webhooks/zoom`. 이 라우트만 Fastify JSON 파싱 전 **원본 바이트**를 받아 서명 검증(`v0:{ts}:{raw body}` HMAC-SHA256, 상수 시간 비교) → `endpoint.url_validation`이면 CRC 응답(3초 안) → 그 밖은 큐에 넣고 즉시 204. 처리는 worker에서. 72시간마다 재검증, 6회 연속 실패 시 구독 중지.
- 외부 HTTP 호출은 DB 트랜잭션 밖에서 한다. 결과 저장만 짧은 트랜잭션으로.

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
| `openpyxl` (xlsx 내보내기) | 새 의존성 필요(예: exceljs). 버전 고정 **[결정 필요 L]** |
| FastAPI `Depends`, `HTTPException` | 없음. application 함수가 port를 인자로 받고 `AppError`를 던진다 |
| `dict.get("a", {}).get("b")` | Zod 파싱 후 접근, 또는 `?.` + `noUncheckedIndexedAccess` 대응 |

## 10. 결정 필요 항목 모음

배치(이 레포에서 제안, studio 담당자 확인):

- A. 응답 형식 변환을 infrastructure에 두고 domain에는 Synsory 규칙만 둘지 (2절)
- B. 하위 폴더 사용 여부 (3절)
- C. 외부 오류 `AppError` 코드 이름 (5절)
- I. `activity_type` 이름과 Forms 도구 분할 방식 (7절)
- K. Forms 수집 폴링 주기 (8절)

studio 범위·정책 (studio 담당자 결정):

- 외부 도구 범위 열기(studio `TODO.md` 1절·`AGENTS.md`), `activity_type_allowed` 허용 목록 변경
- D. 연결 토큰 테이블 위치(`studio_auth.provider_connections` 제안)
- E. 토큰 갱신 동시성: 행 잠금 vs 낙관적 갱신
- F. Zoom https 리다이렉트를 로컬에서 받는 방법
- G. Drive용 Google client secret을 앱 env에 두는 예외
- H. Picker용 짧은 수명 access token 전달
- J. 명단에 학번 필드
- L. xlsx 라이브러리 의존성 추가
- GCP 프로젝트·동의 화면과 Zoom 앱을 studio 로그인용과 공유할지

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
