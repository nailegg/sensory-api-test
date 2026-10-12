# `feat/google-tools` 배포 전 검토 보고 (2026-10-10)

검토자: 이 브랜치를 처음 보는 시니어 백엔드·보안 검토자 페르소나(별도 에이전트, 읽기 전용). 대상: synsory-studio `main(a03a27f)..feat/google-tools` 커밋 10개. 직접 실행: typecheck·lint·boundaries·단위 107·DB 47 통과. "라이브"는 `docs/VERIFICATION.md` 2026-10-10 항목이며 코드·테스트로 뒷받침되는지 따로 확인했다. 상현이 pg-boss 내부 코드로 B·C를 재확인함(그룹 동시성은 큐 이름 단위, `singletonKey`는 standard 큐에서 무효).

**한 줄 요약**: 핵심 흐름(연결 → Docs 조별 생성 → 마감 → 재개, 설문 수집)은 코드·DB 테스트·라이브가 일치한다. 다만 ① 조 단위 실패에 재생성 경로가 없고 ② 같은 활동의 생성·마감·재개 작업이 큐가 달라 동시에 돌 수 있으며 ③ `singletonKey`가 효과 없고 ④ worker의 외부 오류 로그가 0줄이며 ⑤ Slides·Sheets·퀴즈·동료평가·폼 재개·Picker 모듈·연결 해제는 studio 라이브 확인이 없다.

## 1. 검증된 기능 표

증거 수준: 단위(가짜 fetch/port) / DB(studio_test + 가짜 Google port) / 라이브(실제 Google) / 미검증.

| 기능 | 증거 | 근거 |
| --- | --- | --- |
| 0010 허용 목록 4개·worker `external_accounts` UPDATE | DB | `tests/db/google-tools-migration.test.ts`, `integration.test.ts` 권한 검사 |
| 0011 worker `course_members` UPDATE(DELETE 없음) | DB + 라이브 | `integration.test.ts`, `google-activities.test.ts`(worker 풀로 수집) |
| `productTools` 4개 등록·다른 키 거절 | 단위 | `domain.test.ts` |
| config 검증 4종(strict), `team_snapshot` 회귀 | 단위 | `google-tools.test.ts` (단, `closed→open`을 `ActivityService.state`로 지나는 DB 테스트 없음) |
| Forms 응답 검증·sourceKey·identity·dto·집계 | 단위 | `google-tools.test.ts` |
| mapper 출력 ↔ strict `formSubmission` 일치 | 코드 대조 + 라이브 1건 | 테스트는 수제 객체라 결합은 라이브 설문 1건뿐 |
| OAuth 어댑터 | 단위 + 라이브(연결) | `google-oauth.test.ts` |
| `ConnectionService` 저장·거절 4종·캐시·갱신·`invalid_grant`·해제 멱등 | DB(가짜 Google) | `google-connections.test.ts` |
| 연결 라이브(start→동의→callback→status) | 라이브 | VERIFICATION |
| 연결 **해제**(실제 revoke), `invalid_grant` 실제 발생 | **미검증(라이브)** | 계획엔 있었으나 기록 없음 |
| 상태 전환 훅 같은 트랜잭션·실패 롤백 | DB | `google-activities.test.ts` |
| Docs 조별 생성(복사 경로)·조 실패 격리·`share_errors`·2회 no-op·상태 DTO | DB | `google-activities.test.ts` |
| Docs 조별 생성(Markdown 업로드 경로) | 단위 + 라이브 | 라이브는 Markdown 경로만 |
| 마감·재개 | DB + 라이브(Docs) | |
| Slides·Sheets 조별 파일 | **단위만** | studio 라이브 없음(Python 실측은 있음). DB 테스트는 `docs` fake를 slides·sheets에 꽂음 |
| 설문 생성·응답자 제한·수집·커서·재수집 무변화 | DB + 라이브 | 응답 1건, 집계 평균 5 |
| 동료평가 조별 폼 | DB(가짜) | 라이브 없음 |
| 퀴즈 수집(`graded` 전체 재조회) | **단위만(함수)** | `collectGoogleForms`의 quiz 분기는 DB·라이브 없음 |
| 폼 재개(`openForm`) | 단위만 | |
| Picker 세션 라우트 | 라이브 + DB(`currentToken`) | |
| Picker 브라우저 모듈·`picked-file` | **미검증(라이브)** | 단위는 가짜 PickerApi |
| 라우트 7개의 HTTP 계층(인증·CSRF·스키마) | **HTTP 테스트 0개** | 라이브로 5개 통과, `picked-file`·DELETE 미확인 |
| worker 배선·`createJobSender` | 테스트 없음, 라이브만 | |
| Drive 어댑터(배치·재시도·업로드·export·오류 분류) | 단위 22개 | |

작성자 기록과의 차이: "Picker 세션 확인"은 라우트만. "해제 1회"는 라이브 기록 없음. DB 테스트가 worker 역할로 도는 것은 수집만(provision·close·reopen은 API 역할. worker 권한은 0001로 충분하고 라이브 Docs가 실제 worker로 돌았으므로 결과는 뒷받침됨).

## 2. 발견된 오류

### 라이브에서 잡혀 수정된 2건 — 검증
- ① `team_snapshot` strict 거절: 수정(`parseConfig` 분리·되붙임)과 단위 회귀 적절. 부작용: `validateResponse`도 같은 함수라 payload에 `team_snapshot` 키가 오면 strict를 우회(실해 없음, 낮음).
- ② worker `course_members` 잠금 권한: 원인·0011·회귀 적절. 권한 확대 리스크는 S5.

### 새로 찾은 결함
- **A. 조 단위 실패는 영구히 재생성되지 않는다(중~높)** — `provisionGoogleActivity`가 폴더 ref가 있으면 즉시 return. 조 하나가 429/5xx/404로 실패하면 `{team_id, error}`만 남고 이후 open은 reopen으로 가서 `restoreEditors`만 돈다. 교수자가 할 수 있는 일이 없다(DB 직접 수정 외).
- **B. 같은 활동의 provision·close·reopen이 동시에 돌 수 있다(중)** — pg-boss 그룹 동시성은 큐 이름 단위(`plans.js` `WHERE name = … AND group_id`). 세 작업은 서로 다른 큐. 재현: 조 20개 open(수십 초) 직후 closed → close가 refs 없는 상태로 no-op 완료 → provision이 writer로 공유한 파일 저장 → **활동은 closed인데 학생은 writer**. reopen 재시도 중 close면 같은 파일 권한을 동시에 바꿈(8.1절에서 금지한 상황). `saveRefs`가 잠금 없이 통째로 덮어써 기록 유실도 가능.
- **C. `singletonKey` 무효(낮음)** — 큐 정책이 `standard`라 효과 없음(`short`/`stately` 필요). 주석·계획이 거짓.
- **D. `reopen_error`가 상태 라우트에 안 나온다(낮~중)** — DTO가 `close_error`만 읽음. 재개 실패가 정상으로 보임.
- **E. 이메일 없는 학생은 조용히 공유에서 빠진다(낮)** — `share_errors`에도 안 남음.
- **F. 작업이 중간에 죽으면 재시도가 폴더·파일을 중복 생성(중)** — refs를 흐름 끝에 한 번 저장. worker 크래시·만료(15분) 뒤 재시도는 새 폴더·새 파일·중복 공유.
- **G. 수집 실패는 흔적 없이 `failed`, 재수집 경로 없음(중)** — close 뒤 수집이 던지면 작업 전체 실패→3회→failed. 상태는 정상으로 보임. 원인 후보: 연 교수자가 수업에서 빠짐(FORBIDDEN), 429, payload strict 불일치. 유일한 재실행은 open/closed 왕복인데 그 왕복이 B를 유발.
- **H. 외부 오류 구조화 로그(결정 31) 미구현(중, 운영)** — 어댑터·흐름·worker에 로그 0줄. 실패는 `studio_queue.job.output`에만.
- **I. 콜백 중 세션 만료 시 JSON 401(낮, UX)** — onRequest 인증이 콜백 핸들러 try/catch 밖. → **수정**(2026-10-13, K4 참조).
- **J. 템플릿을 고른 교수자 ≠ 활동을 연 교수자면 전 조 404(중)** — `drive.file`은 고른 사람 × 앱 단위. B 토큰으로 A가 고른 템플릿 복사 → 조마다 NOT_FOUND, 폴더는 생성돼 A로 재생성도 불가(A 참조). 결정 27의 보류 항목이 코드에서 실패로 드러남.

## 3. 불완전할 수 있는 부분
- 가짜 port: DB 테스트 `fakeGoogle`은 배치 전체 실패→개별 재시도, 페이지네이션·`since`를 흉내 내지 않음. slides·sheets에 docs fake. `refresh_token` 없는 응답은 `GOOGLE_SCOPE_MISSING`이라는 오해하기 쉬운 코드.
- **실행 중간 사망 시 중복 공유(2026-10-13 확인, A·F 수정의 잔여)**: provision은 폴더는 즉시 기록하지만 조별 파일 ref는 **모든 조가 끝난 뒤 한 번** 기록하고, 조별 흐름은 복사 → 치환 → 공유를 조마다 이어서 한다. 강제 종료·OOM·2시간 만료로 중간에 죽으면 이번 실행에서 이미 만들고 공유까지 끝난 조들이 refs에 없어 재실행이 같은 조의 파일을 다시 만들고 다시 공유한다 → 학생이 파일 두 개를 받는다. graceful stop(10초)은 조가 많은 작업을 보호하지 못한다. 앞서 "중복 공유 없음"이라 적은 것은 틀렸다. 제안: 조마다 "만들기 → refs 기록 → 공유" 순서로 바꾸고 기록을 조 단위로 한다. 기록 전 사망은 공유 안 된 고아 1개, 기록 후 사망은 재실행이 refs의 파일에 공유만 다시 한다(권한 생성은 Drive에서 멱등). 변경은 `google-files.ts` 두 흐름에 조 결과 콜백 하나와 provision의 조별 `updateRefs`. → **수정**(2026-10-13 상현 지시, studio 366f83e): 파일·폼이 생기면 즉시 `share_pending` 표시로 refs에 기록하고 그다음 공유. 끝의 병합이 pending ref를 공유 결과로 교체. 재실행은 pending ref의 공유만 마저 하고 새로 만들지 않음. 덧붙여 `mapConcurrently`가 한 조 실패 뒤 새 조를 시작하지 않고 진행 중인 조는 끝낸 뒤 던지도록 바꿈(실패한 실행의 잔여 작업이 재시도와 겹치지 않게). 테스트: 단위 1(콜백이 치환 뒤·공유 전에만 호출), DB 2(파일·동료평가 폼 각각 공유 중 사망 → 재실행이 재생성 없이 공유만 완료). 단위 109·DB 50 통과. 남은 틈은 "만든 직후 기록 전 사망"의 공유 안 된 고아 파일 1개뿐.
- 경계: 콜드 캐시에서 동시 4개 갱신(무해). provision은 멱등 아님(F). close·reopen은 멱등. API 401 시 "한 번만 갱신 후 재시도" 미구현. 연결 해제 뒤 provision은 예외→failed(상태는 `provisioned:false`만), close는 조별 `close_error`, reopen은 기록되나 안 보임(D), 수집은 G. 교수자가 수업에서 빠짐: 수집만 FORBIDDEN.
- 조용히 삼켜짐: `googleRefs`의 `safeParse`+`flatMap`은 스키마에 안 맞는 ref를 없는 것처럼 취급(스키마 진화 시 파일이 마감·재개·수집에서 조용히 빠짐). `accountEmail` 실패 시 null. `ExternalResponseError`는 작업 전체 실패.
- 관측: 로그 0줄, `observe` 없음, 교수자는 재시도 횟수·실패 사유를 볼 수 없음.
- 테스트 공백: HTTP 라우트 7개, `state()` 경유 재개, Slides/Sheets/퀴즈/폼 재개/동료평가 수집·집계 결합, B·F 시나리오.

## 4. 리스크

| # | 영역 | 내용 | 심각도 |
| --- | --- | --- | --- |
| S1 | 토큰 노출 | refresh token은 암호문만 DB, access token은 메모리, 로그는 쿼리·쿠키·CSRF 마스킹, details에 토큰 없음. 노출 경로 미발견 | 낮음 |
| S2 | CSRF·세션 | 전역 CSRF·Origin·CORS·SameSite, 콜백은 state 1회+브라우저 해시+세션 profile 일치. 로그인 CSRF 차단 | 낮음 |
| S3 | 권한 | 상태 라우트는 교수자 전용. 연결 라우트 6개는 로그인한 누구나(학생 포함) 호출 가능 — 무해하나 공격면 확대 | 낮음 |
| S4 | Picker 토큰 | 교수자 access token(1시간)이 브라우저로(결정 36 수용). XSS 시 해당 시간 Drive 앱 파일 조작 가능. 웹 CSP 없음 | 중간(수용) |
| S5 | DB 권한 | 0011로 worker가 `course_members` 전체 UPDATE(잠금에만 필요). 결함·주입 시 명단 변조 가능 | 중간 |
| S6 | 키 | 세션 키 하나로 연결 토큰 암호화(결정 37). 키 교체 절차 문서 없음 | 낮음 |
| D1 | 동시 쓰기 | `saveRefs` 잠금·버전 없음. B와 결합 시 기록 유실 | 중간 |
| D2 | 수집 커서 | checkpoint 매 배치 재조회, 커서 경계 중복은 unique로 멱등. 설계 일치 | 낮음 |
| D3 | 중복 생성 | F | 중간 |
| D4 | 고아 파일 | 활동 삭제·조 실패·중복 생성 시 Drive 파일 정리 없음 | 낮음 |
| O1 | 재실행 | failed 작업 재실행이 open/closed 왕복뿐이고 그게 B를 유발 | 중간 |
| O2 | 큐 생성 시점 | 큐 3개는 `migrate.ts`에서만 생성. 마이그레이션 전에 API가 뜨면 `state('open')`이 500 | 중간 |
| O3 | 로그 | H | 중간 |
| O4 | worker 캐시 | 프로세스별 캐시라 해제·`invalid_grant` 뒤 다른 프로세스는 만료까지 옛 토큰 사용 | 낮음 |
| O5 | 마이그레이션 | 0010 `ADD CHECK`가 기존 행 검사. 배포 전 `activities` 0행 확인 | 낮음 |
| O6 | API 기동 | `jobs.start()` 실패 시 API 안 뜸. Google 미설정 환경도 큐 스키마 필수 | 낮음 |
| E1 | 테스트 앱 | 동의 화면 "테스트" 상태면 refresh token 7일 만료 → 마감 작업 실패. 프로덕션 전환 전 배포 금지 | **높음(설정)** |
| E2 | `drive.file` | J, 웹 사본·옮긴 파일 접근, Picker 장기 유지 미확인 | 중간 |
| E3 | 쿼터 | Forms 응답 읽기 분당 180(비싼 읽기). 작업 수준 backoff 없음 | 낮~중 |
| E4 | 동시성 | worker당 큐 3 × 2 × 조별 4 = 최대 24 동시 호출(교수자 1명 기준). 실측은 6까지 | 낮음 |
| U1 | UX | 화면 없음. 오류는 코드만 노출. 조·재개·수집 실패를 교수자가 알기 어려움 | 중간 |

## 처리 현황 (2026-10-10, 상현 지시로 push 전 반영)

- **1. B·C 해결**: 큐 하나(`google-activity`)에 group = 활동 ID → 같은 활동의 작업이 순서대로 하나씩. `singletonKey` 제거. (`google-jobs.ts`, `migrate.ts`, worker)
- **2. A·G·D 해결**: provision이 폴더를 먼저 저장하고 빠진 조만 채움(F도 같이 완화). 수집 실패는 폼 ref `collect_error`. 상태 DTO가 `close_error`·`reopen_error`·`collect_error`를 모두 표시. `POST …/google/retry` 추가. DB 테스트 3건 추가.
- **3. O2·E1**: studio `TODO.md`에 배포 체크리스트(마이그레이션 → 기동 순서, 0행 확인, 동의 화면 프로덕션 전환).
- **4. H 해결**: worker가 실패를 `jobFailure`(이메일·긴 ID 마스킹) JSON 한 줄로 로그. 단위 테스트.
- 추가 발견(재시도 라이브에서): 재개가 **파일 소유자 본인**의 권한을 writer로 바꾸려다 실패(`reopen_error`). `restoreEditors`가 소유자를 건너뛰게 수정.
- **S5 처리(2026-10-12)**: 0011을 테이블 전체 UPDATE에서 **`updated_at` 열 하나**로 좁힘. Postgres는 행 잠금에 "어느 한 열"의 UPDATE만 요구함을 실측(열 권한 상태에서 이메일 UPDATE 거절). 근본 대안 D(`commit`에 시스템 호출자 경로)는 PR 안건.
- **D 근거 재확인(2026-10-13)**: "worker가 `CollectionService.commit`을 부른다"는 **명시 규칙은 studio에 없다**(AGENTS·SECURITY_REVIEW·VERIFICATION·코드 주석 모두). 정황 근거는 studio `TODO.md` P5 절("Worker·큐·계측")이 `commit`의 기능(checkpoint revision 검사, 100행·1 MiB 묶음, 원본별 멱등, 진행 지점 원자 갱신·중간 실패 복구)을 "기반을 구현한다"로 적고, 같은 절에서 "외부 HTTP를 수행하는 구체적인 도구 작업은 등록하지 않는다"고 의도적으로 멈춘 것. 즉 `commit`은 worker 수집을 위해 미리 둔 기반이고 우리 `google-activity` 작업이 첫 실제 소비자다. 그러나 작성자가 worker 역할로 `commit`을 실행한 적은 없다(통합 테스트는 교수자 actor, 0001이 worker에 `course_members` UPDATE를 안 줌). 따라서 "worker가 자신을 누구로 밝히고 부르는가"는 미결 설계이고, K2(작업을 넣은 교수자를 actor로)와 0011은 그 빈칸을 우리가 채운 선택이다. 함수가 틀린 것이 아니라 시스템 호출자 입구가 없는 미완성 기반이므로, `commitFromJob`을 우리가 만들면 작성자 몫의 결정을 대신하게 된다. 브랜치는 B+K2로 두고 PR에서 작성자(taeyeongyoo)에게 묻는다.

## 5. 권고

**배포 전 반드시**
1. B: 세 작업을 한 큐로 합치거나(종류는 `data.kind`), 작업 안에서 활동 행을 `FOR UPDATE`로 잡고 현재 state에 맞는 동작만 한다. `singletonKey` 주석(C)을 지우거나 큐 정책을 `stately`로.
2. A·G·D: 실패한 조만 재생성하는 경로 + 수동 재시도/재수집 라우트 1개, `reopen_error` 표시.
3. O2·E1: 배포 절차에 "마이그레이션(큐 생성) → API" 순서와 "동의 화면 프로덕션 전환" 체크, 0010 전 `activities` 0행 확인.
4. H: worker 작업 실패를 구조화 로그 1곳에서(결정 31).

**다음 브랜치에서**
5. F(폴더 생성 직후 refs 1차 저장), J(템플릿 소유자 ≠ 여는 교수자 가드/안내), E. (I는 2026-10-13 수정.)
6. 라우트 HTTP 테스트 7개, `state()` 경유 재개 DB 테스트, Slides/Sheets/퀴즈/동료평가 라이브 1회씩, 해제·`invalid_grant` 라이브, picked-file 라이브.
7. S3(연결 라우트 교수자 제한), S5(0011 범위 재검토).

**받아들일 만함**
8. S1·S2·D2·O4·O5·E4. S4·S6은 승인된 결정이라 기록만.

## 6. 추가 탐색: 코드베이스 미숙지로 인한 오류 (2026-10-12, 별도 에이전트)

2번(team_snapshot)·3번(FOR SHARE 권한)·4번(pg-boss 그룹) 같은 유형을 더 찾게 했다. 전제가 맞는 것(권한·트리거·checkpoint 필드·zod 직렬화·CSRF·웹 클라이언트 등 16건)은 확인됐고, 틀린 것 6건:

| # | 발견 | 전제 vs 실제 | 처리 |
| --- | --- | --- | --- |
| K1 (높음, 실측) | 단일 큐로도 같은 활동 작업이 겹칠 수 있음 | 전제: `groupConcurrency: 1`이면 DB가 직렬화. 실제: 그룹 필터는 active 행의 NOT EXISTS 서브쿼리라 동시 fetch 둘 다 통과(30/30 재현). `localConcurrency: 2`와 notify 동시 깨움으로 retry(작업 2개)·빠른 close→open에서 거의 확실히 겹치고, `saveRefs` 덮어쓰기로 ref 유실 | **수정**: `localGroupConcurrency: 1`(프로세스 안 원자적) + refs 쓰기를 행 잠금 안 읽기-합치기-쓰기로 + 재시도를 작업 하나로. 프로세스 간 직렬화는 없어 `WORKER_INSTANCES=1` 전제를 문서화. 1대 전제는 기존 studio에 없던 제약이라 "외부 API 호출 작업의 동시성 관리"로 PR 안건(결정 51, 2026-10-13) |
| K2 (중간) | 수집 commit이 "처음 연 교수자가 지금도 활성 교수자 + 수업 미보관"을 요구 | `courses.member(…, instructor=true)`가 `removed_at`·보관 검사 | **수정**: 수집 주체를 작업을 넣은(닫은·재시도한) 교수자로. 보관 수업은 retry 라우트도 막힘(설계상 수용) |
| K3 (중간) | 상태 전환 훅이 트랜잭션 안에서 풀 연결을 하나 더 빌림 | `Database.query`는 새 연결. 동시 open이 풀 크기면 5초 뒤 일괄 500 | **수정**: `ConnectionService.status(profileId, tx)`로 트랜잭션 연결 사용 |
| K4 (낮음) | 연결 콜백이 인증 훅 아래라 세션 만료 시 JSON 401 | 로그인 콜백은 `/api/auth/` 면제 경로 | **수정**(2026-10-13, 상현 지시, studio 0aeedda). 원인은 우리 경로 선택: studio의 `onRequest` 훅은 `/api/auth/*`·health·openapi만 인증을 면제하고, 로그인 Google 콜백은 그 면제 경로 아래에서 핸들러 안의 실패를 웹으로 redirect한다(관례). 우리 콜백은 `/api/connections/google/callback`이라 훅이 먼저 돌아, 동의 화면에 머무는 동안 세션이 만료되면 훅의 401 JSON이 핸들러의 try/catch에 닿기 전에 나갔다. 데이터 영향 없음. 수정: 면제 목록에 이 경로를 추가하고 핸들러 try 안에서 `auth.authenticate`를 직접 불러 실패하면 `/courses?google_error=UNAUTHENTICATED`로 redirect(콘솔 리다이렉트 URI 유지). 라우트 테스트 1건 추가(세션 없이 호출 → 302). 단위 108·DB 48·타입·린트·경계 통과 |
| K5 (낮음) | 15분 만료 뒤 supervisor가 재시도해 핸들러 겹침 | `expireInSeconds` 기본 15분 | **수정**: 2시간 |
| K6 (확인 필요) | 스냅샷의 `student_ids`에 `removed_at` 미적용 → 제거된 학생에게도 재시도 시 공유 | 스냅샷은 open 시점 명단을 고정하는 설계 | **PR 안건**(2026-10-13 상현, 결정 52). 스냅샷 의미론상 의도로 볼지, 재시도(빈 조 채우기) 때만 `removed_at`을 걸러 공유 대상에서 뺄지 작성자와 정한다 |

