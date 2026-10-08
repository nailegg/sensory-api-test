# Google Meet 연동 스펙

상태: 1단계(API 탐색) 완료 · 2단계(유즈케이스 확정, 상현) 대기
최종 수정: 2026-10-05 · 작성: 상현
확인 기준: 공식 문서 2026-10-05(developers.google.com Meet REST API v2 · Workspace Events API · Calendar API, support.google.com Meet·Google One). 실측 없음. **개인 Gmail 계정에서 Meet REST API가 동작하는지부터 공식 문서에 명시가 없어** 3단계 첫 호출로 확인한다(12절).

이식 대상(예정, studio에 TS로 이식): `app/services/google_meet/{client,mapper,scopes,usecases}.py`와 이 문서. 녹화 파일(MP4)·트랜스크립트 문서는 Drive 파일이므로 Drive 호출은 `app/services/google_drive/`와 `docs/google_drive.md`에 둔다. 시각이 있는 예약은 Calendar API가 필요한데, Calendar 호출을 어느 폴더에 둘지(새 `google_calendar` 서비스 vs Meet 유즈케이스 범위 축소)는 2단계 결정이다(10절 1항). 이 문서는 Meet REST API(`https://meet.googleapis.com/v2`)를 다룬다.

---

## 1단계 요약: 할 수 있는 일 · 못 하는 일 · 눈에 띄는 제약

2단계에서 유즈케이스를 고를 때 보는 한 장이다. 아래 3~12절은 이 요약의 근거다.

**리소스.** 미팅 공간(`spaces/{space}`, `meetingUri` `https://meet.google.com/abc-mnop-xyz`, `meetingCode`) 하나가 여러 번 열린다. 열릴 때마다 회의 기록(`conferenceRecords/{id}`)이 생기고, 그 아래에 참가자(`participants`) → 접속 세션(`participantSessions`), 녹화(`recordings`), 트랜스크립트(`transcripts`) → 발화(`entries`), Gemini 회의록(`smartNotes`)이 달린다. 공간에는 **시작 시각·길이 필드가 없다.** 예약된 미팅은 Calendar 일정에 Meet 링크가 붙은 것이다. 녹화·트랜스크립트·회의록 **파일은 주최자 Drive**에 생기고 Meet API는 그 파일 ID만 준다.

**할 수 있는 일 — API 기능** (플랜 조건은 아래 "플랜" 표)

| 분류 | 내용 | 메서드 |
| --- | --- | --- |
| 공간 생성 | 링크 하나를 즉시 만든다. 접근 방식(`OPEN` 링크만 있으면 입장 · `TRUSTED` · `RESTRICTED` 초대된 사람만), 진행자 제어(채팅·반응·발표 제한, 뷰어로 입장), 자동 녹화·트랜스크립트·회의록, 출석 보고서 생성 여부를 미리 설정 | `spaces.create` |
| 공간 조회·수정 | 설정 변경, 진행 중인 회의(`activeConference`) 확인. `spaces/{meetingCode}`로도 조회(Calendar가 만든 링크를 공간으로 바꿀 때) | `spaces.get` / `spaces.patch` |
| 강제 종료 | 진행 중 회의를 끝낸다(전원 퇴장) | `spaces.endActiveConference` |
| 멤버 지정 | 공간에 이메일로 멤버 등록(노크 없이 입장), 공동 호스트(`COHOST`) 지정. 2026-09-11 GA | `spaces.members.create` / `list` / `delete` / `batchUpdate` … |
| 회의 기록 | 공간별·기간별 회의 목록, 실제 시작·종료 시각, 진행 중 여부(`end_time IS NULL`) | `conferenceRecords.list` / `get` |
| 출석 | 참가자별 최초 입장·최종 퇴장 시각, 접속 세션별 입퇴장(재접속 구분). 로그인 사용자·익명·전화 참가자 구분 | `…participants.list` / `…participantSessions.list` |
| 녹화·트랜스크립트·회의록 | 생성 상태(`STARTED` → `ENDED` → `FILE_GENERATED`), Drive 파일 ID·링크. 트랜스크립트는 **발화 단위 텍스트를 Meet API로 직접** 읽을 수 있다(말한 참가자·시각·언어) | `…recordings` / `…transcripts` / `…transcripts.entries` / `…smartNotes` |
| 이벤트 | 회의 시작·종료, 참가자 입퇴장, 녹화·트랜스크립트·회의록 파일 생성 | Workspace Events API `subscriptions.create` → **Cloud Pub/Sub** (9절) |
| 예약 | 시각·반복이 있는 미팅 = Calendar 일정 + Meet 링크(`conferenceData.createRequest`) | Calendar API `events.insert`(4.3절) |

**못 하는 일 · 다른 API로 해야 하는 일**

- **Meet API만으로는 시각을 정한 예약을 못 한다.** 공간에 시각 필드가 없다. 예약·반복·참석자 초대 메일은 Calendar API `events.insert`(Calendar scope 추가)로 하거나, `spaces.create`로 링크만 만들고 시각은 Synsory가 관리한다.
- **녹화를 API로 시작·중지할 수 없다.** `artifactConfig.recordingConfig.autoRecordingGeneration=ON`으로 "열리면 자동 녹화"를 미리 걸어두는 것만 된다. 트랜스크립트·회의록도 같다.
- **소회의실·투표·Q&A API가 없다.** 레퍼런스에 메서드가 없다.
- **참가자 이메일을 주지 않는다.** 로그인 사용자는 `signedinUser.user = "users/{id}"`와 표시 이름만 온다. 이메일은 People API `people.get`으로 따로 바꿔야 하고 "privacy 때문에 모든 참가자의 프로필을 받을 수는 없다"고 명시되어 있다. 익명·전화 참가자는 표시 이름뿐이다.
- **녹화 MP4를 받으려면 Drive 제한(restricted) scope가 필요하다.** 문서상 경로는 `drive.readonly` 또는 `drive.meet.readonly`(둘 다 제한 → CASA). `drive.file`로 Meet이 만든 파일을 읽을 수 있는지는 미확인(12절). 트랜스크립트는 `entries` API로 텍스트를 받으면 Drive scope 없이 된다.
- **회의 기록은 종료 30일 뒤 삭제된다**(`expireTime`). 참가자·발화 데이터도 같다. 필요한 값은 30일 안에 Synsory로 옮긴다.
- **이벤트는 Pub/Sub으로만 온다.** Zoom처럼 https 웹훅 URL을 등록하는 방식이 없다. Pub/Sub은 **결제 계정이 연결된 Cloud 프로젝트**를 요구한다(Forms watch와 같은 조건). 대안은 `conferenceRecords.list` 폴링이다.
- Meet API는 "성과 추적이나 사용자 평가용이 아니다"("isn't intended for performance tracking or user evaluation")라는 문구가 개요에 있다. 출석을 성적에 쓰는 설계는 심사 때 설명이 필요할 수 있다(10절 12항).

**눈에 띄는 제약**

| 항목 | 값 | 비고 |
| --- | --- | --- |
| **개인 계정 지원** | Meet REST·Events API 문서에 개인 Gmail 지원 여부 **명시 없음** | Media API 문서는 Gmail 회의를 따로 다루므로 대상이긴 한 것으로 보인다. 3단계 첫 `spaces.create`로 확인 |
| **무료 Gmail 통화 시간** | 1:1은 24시간, **3명 이상은 60분**(50분에 경고) | 수업·팀 회의는 60분에 끊긴다. Google One 2TB 이상 AI 플랜은 24시간 |
| **무료 Gmail 기능** | 녹화·트랜스크립트·Gemini 회의록·출석 보고서·공동 호스트·소회의실 호스팅 **전부 불가** | API로 `artifactConfig`를 켜도 "주최자 라이선스가 지원할 때만" 생성된다 |
| **scope 등급** | `meetings.space.created`·`meetings.space.readonly`는 **민감(sensitive)**, `meetings.space.settings`는 비민감 | 지금까지 Google 4종은 비민감 `drive.file` 하나였다. Meet을 넣으면 **처음으로 민감 scope가 생겨 앱 검증 대상**이 되고, 추가 시 전원 재동의 |
| 앱이 만든 공간만 | `meetings.space.created`로는 **앱이 만든 공간의 회의만** 보인다 | 교수자가 Meet·Calendar UI로 만든 미팅의 출석·트랜스크립트는 `meetings.space.readonly` 필요 |
| 쿼터 | 읽기 사용자당 분당 600 · 쓰기 100 · **`spaces.create`만 사용자당 분당 10**(프로젝트당 100) | 그룹 30개 공간을 한 번에 만들면 3분. "2026년부터 초과분 과금" 문구 |
| 보존 | 회의 기록·참가자·발화 **30일** | 파일(녹화·트랜스크립트 문서)은 Drive 규칙 |
| `meetingCode` | 마지막 사용 후 약 **365일** 지나면 만료·재사용 | DB 키는 `spaces/{id}`로 저장. 코드는 표시용 |
| 이벤트 구독 수명 | 최대 **7일**, 자동 갱신 없음(`ttl=0`으로 갱신) | Forms watch와 같은 7일 |
| Calendar 쿼터 | 프로젝트당 분당 10,000 · 사용자당 분당 600 | 일정 생성·외부 초대에 별도 사용 한도 있음 |

**플랜별 Meet 기능** (support.google.com, 2026-10-05)

| 기능 | 무료 Gmail | Google One 2TB+ (AI 플랜) | Workspace |
| --- | --- | --- | --- |
| 그룹 통화 길이 | **60분** | 24시간 | 24시간 |
| 참가자 | 100 | 100 | 100~1,000(에디션별) |
| 녹화 | 불가 | **가능**("2 TB or more") | Business Standard+, Education Plus 등 |
| 트랜스크립트 | 불가 | **문서 상충**(트랜스크립트 문서엔 없음, 프리미엄 기능 표엔 있음) | Business Standard+, Education Plus 등. 한국어 지원 |
| Gemini 회의록 | 불가 | "eligible Google AI plan"(플랜 이름 미확인) | Business Standard+ 등 |
| 출석 보고서 | 불가 | 불가 | Business Plus+, Education Standard/Plus |
| 공동 호스트·소회의실 호스팅 | 불가 | 불가(소회의실 참가만) | Business Standard+ |

**Zoom과 나란히 놓으면** (Synsory가 화상회의를 하나만 붙인다면 2단계에서 비교할 표)

| 항목 | Google Meet | Zoom(`docs/zoom.md`) |
| --- | --- | --- |
| 무료 호스트 시간 제한 | 3명 이상 60분 | 1:1 포함 40분 |
| 예약 | Calendar API 필요(Meet만으론 링크) | Meetings API 하나로 시각·반복까지 |
| 무료 계정으로 가능한 출석 | 참가자 API는 열려 있음(개인 계정 동작 미확인) | 웹훅 누적만(참가자 API는 Pro) |
| 녹화·트랜스크립트 | 개인은 Google One 2TB+, 파일은 Drive(제한 scope) | Pro, 다운로드 URL 직접 |
| 이벤트 | Pub/Sub(결제 계정) 또는 폴링 | https 웹훅(ngrok) |
| 참가자 식별 | `users/{id}` → People API로 이메일(제한적), 익명 가능 | 계정 밖이면 이메일 빈 문자열 |
| 앱 인가 범위 | 테스트 사용자 100명까지, 검증 후 누구나 | 미공개 앱은 개발자 계정만 |
| 새 scope 등급 | 민감 → Google 앱 검증(CASA 아님) | 앱 심사 |
| 인증 공유 | 기존 Google OAuth에 scope만 추가 | 별도 앱·별도 토큰 |

**Synsory 관점에서 유즈케이스 후보 (2단계 참고용, 확정 아님)**

- **액티비티(또는 그룹)마다 Meet 링크를 만들어 학생에게 배포한다.** `spaces.create`(`accessType=OPEN`, 학생이 노크 없이 입장) → `meetingUri`. 시각은 Synsory가 들고 있다. Calendar 일정까지 만들어 교수자·학생 캘린더에 띄우려면 Calendar API를 같이 쓴다(`events.insert` + `conferenceData`, 또는 `spaces.create` 후 일정 `location`/설명에 링크).
- **매주 반복 수업 링크.** 공간은 시각이 없으므로 공간 하나를 학기 내내 재사용하면 된다(링크 고정). 캘린더 반복 일정이 필요하면 Calendar `recurrence`.
- **회의가 끝나면 출석을 가져온다.** `conferenceRecords.list(filter=space.name="spaces/…" AND end_time IS NOT NULL)` → `participants.list` → `participantSessions.list`. 학생 식별은 `signedinUser.user` → People API, 또는 `RESTRICTED` + `spaces.members`로 수강생 이메일만 들어오게 하는 설계. **무료 Gmail에서 참가자 API가 실제로 채워지는지가 3단계 핵심 확인 항목**이다.
- **마감 시각에 진행 중 회의를 끝낸다.** `spaces.endActiveConference`. Zoom 유즈케이스 7과 같은 자리.
- **트랜스크립트 텍스트를 Synsory에 보관한다.** `transcripts.entries.list`(Drive scope 불필요). 단 교수자가 Workspace 유료·Google One 등 트랜스크립트 가능 플랜이어야 하고, 상현 개인 계정으로는 실측할 수 없다.
- 진행 상태(예정 → 진행 중 → 종료)는 `spaces.get`의 `activeConference` 유무 + `conferenceRecords`의 `endTime`으로 폴링해 판단한다. 실시간이 필요하면 Events API + Pub/Sub(결제 계정 연결 결정 필요).

---

## 1. 이 서비스로 하는 일 (유즈케이스)

**초안 — 상현 확인 대기.** 2026-10-06 상현이 정한 방향: **Meet 단독으로 쓴다(Calendar API 없음, `docs/google_calendar.md`의 C안)**, **출석까지 한다**, 학생 캘린더에 일정을 띄울 필요는 없다. 시각은 Synsory가 들고 있고 Meet에는 링크(공간)만 만든다. 전제는 Zoom과 같다: OAuth로 연결하는 사용자는 교수자(공간 주최자)이고, 학생은 앱을 연결하지 않고 `meetingUri`로 입장한다. 링크 배포는 Synsory 몫이다. Zoom에서 뺀 "강제 종료"·"상태 추적"은 Meet에서는 호출 하나로 되지만 Zoom과 맞춰 일단 보류로 둔다.

| # | 유즈케이스 | 호출 순서 | usecases 함수 |
| --- | --- | --- | --- |
| 1 | 액티비티의 그룹마다 Meet 링크를 만든다 | 그룹마다 `spaces.create`(`accessType=OPEN`) → 그룹별 `Meeting`(`id`=`spaces/{id}`, `join_url`=`meetingUri`, `topic`·시각은 Synsory 값). 반복 수업은 같은 공간을 학기 내내 쓴다(추가 호출 없음) | `create_group_spaces` |
| 2 | 그룹 링크를 수강생 명단으로 잠근다(출석 식별용) | `spaces.patch`(`accessType=RESTRICTED`) → 학생 이메일마다 `spaces.members.create`(또는 `batchUpdate`) → `members.list`로 이메일 ↔ `user`(`users/{id}`) 대응표 반환 | `restrict_space_to_roster` |
| 3 | 회의가 끝나면 출석을 집계한다 | `conferenceRecords.list(filter: space.name="spaces/…" AND end_time IS NOT NULL, start_time 범위)` → 회차마다 `participants.list` → 참가자마다 `participantSessions.list` → 학생 식별(아래 A/B) → 학생별 접속 구간 합산(재입장·여러 기기) → 출석·지각·결석 판정과 미확인 접속 목록 | `get_attendance` (+ Zoom과 같은 판정 로직) |
| 4 | 링크를 회수한다(취소·학기 종료) | 공간 삭제 API가 없다 → `spaces.patch`(`accessType=RESTRICTED`) + 멤버 삭제(`spaces.members.delete`). 진행 중이면 `endActiveConference` 먼저 | `revoke_space` |

**유즈케이스별 메모**

- 1: `spaces.create`는 **사용자당 분당 10회**라 그룹 30개면 3분이다(8절). 생성은 순차 + 429 백오프로 하고, 액티비티 화면에서 동기 호출로 묶지 않는다. 교수자도 같은 `meetingUri`로 들어간다. 공간을 만든 Google 계정으로 로그인돼 있으면 주최자다(Zoom의 `start_url` 유즈케이스 5는 필요 없다). Zoom 유즈케이스 1(플랜 확인)에 해당하는 API는 Meet에 없으므로 Synsory는 "3명 이상이면 60분에 끊길 수 있음"을 항상 안내한다. 그룹별 "일정 변경"(Zoom 4)은 Synsory DB만 고치면 되어 API 호출이 없다.
- 2: 출석 식별을 위한 선택 단계다. `RESTRICTED`면 멤버가 아닌 사람은 노크하고 호스트가 수락해야 한다. 멤버 응답의 `user`가 참가자 `signedinUser.user`와 같은 형식이라 **People API 없이 이메일 ↔ 참가자를 맞출 수 있을 것으로 본다**(무료 계정에서 `members`가 동작하는지, `user`가 채워지는지는 미확인, 12절).
- 3: Zoom과 달리 **웹훅 없이 사후 조회**한다. 놓친 구간이 없고, 회의가 끝난 뒤 30일 안에만 부르면 된다(그 뒤엔 기록 삭제). 40분 끊김 같은 재개 시 Meet은 같은 공간에 새 `conferenceRecord`가 생기므로 공간 단위로 합친다. 학생 식별은 두 방식을 비교한다(Zoom 2-A/B처럼).
  - **A(기본 후보): 멤버 대응표.** 2를 거친 공간에서 `signedinUser.user` → 이메일 → 학번. 대리 출석이 어렵고(본인 Google 계정으로 로그인해야 함) 이름 규칙 안내가 필요 없다. 학생이 명단의 이메일과 **같은 Google 계정으로 로그인**해야 한다.
  - **B(대안): 표시 이름의 학번.** Zoom 6번과 같은 방식. 단 Meet은 **로그인 사용자의 표시 이름이 Google 계정 이름으로 고정**되어 회의마다 바꿀 수 없다. 학번을 이름에 넣을 수 있는 건 로그인하지 않은 게스트(`anonymousUser`)뿐이고, 개인 계정 회의에 게스트가 들어올 수 있는지도 미확인이다. 그래서 Meet에서는 B가 A보다 약하다.
  - 판정 로직(접속 구간 합치기·겹침 표시·지각·결석, 미확인 목록)은 Zoom `summarize_attendance`와 같다. 입력만 웹훅 이벤트 대신 `participantSessions`가 된다. 공통으로 뺄지는 구현 때 정한다(서비스 간 공유 위치는 CLAUDE.md에 없음).
  - 무료 Gmail 회의에서 `participants`·`participantSessions`가 실제로 채워지는지가 **이 유즈케이스 전체의 전제**다(12절, 3단계 첫 확인).
- 4: Zoom 4의 "취소"에 해당한다. 공간은 지울 수 없어서 잠그는 방식이다. 잠근 뒤 기존 링크로 들어오면 노크 화면이 뜬다.
- 범위 밖(보류): 마감 시각 강제 종료(`endActiveConference`)·진행 상태 추적(`spaces.get`의 `activeConference`) — Zoom에서 뺀 것과 맞춤, 필요하면 호출 하나로 추가. Calendar 예약·초대(학생 캘린더 불필요, 2026-10-06 상현). 녹화·트랜스크립트·회의록(무료 계정 불가). Pub/Sub 이벤트.
- scope: `meetings.space.created` 하나(People API를 쓰지 않는 A 방식 기준). 민감 scope라 앱 검증 대상이 된다(2절).

## 2. 인증

Google 4종과 같은 OAuth 클라이언트·동의 화면을 쓴다. 콘솔 설정·인가·갱신 절차는 `docs/google_docs.md` 2절, 공통 제약은 `docs/google_drive.md` 2절. Meet에서 추가로 할 일:

- GCP 콘솔 "API 및 서비스 → 라이브러리"에서 **Google Meet REST API**를 사용 설정한다. 예약에 Calendar를 쓰면 **Google Calendar API**, 참가자 이메일 변환에 **People API**도.
- OAuth 동의 화면 "데이터 액세스"에 `meetings.space.created`(민감)를 추가한다. **Google 4종에서 처음 들어가는 민감 scope**라서:
  - 테스트 상태에서는 그대로 동작하지만 동의 화면에 "확인되지 않은 앱" 경고가 뜬다. 테스트 사용자 100명 한도는 그대로.
  - 서비스 레포가 우리 계정 밖 사용자를 받으려면 **민감 scope 앱 검증**(scope별 사용 이유·데모 영상)이 필요하다. 제한 scope가 아니므로 CASA는 없다. 미검증 앱은 민감·제한 scope 사용 시 **프로젝트 평생 신규 사용자 100명** 상한.
  - `drive.readonly`/`drive.meet.readonly`(녹화 다운로드)를 넣으면 제한 scope라 CASA(12개월마다)가 따라온다. 1단계 판단: 넣지 않는다(10절 7항).
- scope가 늘면 **기존 로그인 사용자 전원 재동의**가 필요하다(`prompt=consent` 재로그인). 3단계에서 Meet scope를 넣는 순간 Docs·Sheets·Slides 실측용 토큰도 다시 받는다.
- `core/oauth.py`는 `REGISTERED_SCOPE_MODULES`에 `google_meet_scopes`를 추가하면 같은 인가 요청에 합쳐 보낸다(CLAUDE.md 새 서비스 규칙).
- Events API(9절)를 쓰면 **Workspace Events API·Cloud Pub/Sub API 사용 설정 + 결제 계정 연결**이 추가로 필요하다. OAuth 동의와 무관한 우리 프로젝트 쪽 설정이다.
- 사용자 모델: OAuth 연결은 교수자(공간 주최자). 학생은 앱을 연결하지 않고 `meetingUri`로 입장한다. `accessType=OPEN`이면 링크만으로, `RESTRICTED`면 멤버로 등록된 Google 계정만 입장한다.

## 3. scope 표

출처: Meet 인증 가이드, Events API 인증 가이드, Calendar 인증 가이드(2026-10-05). Calendar scope의 민감도는 공식 문서 표에 없어 콘솔에서 추가할 때 표시되는 등급을 3단계에서 기록한다.

| scope | 용도 | 등급 | 1단계 판단 |
| --- | --- | --- | --- |
| `https://www.googleapis.com/auth/meetings.space.created` | 앱이 만든 공간의 생성·수정·종료, 그 공간의 회의 기록·참가자·녹화/트랜스크립트 메타데이터·발화 읽기, 그 공간의 이벤트 구독 | 민감 | **기본.** `spaces.create`·`endActiveConference`는 이 scope만 허용 |
| `…/meetings.space.readonly` | 사용자가 접근할 수 있는 **모든** 공간(교수자가 Meet·Calendar UI로 만든 것 포함)의 메타데이터·회의 기록 읽기 | 민감 | 교수자가 직접 만든 미팅의 출석까지 다룰 때만 |
| `…/meetings.space.settings` | 사용자의 모든 Meet 통화 설정 보기·편집(다른 앱·Calendar가 만든 공간의 자동 녹화 등) | 비민감 | Calendar가 만든 링크에 자동 녹화를 걸 때만. 가이드와 레퍼런스가 `patch` 필요 scope를 다르게 적음(12절) |
| `…/drive.meet.readonly` | Meet이 만들거나 편집한 Drive 파일 보기(녹화 MP4 다운로드) | **제한** | 넣지 않는다(CASA) |
| `…/drive.readonly` | Drive 전체 읽기 | **제한** | 넣지 않는다 |
| `…/calendar.events.owned` | 사용자가 소유한 캘린더의 일정 보기·만들기·수정·삭제 | 미확인 | Calendar 예약을 넣을 때 후보. `calendar.events`보다 좁다 |
| `…/calendar.app.created` | 앱이 만든 보조 캘린더와 그 안의 일정만 | 미확인 | "Synsory 수업" 보조 캘린더를 따로 두는 설계면 가장 좁은 선택 |
| `…/contacts.readonly` 또는 `…/directory.readonly`(People API) | `users/{id}` → 이메일 변환 | 미확인 | 출석에서 이메일이 필요할 때만. `people.get`이 어떤 scope로 타인 프로필을 주는지 3단계 확인 |
| `meetings.conference.media.*` | Meet Media API(실시간 오디오·비디오) | 제한 | 쓰지 않는다(Developer Preview, 신규 가입 중단) |

- Events API: 회의·참가자·녹화/트랜스크립트 `fileGenerated` 이벤트는 `meetings.space.created` 또는 `readonly`로 구독된다. 회의록 이벤트와 녹화/트랜스크립트 `started`/`ended`의 scope는 문서에 없다(12절).
- `services/google_meet/scopes.py`는 `meetings.space.created` 하나로 시작하는 것이 1단계 권고다. 나머지는 2단계 유즈케이스에 따라 추가한다.

## 4. 엔드포인트 표

Base URL `https://meet.googleapis.com`. 출처는 v2 REST 레퍼런스. "scope" 열의 created = `meetings.space.created`, readonly = `meetings.space.readonly`, settings = `meetings.space.settings`.

**4.1 공간(spaces)**

| 메서드 | 경로 | 용도 | scope | 비고 |
| --- | --- | --- | --- | --- |
| `POST` | `/v2/spaces` | 공간 생성 | created만 | 본문 `{"config": {…}}`(생략 가능). 응답 `name`, `meetingUri`, `meetingCode`, `config`. **사용자당 분당 10회** |
| `GET` | `/v2/spaces/{space}` | 조회 | created · readonly · settings | `{space}` 자리에 `meetingCode`도 가능(대소문자 무시). `activeConference.conferenceRecord`가 있으면 진행 중 |
| `PATCH` | `/v2/spaces/{space}?updateMask=…` | 설정 변경 | created · settings | `updateMask` 생략 시 보낸 필드만, `*`면 전체 교체(빈 필드 삭제) |
| `POST` | `/v2/spaces/{space}:endActiveConference` | 진행 중 회의 종료 | created만 | 본문 `{}`, 응답 `{}`. 진행 중 회의가 없을 때의 응답은 미확인(12절) |
| `POST/GET/PATCH/DELETE` | `/v2/spaces/{space}/members[/{member}]`, `…/members:batchUpdate` | 멤버·공동 호스트 | create는 created | 2026-09-11 GA. `email` 필수, `role` `COHOST` 또는 미지정. 공동 호스트는 자동 녹화·진행자 설정은 못 바꾼다. 무료 계정 동작·초대 메일 발송·인원 상한 미확인 |

**`SpaceConfig` 주요 필드**

| 필드 | 값 | 비고 |
| --- | --- | --- |
| `accessType` | `OPEN` · `TRUSTED` · `RESTRICTED` | 기본은 관리자 정책, 없으면 `RESTRICTED`. 개인 계정의 기본값과 각 값의 실제 입장 동작은 3단계(12절) |
| `entryPointAccess` | `ALL` · `CREATOR_APP_ONLY` | `CREATOR_APP_ONLY`면 앱이 만든 진입점으로만 입장 |
| `moderation` + `moderationRestrictions{chatRestriction, reactionRestriction, presentRestriction, defaultJoinAsViewerType}` | `ON`/`OFF`, `HOSTS_ONLY`/`NO_RESTRICTION` | 2025-04-29 GA. 개인 계정은 UI상 호스트 관리 기능이 없어 동작 미확인 |
| `attendanceReportGenerationType` | `GENERATE_REPORT` · `DO_NOT_GENERATE` | 출석 보고서(Sheets)를 주최자 Drive에 + 이메일. 무료·Google One 불가 |
| `artifactConfig.{recordingConfig.autoRecordingGeneration, transcriptionConfig.autoTranscriptionGeneration, smartNotesConfig.autoSmartNotesGeneration}` | `ON`/`OFF` | 주최자만 설정 가능. "주최자 라이선스가 지원할 때만" 생성 |

**4.2 회의 기록과 하위 리소스(conferenceRecords)**

| 메서드 | 경로 | 용도 | 비고 |
| --- | --- | --- | --- |
| `GET` | `/v2/conferenceRecords` | 회의 목록 | `filter`: `space.name`, `space.meeting_code`, `start_time`, `end_time`(예: `space.name = "spaces/X" AND end_time IS NOT NULL`). `pageSize` 기본 25·최대 100, `start_time` 내림차순. 가이드는 "주최자인 회의만" 반환이라고 함 |
| `GET` | `/v2/conferenceRecords/{id}` | 회의 1건 | `startTime`, `endTime`(진행 중이면 없음), `expireTime`(종료 + 30일), `space` |
| `GET` | `…/{id}/participants` | 참가자 | `pageSize` 기본 100·최대 250, `filter` `earliest_start_time`·`latest_end_time`(`latest_end_time IS NULL` = 지금 접속 중). `signedinUser{user, displayName}` · `anonymousUser{displayName}` · `phoneUser{displayName}` 중 하나 + `earliestStartTime`·`latestEndTime` |
| `GET` | `…/participants/{p}/participantSessions` | 접속 세션 | 기기에서 들어올 때마다 1개. `startTime`·`endTime` |
| `GET` | `…/{id}/recordings` | 녹화 | `state`, `driveDestination{file, exportUri}`. 필터 없음 |
| `GET` | `…/{id}/transcripts` | 트랜스크립트 | `state`, `docsDestination{document, exportUri}` |
| `GET` | `…/transcripts/{t}/entries` | 발화 | `participant`, `text`, `languageCode`, `startTime`·`endTime`. `pageSize` 기본 10·**최대 100**, 시작 시각 오름차순. Docs 원본과 내용이 다를 수 있다고 명시. 종료 30일 뒤 삭제 |
| `GET` | `…/{id}/smartNotes` | Gemini 회의록 | `state`, `docsDestination`. 2026-04-02 GA |

모든 하위 리소스는 `get`도 있다. scope는 created 또는 readonly.

**4.3 Calendar로 예약할 때 (다른 API, 참고)**

| 메서드 | 경로 | 용도 | 비고 |
| --- | --- | --- | --- |
| `POST` | `https://www.googleapis.com/calendar/v3/calendars/{calendarId}/events?conferenceDataVersion=1&sendUpdates=…` | Meet 링크가 붙은 일정 생성 | 본문 `conferenceData.createRequest{requestId: <임의>, conferenceSolutionKey{type: "hangoutsMeet"}}`. `conferenceDataVersion`을 빼면 무시된다. 응답 `hangoutLink`, `conferenceData.conferenceId`(= `meetingCode`), `entryPoints[]`. `status.statusCode`가 `pending`이면 다시 읽는다. 반복은 `recurrence: ["RRULE:FREQ=WEEKLY;…"]`, 참석자 초대 메일은 `attendees` + `sendUpdates=all` |

Calendar로 만든 링크는 `spaces.get("spaces/{conferenceId}")`로 공간 이름(`spaces/{id}`)을 얻는다. Meet 공간 개요 가이드는 Calendar가 만든 공간을 **"다른 앱이 만든 공간"**으로 분류하므로 `meetings.space.created`로는 관리할 수 없고, 출석·설정에 `meetings.space.readonly`·`settings`가 필요하다. 이미 만든 공간을 일정의 Meet 회의로 붙이는 공식 경로는 없고, 2026-02-17부터 Google은 일정마다 `createRequest`로 새 회의를 만들라고 권고한다. 그래서 `spaces.create` 공간을 쓰려면 `meetingUri`를 일정 장소·설명에 텍스트로 넣는 수밖에 없다(Meet 버튼 없음). A·B·C안 비교와 Calendar 상세는 `docs/google_calendar.md`(2026-10-06).

**4.4 공통**: 페이지네이션은 `pageToken`/`nextPageToken`. 모든 리소스 이름은 `spaces/…`, `conferenceRecords/…/participants/…` 형식의 경로 문자열이다.

## 5. 요청·응답 샘플

5단계에서 `samples/google_meet/`에 채운다. 1단계에서는 없음. 저장 전 마스킹 대상: 토큰·`meetingUri`·`meetingCode`(링크만 있으면 입장 가능한 `OPEN` 공간이라 비밀값에 가깝다)·`signedinUser.user`·`displayName`·`phoneAccess.pin`·Drive 파일 ID·이메일.

## 6. 공통 모델 매핑

`core/models.py`의 `Meeting` 초안(Zoom 기준)과 Meet 응답의 대응. **필드 확정은 2단계 유즈케이스 뒤**에 하고 아래는 제안이다. `Meeting`의 독스트링·`provider` 기본값이 Zoom 전제이므로 Meet을 넣으면 `provider=Provider.GOOGLE`을 mapper가 명시한다.

| Meeting 필드 | 출처 | 비고 |
| --- | --- | --- |
| `id` | `spaces.name`(`spaces/{id}`) | `meetingCode`는 365일 후 재사용될 수 있어 키로 쓰지 않는다 |
| `topic` | 없음 | 공간에 제목이 없다. Calendar 일정 `summary` 또는 Synsory가 가진 액티비티 이름 |
| `status` | `activeConference` 있음 → `STARTED`; 없고 `conferenceRecords`에 `endTime` 있는 기록이 있음 → `ENDED`; 둘 다 없음 → `SCHEDULED` | 공간은 여러 번 열릴 수 있어 "종료"는 회차(`conferenceRecord`) 단위 개념이다 |
| `start_time` | Calendar 일정 `start` 또는 Synsory 값. 실제 시작은 `conferenceRecord.startTime` | |
| `duration_minutes` | Calendar 일정 길이 또는 Synsory 값 | 실제 길이는 `endTime - startTime` |
| `join_url` | `meetingUri` | |
| `host_id` | 없음(공간 응답에 주최자 필드 없음) | 연결한 교수자 = 주최자 |
| `has_recording` | `recordings[].state == FILE_GENERATED` | 개인 무료 계정은 항상 false |
| `has_transcript` | `transcripts[].state == FILE_GENERATED` | 같음 |

추가 제안: `conference_id`(회차, `conferenceRecords/{id}`), `actual_start`·`actual_end`, `meeting_code`(표시용). 출석은 Zoom과 마찬가지로 `Participant` 공통 모델(표시 이름, 식별자, 최초 입장·최종 퇴장, 세션 수) 추가 여부를 2단계에서 본다. Meet의 `participantSessions`가 Zoom의 입장·퇴장 이벤트 쌍과 같은 정보다.

## 7. 에러와 예외 케이스

Meet REST API 전용 에러 코드 문서는 없다. Google 표준 JSON 에러(`{"error": {"code", "message", "status", "details"}}`)로 보고 5단계에서 실측 표를 채운다. 문서에서 확인되거나 예상되는 것:

| 상황 | HTTP | 비고 |
| --- | --- | --- |
| 쿼터 초과 | 429 | 공식: truncated exponential backoff(`2^n초 + 무작위 ≤1초`, 최대 32~64초) |
| Meet API 미사용 설정 | 403 | "API has not been used in project…" (Google 공통) |
| scope 부족(예: Calendar가 만든 공간을 created로 조회) | 403 | 5단계 실측 |
| 존재하지 않는 공간·만료된 `meetingCode` | 404 | 5단계 |
| 30일 지난 회의 기록 | 404 | `expireTime` 이후 |
| 진행 중 회의 없는데 `endActiveConference` | 미확인 | 5단계(Zoom 유즈케이스 7과 같은 확인) |
| 무료 계정에서 `artifactConfig` ON | 미확인 | 에러 없이 저장되고 파일만 안 생길 것으로 예상(문서: "only if license supports") |
| 개인 계정에서 Meet API 자체가 막힘 | 미확인 | 3단계 첫 호출. 막히면 이 서비스 전체가 보류 |

에러는 Google 4종과 같은 `GoogleApiError`(Docs·Drive client에서 쓰는 형태)로 올린다.

## 8. 쿼터 · rate limit · 플랜 제약

공식 Usage limits(2026-10-05). 쿼터는 프로젝트별, "사용자당"은 그 프로젝트 안에서의 사용자당이다.

| 구분 | 프로젝트당 분당 | 사용자당 분당 |
| --- | --- | --- |
| 읽기 | 6,000 | 600 |
| 쓰기 | 1,000 | 100 |
| **`spaces.create`** | **100** | **10** |

- `spaces.create`가 따로 좁다. 그룹마다 공간을 만들면 **교수자 한 명이 분당 10개**, 서비스 전체가 분당 100개다. 학기 초 여러 교수자가 동시에 액티비티를 만들면 프로젝트 한도에 걸릴 수 있다 → 공간을 미리 만들어 재사용하거나 생성 큐를 둔다(10절 4항).
- 발화(`entries`)는 페이지당 최대 100개라 1시간 수업 트랜스크립트는 수십 회 읽기다. 사용자당 분당 600 안에서는 여유가 있다.
- 공식 문구: "Exceeding quota limits will incur charges to your Google Cloud billing account beginning in 2026." Docs·Drive·Sheets·Forms와 같은 계열의 문구. 시행 여부는 핸드오프 직전 재확인.
- Calendar API: 프로젝트당 분당 10,000, 사용자당 분당 600, 프로젝트당 하루 1,000,000. 초과 시 403/429 `usageLimits`. 별도로 일정 생성·외부 초대에 Calendar 사용 한도가 있다.

**플랜 제약** — 1단계 요약의 "플랜별 Meet 기능" 표. 요약하면 **상현 개인 무료 계정으로 실측 가능한 범위는 공간 생성·설정·종료, 회의 기록·참가자·세션 조회(개인 계정 지원 시)까지**이고, 녹화·트랜스크립트·회의록·출석 보고서는 Google One 2TB+ 또는 Workspace 유료 계정이 있어야 한다. 3명 이상 회의는 60분에 끊긴다.

## 9. 웹훅 (해당 시)

Meet 자체에는 웹훅이 없고 **Google Workspace Events API**가 이벤트를 **Cloud Pub/Sub 토픽으로만** 보낸다(`notificationEndpoint`는 `pubsubTopic`만). FastAPI로 받으려면 Pub/Sub **push 구독**을 https 주소(ngrok)로 걸어야 한다. Forms watch와 같은 구조이고, Zoom의 웹훅과 다르다.

**전제**: 결제 계정이 연결된 Cloud 프로젝트, Workspace Events API·Pub/Sub API 사용 설정, 토픽에 `meet-api-event-push@system.gserviceaccount.com` Publisher 권한, 토픽과 구독이 같은 프로젝트. Pub/Sub 무료 사용량은 월 10GiB.

**구독 대상(`targetResource`)**: `//meet.googleapis.com/spaces/{space}`(공간 하나) 또는 `//cloudidentity.googleapis.com/users/{user}`(사용자가 소유한 모든 공간). 개인 계정에서 `users/` 대상이 되는지는 미확인.

**이벤트 13종**

| 분류 | 이벤트 타입 | 비고 |
| --- | --- | --- |
| 회의 | `google.workspace.meet.conference.v2.started` / `.ended` | 주최자 외에 Calendar 초대 대상자도 `started`는 받을 수 있다 |
| 참가자 | `google.workspace.meet.participant.v2.joined` / `.left` | |
| 녹화 | `google.workspace.meet.recording.v2.started` / `.ended` / `.fileGenerated` | |
| 트랜스크립트 | `google.workspace.meet.transcript.v2.started` / `.ended` / `.fileGenerated` | 초대 대상자도 `fileGenerated`는 받을 수 있다 |
| 회의록 | `google.workspace.meet.smartNote.v2.started` / `.ended` / `.fileGenerated` | 2026-04-02 GA |

- **페이로드에 리소스 이름만** 온다(`{"conferenceRecord": {"name": "conferenceRecords/…"}}`). `includeResource`는 Chat·Drive 이벤트 전용. 받은 뒤 `conferenceRecords.get`·`participants.list` 등으로 다시 조회한다. CloudEvents 형식, Pub/Sub 메시지 `data`는 base64.
- **수명 최대 7일**, 자동 갱신 없음. `subscriptions.patch`로 `ttl`을 다시 넣는다(`ttl=0`이면 최대치). 만료 12시간·1시간 전 수명 주기 이벤트가 오지만 공식 문서도 `expireTime`을 직접 추적하라고 권한다. scope 철회·리소스 삭제 시 `SUSPENDED`.
- API 버전은 `v1`(Meet용 `v1beta`는 2025-04-30 폐지).

**1단계 판단**: Forms와 같이 **폴링을 기본**으로 둔다. 종료 감지는 `conferenceRecords.list(filter=space.name=… AND end_time IS NOT NULL)`, 진행 중 확인은 `spaces.get`의 `activeConference`. 쿼터(사용자당 분당 600 읽기)로 공간 수십 개를 분 단위 폴링해도 충분하다. Pub/Sub은 "회의 시작 즉시 반응" 유즈케이스가 있고 결제 계정 연결이 결정됐을 때만 테스트한다.

## 10. 함정과 권장 패턴

공식 문서 기준(미실측). 5단계에서 확인된 것은 날짜를 붙여 갱신한다.

1. **예약 = Calendar.** Meet 공간에는 시각이 없다. "시각이 있는 미팅"이 필요하면 Calendar API가 붙고, 그러면 Calendar scope 추가·Calendar 호출 위치(새 `services/google_calendar/`, Drive처럼 공유 레이어) 결정이 따라온다. CLAUDE.md는 client가 자기 서비스 API만 부르게 하므로 Meet client에 Calendar 호출을 넣지 않는다.
2. **공간은 재사용된다.** 같은 링크로 여러 번 회의가 열리고 회차마다 `conferenceRecord`가 새로 생긴다. Synsory의 "미팅 1건"을 공간에 둘지 회차에 둘지 2단계에서 정한다. 반복 수업은 공간 하나로 충분하다.
3. **DB 키는 `spaces/{id}`.** `meetingCode`는 마지막 사용 후 약 365일이면 만료되어 다른 공간에 재사용될 수 있다.
4. **`spaces.create`는 사용자당 분당 10회.** 그룹 30개면 3분이 걸린다. 생성은 큐로 돌리고 429면 백오프. 액티비티 생성 화면에서 동기 호출로 묶지 않는다.
5. **`meetings.space.created`의 경계는 Drive `drive.file`과 같다.** 앱이 만든 공간만 보인다. 교수자가 Meet·Calendar UI로 만든 미팅의 출석을 원하면 민감 scope `meetings.space.readonly`가 추가로 필요하다. Picker 같은 우회로는 없다.
6. **민감 scope가 처음 들어온다.** Docs·Sheets·Slides·Forms는 비민감 `drive.file`로 끝났지만 Meet은 기본 scope부터 민감이다. 서비스 레포 출시 일정에 Google 앱 검증(수 주)을 넣는다. PLAN.md "참고: 심사 절차"에 해당.
7. **녹화 MP4는 제한 scope.** `drive.meet.readonly`/`drive.readonly`가 필요해 CASA가 따라온다. 녹화가 꼭 필요하지 않으면 `exportUri`(Drive 링크)를 Synsory에 보여주는 데서 멈춘다. 트랜스크립트는 `entries` API로 텍스트를 받으면 Drive scope가 필요 없다.
8. **회의 기록 30일.** 출석·발화는 종료 후 30일 안에 Synsory DB로 옮긴다. 폴링이 끊겨도 30일 안에만 다시 돌면 복구된다.
9. **참가자 식별.** `signedinUser.user`(`users/{id}`)는 이메일이 아니다. People API로 바꿔도 프로필을 못 받을 수 있다고 명시. 익명(`anonymousUser`)은 표시 이름뿐. 확실한 식별이 필요하면 `accessType=RESTRICTED` + `spaces.members`(수강생 이메일 등록)로 Google 로그인 사용자만 들어오게 하는 방안을 5단계에서 확인한다. Zoom 10절 9항과 같은 문제.
10. **"종료"는 회차 단위.** `endActiveConference`로 끝내도 공간은 남아 같은 링크로 다시 열 수 있다. "마감 후 재입장 차단"이 필요하면 `accessType`을 `RESTRICTED`로 바꾸고 멤버를 지우는 방식을 검토한다(삭제 API는 공간에 없다).
11. **산출물 생성은 늦게 온다.** `recordings`·`transcripts` 상태는 `STARTED` → `ENDED`(파일 생성 대기) → `FILE_GENERATED`. 종료 직후엔 `ENDED`라서 파일 ID가 없다. 생성까지 걸리는 시간은 문서에 없다.
12. **출석을 평가에 쓰는 것에 대한 문구.** 개요에 "성과 추적·사용자 평가용이 아니다"라고 적혀 있다. 금지 조항인지 권고인지 약관 수준 확인이 필요하고, 앱 검증 때 사용 이유 설명에 영향을 준다(12절).
13. **`artifactConfig`는 라이선스가 받쳐야 한다.** 무료 계정에서 ON으로 저장돼도 파일이 생기지 않는 것으로 보인다. 기능 가용성은 교수자 계정 플랜에 달려 있고 API로 플랜을 묻는 방법은 Meet API에 없다(Zoom `/users/me` `type`에 해당하는 것이 없음).
14. **문서 간 상충이 여럿 있다.** `conferenceRecords.list`를 참가자도 부를 수 있는지(가이드 "주최자만" vs 2025-02 릴리스 노트 "모든 참가자"), `spaces.patch`의 필요 scope(가이드 settings vs 레퍼런스 created·settings), Google One의 트랜스크립트 지원. 실측으로 정한다(12절).
15. **SDK 없이 REST.** 리소스가 단순한 GET 위주이고 JSON이다. httpx로 충분. 예외 근거 없음.

## 11. 샘플 코드 (`usecases.py`의 흐름을 기준으로)

5단계에서 `app/services/google_meet/usecases.py`를 구현한 뒤 작성한다. 구조는 Docs와 같다: `MeetClient(access_token)`, 유즈케이스 함수는 FastAPI 없이 동작, Drive 메타데이터가 필요하면 usecases가 `google_drive.client`를 불러 mapper에 함께 넘긴다.

## 12. 미확인 · 보류 항목

| 항목 | 확인 방법 · 시점 |
| --- | --- |
| **개인 Gmail 계정에서 Meet REST API(`spaces.create`·`conferenceRecords.list`)가 동작하는지** | 3단계 첫 호출. 막히면 Meet 전체 보류, PLAN.md에 기록 |
| 무료 계정 회의에서 `participants`·`participantSessions`가 채워지는지 | 5단계. 상현 + 테스트 계정(koreaji8)으로 2명 회의 |
| 개인 계정 공간의 `accessType` 기본값, `OPEN`·`RESTRICTED`에서 Google 계정 없는 사람·다른 계정의 실제 입장 동작 | 5단계. koreaji8과 로그아웃 브라우저로 입장 |
| `spaces.members`가 무료 계정에서 되는지, `COHOST` 지정 결과, 초대 메일 발송 여부, 멤버 수 상한, create 외 메서드 scope | 5단계(멤버를 유즈케이스에 넣는 경우) |
| 진행 중 회의 없을 때 `endActiveConference` 응답 | 5단계 |
| 무료 계정에서 `artifactConfig` ON 저장 시 에러 여부 | 5단계(비용 0) |
| `spaces.patch` 필요 scope(가이드 settings vs 레퍼런스 created) | 5단계. created만 든 토큰으로 patch |
| `conferenceRecords.list`를 참가자 계정이 호출할 때 결과(가이드 vs 릴리스 노트 상충) | 5단계. koreaji8로 로그인한 토큰이 필요해 우선순위 낮음 |
| Calendar로 만든 Meet 공간이 `meetings.space.created`로 조회·종료되는지 | Calendar를 유즈케이스에 넣는 경우 5단계 |
| Calendar scope(`calendar.events.owned`, `calendar.app.created`)의 민감도 | 3단계에서 콘솔 "데이터 액세스"에 추가할 때 표시 확인 |
| People API로 `users/{id}` → 이메일 변환 시 필요한 scope와 성공 범위 | 출석 유즈케이스가 확정되면 5단계 |
| `drive.file`로 Meet이 만든 녹화·트랜스크립트 파일을 읽을 수 있는지 | 녹화 가능한 계정이 생기면. 지금 계정으로는 파일이 생기지 않는다 |
| Google One 2TB+의 트랜스크립트 지원(support 문서 상충), "Take notes for me"가 되는 AI 플랜 이름 | 녹화·트랜스크립트 유즈케이스를 넣고 플랜 결제를 검토할 때 |
| 녹화·트랜스크립트 파일 생성까지 걸리는 시간 | 녹화 가능한 계정에서 5단계 |
| Events API가 개인 계정에서 되는지(`users/` 대상 포함), 회의록·녹화 started/ended 이벤트 scope | Pub/Sub 테스트를 결정한 경우 |
| Pub/Sub 테스트 여부(결제 계정 연결 필요) | 2단계. Forms와 함께 결정 |
| "성과 추적·사용자 평가용이 아님" 문구가 약관상 제한인지 | 출석을 성적에 연결하는 유즈케이스가 생기면 Meet API 약관 확인 |
| 2026년 쿼터 초과 과금의 실제 시행 여부 | 핸드오프 직전 재확인(Google 공통) |
| Meet add-on(회의 안 측면 패널 앱) 검토 | 범위 밖. 회의 안에서 Synsory 액티비티를 띄우는 요구가 생기면 별도 탐색. 개인 개발자는 Marketplace 공개 등록이 필요 |
| Meet Media API | 범위 밖. Developer Preview이고 신규 가입 중단, 제한 scope |

## 출처 (2026-10-05 확인)

- Meet REST API 개요 — https://developers.google.com/workspace/meet/api/guides/overview
- REST 레퍼런스 v2 — https://developers.google.com/workspace/meet/api/reference/rest/v2
- spaces(SpaceConfig) — https://developers.google.com/workspace/meet/api/reference/rest/v2/spaces ; create · get · patch · endActiveConference — 같은 경로 `/create`, `/get`, `/patch`, `/endActiveConference`
- spaces.members — https://developers.google.com/workspace/meet/api/reference/rest/v2/spaces.members ; 멤버 가이드 — https://developers.google.com/workspace/meet/api/guides/meeting-space-members
- 공간 개요·설정 가이드 — https://developers.google.com/workspace/meet/api/guides/meeting-spaces-overview , https://developers.google.com/workspace/meet/api/guides/meeting-spaces-configuration
- conferenceRecords · list — https://developers.google.com/workspace/meet/api/reference/rest/v2/conferenceRecords , …/conferenceRecords/list ; 회의 가이드 — https://developers.google.com/workspace/meet/api/guides/conferences
- participants · participantSessions — https://developers.google.com/workspace/meet/api/reference/rest/v2/conferenceRecords.participants , …participants.participantSessions ; 참가자 가이드 — https://developers.google.com/workspace/meet/api/guides/participants
- recordings · transcripts · entries · smartNotes — https://developers.google.com/workspace/meet/api/reference/rest/v2/conferenceRecords.recordings , …transcripts , …transcripts.entries/list , …smartNotes ; 산출물 가이드 — https://developers.google.com/workspace/meet/api/guides/artifacts
- 인증·scope 등급 — https://developers.google.com/workspace/meet/api/guides/authenticate-authorize
- Usage limits — https://developers.google.com/workspace/meet/api/guides/limits
- 릴리스 노트 — https://developers.google.com/workspace/meet/release-notes
- Media API — https://developers.google.com/workspace/meet/media-api/guides/overview , https://developers.google.com/workspace/meet/media-api/guides/get-started
- Add-ons — https://developers.google.com/workspace/meet/add-ons/guides/overview
- Workspace Events API: Meet 이벤트 — https://developers.google.com/workspace/events/guides/events-meet ; 개요 — https://developers.google.com/workspace/events ; 인증 — https://developers.google.com/workspace/events/guides/auth ; 구독 생성 — https://developers.google.com/workspace/events/guides/create-subscription ; subscriptions 리소스 — https://developers.google.com/workspace/events/reference/rest/v1/subscriptions ; 갱신 — https://developers.google.com/workspace/events/guides/update-subscription ; Python 튜토리얼 — https://developers.google.com/workspace/meet/api/guides/tutorial-events-python ; 릴리스 노트 — https://developers.google.com/workspace/events/release-notes
- Pub/Sub 가격 — https://cloud.google.com/pubsub/pricing
- Calendar: 일정 생성(conferenceData) — https://developers.google.com/workspace/calendar/api/guides/create-events ; events.insert — https://developers.google.com/workspace/calendar/api/v3/reference/events/insert ; scope — https://developers.google.com/workspace/calendar/api/auth ; 쿼터 — https://developers.google.com/workspace/calendar/api/guides/quota
- Meet 플랜: 통화 시간·참가자 — https://support.google.com/meet/answer/7317473 ; 녹화 — https://support.google.com/meet/answer/9308681 ; 트랜스크립트 — https://support.google.com/meet/answer/12849897 ; Take notes for me — https://support.google.com/meet/answer/14754931 ; 프리미엄 기능 표 — https://support.google.com/meet/answer/10459644 ; 출석 — https://support.google.com/meet/answer/10090454 ; 호스트 관리 — https://support.google.com/meet/answer/10885841 ; Google One Meet 혜택 — https://support.google.com/googleone/answer/12351029
- OAuth: 테스트 상태 refresh token 7일 — https://developers.google.com/identity/protocols/oauth2 ; 미검증 앱 100명 — https://support.google.com/cloud/answer/7454865 ; 제한 scope 검증(CASA) — https://developers.google.com/identity/protocols/oauth2/production-readiness/restricted-scope-verification
