# Zoom 연동 스펙

상태: 6단계(스펙 문서화) 완료 · 7단계(핸드오프) 대기
최종 수정: 2026-10-05 · 작성: 상현
확인 기준: 공식 문서 2026-10-04~05(developers.zoom.us 가이드·공식 OpenAPI JSON, support.zoom.com, zoom.us/pricing). **실측 2026-10-05**: 개인 무료(Basic) 계정 + General App(User-managed, Development) + ngrok 고정 도메인. 실측한 것은 각 절에 날짜를 붙였다.

이식 대상(studio에 TS로 이식, 위치는 11절 "studio 이식"): `app/services/zoom/{client,mapper,scopes,usecases}.py`와 이 문서. 웹훅 URL 검증 응답 생성과 서명 검증은 FastAPI 없는 순수 함수로 `usecases.py`에 두어 함께 이식하고, `router.py`는 그것을 부르기만 한다. Zoom은 Google처럼 공유 레이어(Drive)가 없으므로 이 문서 하나가 Zoom 전부를 다룬다. Base URL: `https://api.zoom.us/v2`(토큰 응답의 `api_url`이 다르면 그 값).

---

## 1단계 요약: 할 수 있는 일 · 못 하는 일 · 눈에 띄는 제약

2단계에서 유즈케이스를 고를 때 보는 한 장이다. 아래 3~12절은 이 요약의 근거다.

**리소스.** 사용자(`/users/me`, user-managed 앱은 `me`만) → 미팅(`id`: int64 미팅 번호, 10자리 초과 가능 · `uuid`: 인스턴스마다 새로 생성, `/`로 시작하거나 `//`를 포함하면 **이중 URL 인코딩**) → 과거 미팅 인스턴스·참가자 → 클라우드 녹화 파일(`recording_files[]`: MP4 · M4A · TRANSCRIPT(VTT) · CHAT · SUMMARY …) · AI Companion 요약 · 트랜스크립트. 웹훅은 미팅 시작·종료·참가자 입퇴장·녹화 완료·트랜스크립트 완료·요약 완료 등 108종(Meetings 영역).

**할 수 있는 일 — Basic(무료)에서 되는 것**

| 분류 | 내용 | 메서드 | 조건 |
| --- | --- | --- | --- |
| 미팅 예약 | 즉시(1)·예약(2)·반복 고정 없음(3)·반복 고정(8) 미팅 생성. 주제·시작 시각(UTC + `timezone`)·길이(1~1440분)·패스코드·대기실·호스트 전 입장·자동 녹화·음소거·인증 필요 여부. 응답에 `join_url`(참가자용) · `start_url`(호스트 전용, **2시간 만료**) · `password` | `POST /users/me/meetings` | 미팅 자체는 40분 제한. `auto_recording=cloud`는 Pro |
| 소회의실 사전 배정 | 그룹명 + 참가자 **이메일** 목록으로 소회의실을 미리 만든다(`settings.breakout_room.rooms[]`) | 생성·수정 본문 | 이메일로 매칭하려면 학생이 그 이메일 Zoom 계정으로 로그인해 들어와야 함(12절) |
| 조회·수정·삭제 | 미팅 상세(`status`: `waiting` / `started`만), 수정(`PATCH`, 반복 미팅은 `occurrence_id`), 삭제(반복은 `occurrence_id` 없으면 시리즈 전체), 초대문 텍스트, 상태 변경(`end`) | `GET/PATCH/DELETE /meetings/{id}`, `GET …/invitation`, `PUT …/status` | |
| 목록 | 사용자의 예약 미팅 목록(`type`: scheduled · live · upcoming · previous_meetings, 최대 6개월). 즉시 미팅은 안 나옴 | `GET /users/me/meetings` | |
| 실시간 이벤트 | 미팅 시작·종료, 참가자 입장·퇴장(이름·이메일·시각·`leave_reason`), 미팅 생성·수정 | 웹훅 `meeting.started` · `meeting.ended` · `meeting.participant_joined/left` · `meeting.created/updated` | 플랜 조건 없음. `meeting.deleted`만 Pro |
| 계정 정보 | 사용자 플랜 유형(`type`: 1 Basic · 2 Licensed), 시간대, PMI, 녹화·AI 설정 값 | `GET /users/me`, `GET /users/me/settings` | |

**할 수 있는 일 — Pro 이상에서만 되는 것** (Basic으로 부르면 400 code 200 "Only available for paid account")

| 분류 | 내용 | 메서드 | 조건 |
| --- | --- | --- | --- |
| 종료 후 정보 | 종료된 미팅의 실제 시작·종료·길이·참가자 수·`has_meeting_summary`, 반복 미팅의 인스턴스 목록(15개월) | `GET /past_meetings/{id}`, `GET /past_meetings/{id}/instances` | 상세는 **유료 계정만**으로 명시. 인스턴스 목록의 플랜 전제는 미확인(12절) |
| 출석 | 종료된 미팅 참가자별 입장·퇴장 시각·체류 초. 이메일은 호스트 계정 밖 사용자면 **빈 문자열** | `GET /past_meetings/{id}/participants`, `GET /report/meetings/{id}/participants`(admin scope) | Basic에서는 웹훅 누적으로 대신한다 |
| 클라우드 녹화 | 녹화 목록(기간 최대 1개월), 미팅별 파일 목록, 다운로드(Bearer 토큰 헤더 + 리다이렉트 추종), 휴지통·영구 삭제, 녹화 완료 웹훅(`download_token` 24시간) | `GET /users/me/recordings`, `GET/DELETE /meetings/{id}/recordings`, 웹훅 `recording.completed` | + 클라우드 녹화 설정 |
| 트랜스크립트 | ① 클라우드 녹화의 `TRANSCRIPT`(VTT) 파일 — "Create audio transcript" 설정 필요. ② AI Companion 미팅 트랜스크립트 다운로드 URL. 완료 웹훅 2종 | ① 녹화 파일 목록 + `recording.transcript_completed` ② `GET /meetings/{id}/transcript` + `meeting.aic_transcript_completed` | ①의 웹훅 전제는 문서상 Business 이상(12절) |
| AI 요약 | 미팅 요약 본문(`summary_content`, Markdown) 조회·삭제, 사용자의 요약 목록, 완료 웹훅 | `GET /meetings/{uuid}/meeting_summary`, `GET /users/me/meeting_summaries`, 웹훅 `meeting.summary_completed` | + "Meeting Summary with AI Companion" 설정 |
| 등록·설문 | 사전 등록(승인 자동/수동)·일괄 등록, 폴 생성·결과 | `…/registrants`, `…/batch_registrants`, `…/polls` | Licensed 호스트. "Registration cannot be enabled for a basic user" |

**못 하는 일 · 주의할 일**

- **무료(Basic) 호스트 미팅은 40분 제한.** 1:1도 포함("1 host, 1 or more participants"). 호스트 혼자 있을 때만 예외. 유료 라이선스는 30시간. 참가자 상한은 Basic·Pro 모두 100명.
- **Basic에서 안 되는 API**: 과거 미팅 상세·참가자, 클라우드 녹화 전부, 트랜스크립트, AI 요약 API, 등록·폴, 미팅 삭제 웹훅(`meeting.deleted`는 Pro 전제). 가격 페이지의 "Basic 월 3회 요약"은 UI 기능이고 요약 API 전제는 Pro 이상이다.
- **미팅 `status`에 `ended`가 없다.** 종료는 웹훅 `meeting.ended`로 받거나 `GET /past_meetings/{id}`(유료)로 확인한다. `meeting.ended`의 `duration`은 **예정 길이**이고 실제 길이는 `end_time - start_time`으로 계산한다.
- **참가자 이메일은 호스트 계정 밖이면 빈 문자열.** 학생이 개인 Zoom 계정이거나 로그인 없이 들어오면 `user_email`·`email`이 비어 있다("with some exceptions", 규칙 미확인). 학생 식별은 이름, 사전 등록(`registrant_id`, Pro), 또는 Synsory가 발급한 참가 링크 설계로 풀어야 한다. → 2026-10-05 표시 이름의 학번 매칭으로 결정(1절 6번).
- **미팅 생성·수정은 사용자당 하루 100회(UTC 00:00 리셋).** 그룹 100개 넘는 수업을 하루에 만들 수 없다.
- **리다이렉트 URI는 https 필수.** `http://localhost`는 등록 불가. 루프백 `http://127.0.0.1:…`은 **PKCE 공개 클라이언트 전용**이고 client secret을 쓰는 서버형 앱은 "Do not use". → Zoom만 ngrok https 주소(CLAUDE.md 전제 확인). 웹훅 수신 URL도 공개 https FQDN 필수.
- **미공개 앱은 개발자 본인 계정 사용자만 인가 가능.** 다른 Zoom 계정(다른 교수자)이 연결하려면 Beta 공유 승인(3~4영업일, 4주 한시) 또는 게시 심사(public/unlisted)가 필요하다. 테스트 중에는 상현 계정 하나로만 로그인된다.
- **토큰**: access 1시간, refresh **90일**, 갱신마다 새 refresh token이 오고 "항상 최신 것을 쓰라"고 명시. 2023-02-14부터 토큰을 URL 쿼리로 보내면 거부(헤더·본문만). 녹화 다운로드도 `Authorization: Bearer` 헤더.
- **무료 계정 rate limit은 초당 + 일일 한도** (Light 4/초·6,000/일, Medium 2/초·2,000/일, Heavy 1/초·1,000/일). 계정 단위이며 설치된 모든 앱이 공유한다.
- 웹훅은 **3초 안에 2xx**를 돌려줘야 하고, 5xx·네트워크 오류만 3회 재시도(5분·20분·60분 후), 4xx는 재시도 없음. URL은 72시간마다 재검증되고 6회 연속 실패하면 구독이 꺼진다.
- `start_url`은 호스트 로그인과 같다. 저장·노출하지 않고 필요할 때 `GET /meetings/{id}`로 다시 받는다.
- 녹화 저장 용량은 Pro 라이선스당 10GB(계정 풀링). 휴지통 30일. Pro $16.99/월(월납) · $14.16/월(연납), USD만 표기.

**유즈케이스**: 2단계에서 확정한 6개는 1절. 위 "할 수 있는 일 — Pro 이상"(녹화·트랜스크립트·요약·과거 미팅 참가자·사전 등록)은 Pro 결제가 결정될 때까지 보류다.

---

## 1. 이 서비스로 하는 일 (유즈케이스)

2026-10-05 상현 확정. **무료(Basic) 계정으로 실측할 수 있는 것만** 먼저 한다(4.1절 API만 사용). 1단계에서 후보였던 "마감 시각에 강제 종료"(`PUT …/status` `end`)와 "시작·종료 웹훅으로 상태 추적"(`meeting.started`/`ended`)은 필요 없다고 보고 뺐다. 출석은 처음에 보류했다가 **표시 이름의 학번 매칭 방식으로 6번에 넣었다**(모두 2026-10-05 상현). 웹훅은 6번만 쓴다. 전제는 Google과 같다: **OAuth로 연결하는 사용자는 교수자(호스트)**이고, 학생은 Zoom 계정 없이 `join_url`로 입장한다. Zoom은 학생에게 메일을 보내지 않으므로 `join_url` 배포는 Synsory 몫이다.

| # | 유즈케이스 | 호출 순서 | usecases 함수 |
| --- | --- | --- | --- |
| 1 | 교수자 플랜을 확인한다(Basic이면 40분 넘는 예약에 경고) | `GET /users/me` → `type`(1 Basic · 2 Licensed), `timezone` | `get_host_profile` |
| 2 | 액티비티의 그룹마다 미팅을 예약하고 `join_url`을 돌려준다 | **A(기본)** 그룹마다 `POST /users/me/meetings`(type 2, 주제 템플릿, `start_time`·`duration`·`timezone`, 대기실·호스트 전 입장) → 그룹별 `Meeting`. **B(비교용)** `POST` 1회 + `settings.breakout_room.rooms[]{name, participants[이메일]}` → `Meeting` 1개 | `create_group_meetings` (A), `create_breakout_meeting` (B) |
| 3 | 정기 회의(매주 반복 수업)를 만든다 | `POST /users/me/meetings`(type 8, `recurrence{type 2 매주, repeat_interval, weekly_days, end_date_time 또는 end_times≤60}`) 1회 → `Meeting` + 회차 목록(`occurrences[]`) | `create_recurring_meeting` |
| 4 | 일정을 바꾸거나 취소한다(반복 미팅은 한 회차만 또는 시리즈 전체) | 변경: `PATCH /meetings/{id}`(회차면 `occurrence_id`, 204) → `GET /meetings/{id}`로 바뀐 값 반환. 취소: `DELETE /meetings/{id}`(회차면 `occurrence_id`, 204) | `reschedule_meeting`, `cancel_meeting` |
| 5 | 교수자가 Synsory에서 "시작"을 누르면 호스트로 미팅을 연다 | 누를 때마다 `GET /meetings/{id}` → `start_url` → 라우터가 302 리다이렉트. 저장하지 않음 | `get_start_url` |
| 6 | 미팅 출석을 자동으로 집계한다(학생 표시 이름의 학번으로 수강생과 매칭) | 웹훅 `POST /zoom/webhook`: 서명 검증 → `endpoint.url_validation`이면 확인 응답, 아니면 `meeting.participant_joined`/`left` 저장 → 미팅이 끝나면 표시 이름에서 학번 추출 → 명단 매칭 → 학생별 접속 구간 합산(재입장·여러 기기) → 출석·지각 판정 값과 미확인 접속 목록 반환 | `verify_signature`, `url_validation_response`, `summarize_attendance` |

**유즈케이스별 메모**

- 1: Synsory가 예약 화면에서 `type == 1`이면 "40분에 끊김" 경고를 띄우는 근거다. 응답 `timezone`은 2·3의 기본 `timezone`으로 쓴다. 반환값을 담을 공통 모델이 필요한지는 구현 때 정한다(서비스 폴더에 모델을 두지 않는 규칙).
- 2: 주제 템플릿은 Docs와 같은 플레이스홀더(`{{activity_name}}`, `{{team_name}}`)를 쓴다. A는 그룹 수만큼 호출하므로 **하루 100회(생성+수정 합산, UTC)** 안에서 그룹 수를 센다. 학생은 로그인 없이 들어온다(`meeting_authentication=false`). B는 호출 1회지만 학생이 **그 이메일의 Zoom 계정으로 로그인해야** 자동 배정된다(10절 10항). **B는 계정 설정 "예약 시 참가자를 소회의실에 할당"이 켜져 있어야 저장된다**(꺼져 있으면 200인데 조용히 버려짐, 10절 10항). 2026-10-05 설정을 켠 뒤 방 목록 저장까지 실측했다. 자동 배정은 학생 역할 Zoom 계정이 생기면 확인한다(12절). Docs 유즈케이스 2처럼 A를 기본으로, B를 비교용으로 함께 구현한다.
- 3: 매주 반복 수업을 미팅 하나로 만든다. `join_url`이 학기 내내 같고 호출도 1회다. `weekly_days`는 1=일요일 … 7=토요일(`"2,4"` = 월·수). 회차마다 40분 제한(Basic). 그룹별 정기 회의가 필요하면 2-A에 `recurrence`를 넘기는 확장으로 처리한다(호출 수는 그룹 수 그대로).
- 4: `PATCH`도 하루 100회에 들어간다. 반복 미팅의 한 회차만 바꾸면 수정 가능한 필드가 제한된다(4.1절). `DELETE`에 `occurrence_id`가 없으면 **시리즈 전체**가 지워진다. 그래서 함수에서 회차 취소와 전체 취소를 인자로 명시하게 한다.
- 5: `start_url`은 2시간이면 만료되고 받은 사람은 누구나 호스트로 들어간다(10절 5항). 그래서 DB·로그·샘플에 남기지 않고 누를 때마다 새로 받는다. 이 레포의 라우터는 리다이렉트만 한다.
- 6: 개인 Zoom 계정 학생은 이메일·`participant_user_id`가 빈 값이라(9절) 로그인으로는 식별할 수 없다. 그래서 학생에게 표시 이름을 `학번 이름`(예: `20231234 홍길동`)으로 하도록 안내하고 학번으로 맞춘다. **한계**: ① 대리 출석을 막을 수 없다(같은 학번이 동시에 두 번 접속하면 표시만 한다). ② 이름 변경 이벤트가 없어 입장할 때의 이름만 받는다. Zoom 설정으로 참가자 이름 변경을 막을 수 있는지는 실측한다(12절). ③ 무료 계정에는 사후 조회 API(`past_meetings`, Pro)가 없어서 웹훅을 놓친 구간은 복구할 수 없다. ④ 40분 끊김 뒤 다시 열면 새 `uuid`가 생기므로 미팅 번호 단위로 합친다. 학번을 못 찾은 접속은 교수자가 직접 짝짓는 "미확인" 목록으로 돌려준다. 출석 기준(최소 체류 시간·지각 기준)은 Synsory가 정하고 함수 인자로 받는다. 실측은 교수자 노트북 + 비로그인 게스트(휴대폰·다른 브라우저)로 혼자 할 수 있다. 학생 역할 Zoom 계정은 필요 없다.
- 범위 밖(보류): 로그인·사전 등록 기반 출석 식별(학교 계정 또는 Pro), 녹화·트랜스크립트·AI 요약·과거 미팅 상세(4.2절, Pro 결제 결정 뒤에 한다).
- scope: `user:read:user`, `meeting:write:meeting`, `meeting:read:meeting`, `meeting:update:meeting`, `meeting:delete:meeting`, `meeting:read:participant`(6번 웹훅 구독) 6개. 3절 표.

## 2. 인증

OAuth 2.0 인가 코드 방식(사용자 동의). Zoom Marketplace **General App · User-managed**. 코드는 `app/core/oauth.py`의 `PROVIDERS["zoom"]`(이미 `client_auth_in_header=True`로 배관됨, 이식하지 않음). 공식 문서(2026-10-04)로 확인한 절차와 제약:

**2.1 Marketplace 설정 (2026-10-05 실제 수행)**

| 순서 | 메뉴 | 값 | 비고 |
| --- | --- | --- | --- |
| 1 | Marketplace → Develop → Build App → **General App** | 관리 유형 **User-managed** ("Individual users add and manage the app. The app has access to only the user's authorized data") | 계정 owner/admin 또는 "Zoom for developers" 역할 필요. 개인 계정은 본인이 owner. **무료 Basic 계정에서 생성 가능한지는 공식 문서에 명시 없음**(12절) |
| 2 | Basic Information → **OAuth redirect URL** | **https 필수.** 서버형(confidential) 앱은 `http://localhost`·`http://127.0.0.1` 불가 → ngrok 주소 `https://<ngrok>/auth/zoom/callback` | 공식 문서: "Do not use loopback for simple OAuth apps that are not PKCE-enabled and native apps. These must continue to use HTTPS redirect URIs." 대안은 2.4 |
| 3 | **OAuth allow list** | 리다이렉트로 허용할 URL. 게시 심사 기준은 https·FQDN·localhost 금지·"ngrok 도메인은 소유 증명 없으면 금지" | 개발 중(미게시)에는 ngrok 등록이 기술적으로 막히는지 미확인(12절). `strict_mode` 옵션 있음 |
| 4 | App Credentials | **Development**와 **Production** 자격증명 쌍이 따로 발급. 개발 중엔 Development ID·Secret을 `.env`의 `ZOOM_CLIENT_ID` / `ZOOM_CLIENT_SECRET`에 | redirect URL도 dev/prod 별도(`development_redirect_uri` 필수, `production_redirect_uri` 선택) |
| 5 | Scopes | 빌드 플로우에서 **granular scope**를 고른다(새 앱 기본). 3절 표 | 각 scope에 사용 이유를 적는 칸이 심사 자료가 된다 |
| 6 | Features → **Access** → Event Subscription → Add New Event Subscription | Method **Webhook**, Subscription name, Events(`meeting.participant_joined`·`meeting.participant_left`), Event notification endpoint URL `https://<ngrok>/zoom/webhook` → **Save**. Secret Token은 같은 Access 화면에 있다 | 유즈케이스 6만 쓴다. 9절. **2026-10-05 실측: 화면에 Validate 버튼이 없고, Save해도 URL 검증(CRC) 요청은 한 번도 오지 않았다**(공식 가이드는 "Validate를 눌러야 저장된다"고 함 → 화면이 바뀐 것으로 보임). 처음 약 40분은 이벤트도 0건이었고, ① 웹훅 URL을 Cloudflare 임시 터널로 변경 ② 앱 제거 후 재설치 ③ 구독에 `meeting.started`·`ended` 추가·저장을 거친 뒤부터 4종 모두 수신됐다. 이어서 URL만 ngrok으로 되돌려도 수신됐으므로 **ngrok 도메인은 원인이 아니었다**. 원인은 Zoom 쪽 구독이 비활성 상태였던 것이고, **앱 재설치 + 구독 재저장**으로 풀렸다(둘 중 하나만으로 되는지는 미분리). 같은 증상의 포럼 글이 2026년에 여러 건 있다. **권장 순서: 구독(URL·이벤트)을 먼저 완성하고 나서 앱을 설치(로그인)한다. 이벤트가 0건이면 앱을 제거하고 다시 설치한 뒤 구독을 한 번 더 저장한다** |
| 7 | Local Test → **Add App Now** | 본인 계정에 설치(인가) | **이 레포에서는 누르지 않는다.** 우리 `state` 없이 callback으로 와서 "state 불일치"가 난다. 대신 `/auth/zoom/login`으로 로그인한다. 다른 계정은 Beta "Request to Share" 승인 전까지 불가 |

**2.2 인가 요청·토큰 교환**

- 인가 URL `https://zoom.us/oauth/authorize?response_type=code&client_id=…&redirect_uri=…&state=…`. 공식 파라미터는 이 넷(+PKCE `code_challenge`, `code_challenge_method=S256`). **`scope` 파라미터는 공식 문서에 없다** — scope는 Marketplace 앱 설정에서 정해진다. `build_authorize_url`은 모든 provider에 `scope`를 붙이는데, **Zoom은 이를 거부하지 않고 로그인이 성공했다**(2026-10-05 실측). 부여된 scope는 앱 설정의 6개와 같았다. `scopes.py`는 그래도 유지한다(설정·심사 근거, 토큰 응답 `scope`와 대조).
- 토큰 URL `https://zoom.us/oauth/token`, `Authorization: Basic base64(client_id:client_secret)` 헤더 + 본문 `grant_type=authorization_code&code=…&redirect_uri=…`(`x-www-form-urlencoded`). Google과 달리 **자격증명을 본문이 아니라 헤더**로 보낸다(`client_auth_in_header=True`).
- 응답: `{"access_token", "token_type": "bearer", "refresh_token", "expires_in": 3600, "scope": "…", "api_url": "https://api.zoom.us"}`. `api_url`은 사용자 리전의 API 호스트다. client는 이 값을 base URL로 쓰는 쪽이 안전하다.
- 갱신: 같은 URL, `grant_type=refresh_token&refresh_token=…`, Basic 헤더. 응답에 **새 refresh token**이 들어 있고 공식 문서는 "You should always use the latest refresh token for the next refresh request"라고 한다. **실측(2026-10-05): 갱신 직후 이전 refresh token으로 다시 갱신해도 200이 났고, 이전 access token도 계속 200이었다.** 즉시 무효는 아니다(유예 시간이 얼마인지는 미확인). 그래도 공식 문구대로 항상 최신 것을 저장해 쓴다(`get_valid_token`이 그렇게 함).
- 수명: **access token 1시간, refresh token 90일.** 90일 동안 한 번도 갱신하지 않으면 교수자가 재연결해야 한다. Google(테스트 상태 7일)보다 길다.
- 폐기: `POST https://zoom.us/oauth/revoke`, Basic 헤더, `token=<access_token>` → `{"status":"success"}`.
- **토큰을 URL 쿼리에 넣으면 거부**(2023-02-14부). 공식 예시 중 일부가 아직 `?grant_type=…` 쿼리 형태로 남아 있어도 본문으로 보낸다.

**2.3 사용자 모델**

- Zoom에 연결하는 사람은 교수자 하나. 모든 호출은 `userId=me`. 학생은 Zoom 계정이 없어도 `join_url`로 입장할 수 있다(`meeting_authentication=false`일 때).
- 미공개 앱은 **개발자 계정 사용자만** 인가 가능(user-level 앱 최대 100명 설치). 다른 교수자(다른 Zoom 계정)가 연결하는 시점에 게시 심사 또는 Beta 공유가 필요하다. 7단계 메모.
- 게시 앱만 `app_deauthorized` 이벤트를 받는다("Private apps or apps in development do not trigger deauthorization notifications"). Data Compliance API는 deprecated라 더 이상 심사 요건이 아니다.

**2.4 ngrok 대안: PKCE 공개 클라이언트**

Zoom은 2026-04부터 "public client" 옵션(secret 없는 별도 client ID)과 2026-09-28부터 **PKCE 루프백 리다이렉트**(`http://127.0.0.1:8000/auth/zoom/callback`, 포트는 무시하고 매칭)를 지원한다. 이것을 쓰면 OAuth 로그인만큼은 ngrok 없이 된다. 단 ① 웹훅을 쓰면 어차피 공개 https가 필요하고(2026-10-05 현재 유즈케이스에는 웹훅이 없어 이 이유는 빠졌다) ② 서비스 레포는 서버형 confidential 클라이언트일 것이므로, 테스트 프로젝트는 **ngrok + 일반 confidential 흐름**으로 한다(2026-10-05 상현 결정: 서비스 레포와 같은 흐름을 검증하기 위해). PKCE는 참고로만 기록한다.

**2.5 `.env` 키**

`ZOOM_CLIENT_ID`, `ZOOM_CLIENT_SECRET`(Development 자격증명), `ZOOM_PUBLIC_BASE_URL`(ngrok https 주소. Zoom 리다이렉트 URI와 웹훅 URL의 base), `ZOOM_WEBHOOK_SECRET_TOKEN`(Event Subscriptions의 Secret Token. 유즈케이스 6). `redirect_uri("zoom")`은 `ZOOM_PUBLIC_BASE_URL`을 쓰고, 비어 있으면 오류를 낸다(Google은 `APP_BASE_URL` = localhost). OAuth 리다이렉트와 웹훅이 같은 ngrok 고정 도메인을 쓴다.

## 3. scope 표

Granular scope(새 General App 기본). 형식은 `<리소스>:<동작>:<대상>`이고 `:admin`은 Admin-managed 앱용, `:master`는 ISV 마스터 계정용이라 쓰지 않는다. 각 엔드포인트의 scope는 공식 OpenAPI JSON의 "Granular Scopes" 항목에서 확인했다(2026-10-04). **Zoom은 scope가 인가 URL이 아니라 앱 설정에 들어가므로, 여기 적은 사용 이유는 Marketplace의 scope 설명 칸과 심사 자료로 그대로 쓴다.**

| scope | 용도 | 필요한 유즈케이스 후보 | 플랜 |
| --- | --- | --- | --- |
| `user:read:user` | `GET /users/me` — 플랜 유형(`type`)·시간대 확인, 토큰 검증 | 공통 | Basic |
| `meeting:write:meeting` | 미팅 생성 | 예약 | Basic |
| `meeting:read:meeting` | 미팅 상세(`join_url`·`start_url` 재조회·상태) | 예약·상태 | Basic |
| `meeting:read:list_meetings` | 사용자의 미팅 목록 | 예약(동기화) | Basic |
| `meeting:update:meeting` | 미팅 수정(시각·설정·소회의실) | 예약 | Basic |
| `meeting:delete:meeting` | 미팅 삭제(취소) | 정리 | Basic |
| `meeting:update:status` | `PUT /meetings/{id}/status` — 진행 중 미팅 강제 종료(`end`) | 쓰지 않는다(강제 종료 유즈케이스 제외, 2026-10-05) | Basic("Basic license or higher") |
| `meeting:read:past_meeting` | 종료된 미팅 실제 시각·길이·참가자 수 | 종료 처리 | **유료 계정** |
| `meeting:read:list_past_participants` | 종료된 미팅 참가자 목록(출석) | 출석 | **Pro** |
| `meeting:read:participant` | 웹훅 `meeting.participant_joined/left` 구독에 필요(공식 웹훅 가이드 예시) | 출석(실시간) | Basic |
| `cloud_recording:read:list_user_recordings` | 사용자의 녹화 목록 | 녹화 | **Pro** |
| `cloud_recording:read:list_recording_files` | 미팅별 녹화 파일·`download_access_token` | 녹화 | **Pro** |
| `cloud_recording:read:recording` | 웹훅 `recording.completed` 구독에 필요(공식 웹훅 가이드) | 녹화 | **Pro** |
| `cloud_recording:read:meeting_transcript` | `GET /meetings/{id}/transcript`(AI Companion 트랜스크립트) | 트랜스크립트 | **Pro** |
| `cloud_recording:delete:meeting_recording` | 미팅 녹화 휴지통·삭제 | 정리 | **Pro** |
| `meeting:read:summary` | `GET /meetings/{uuid}/meeting_summary` + 웹훅 `meeting.summary_completed` | 요약 | **Pro** |
| `meeting:read:list_summaries` | `GET /users/me/meeting_summaries` | 요약 | **Pro** |
| `report:read:list_meeting_participants:admin` | `GET /report/meetings/{id}/participants` | 쓰지 않는다. admin 전용이라 User-managed 앱에 안 맞음. `past_meetings` 참가자로 대체 | — |

- 웹훅 이벤트별 필요 scope: 공식 가이드가 예시로 든 두 개(`participant_joined` → `meeting:read:participant`, `recording.completed` → `cloud_recording:read:recording`) 외에 `meeting.started` · `meeting.ended` · `recording.transcript_completed`의 정확한 scope는 OpenAPI JSON에 없다. 2026-10-05 Event Types 화면은 이벤트마다 "Required Meeting's Read Scopes"라고만 보여 주고 scope 이름은 표시하지 않았다. `started`·`ended`는 추가해도 새 scope가 붙지 않았다(12절).
- scope를 늘리면 기존 사용자는 재인가해야 한다(새 인가 화면). 처음부터 유즈케이스에 필요한 것을 다 넣는 편이 낫다.
- `services/zoom/scopes.py`는 1절 유즈케이스 1~6에 필요한 6개(`user:read:user`, `meeting:write:meeting`, `meeting:read:meeting`, `meeting:update:meeting`, `meeting:delete:meeting`, `meeting:read:participant`)로 시작한다(2026-10-05 확정). `meeting:read:list_meetings`는 동기화 유즈케이스가 생기면, 녹화·요약 scope는 Pro 결제가 결정되면 추가한다.

## 4. 엔드포인트 표

Base URL `https://api.zoom.us/v2`(또는 토큰 응답 `api_url`). 공식 OpenAPI JSON(`https://developers.zoom.us/api-hub/meetings/methods/endpoints.json` 등, 문서 끝 출처) 기준. "등급"은 각 엔드포인트의 Rate Limit Label(8절). **호스트 플랜으로 4.1(Basic에서 되는 것)과 4.2(Pro 이상)를 나눈다.** Basic 계정으로 4.2를 부르면 400 code 200 "Only available for paid account"(7절).

**4.1 Basic(무료)에서 되는 API**

**미팅**

| 메서드 | 경로 | 용도 | 등급 | 비고 |
| --- | --- | --- | --- | --- |
| `POST` | `/users/me/meetings` | 생성 | LIGHT | **하루 100회/사용자**(생성+수정 합산, UTC). `type` 1·2·3·8·10, `start_time` `2026-10-10T05:00:00Z`(UTC) + `timezone`, `duration` 1~1440분, `password`(기본 자동 생성, `default_password`), `schedule_for`(권한 필요), `settings{…}`, `recurrence{type 1·2·3, repeat_interval, weekly_days "1,3", end_times≤60 또는 end_date_time}`. 응답 201 |
| `GET` | `/users/me/meetings` | 목록 | MEDIUM | `type` scheduled(기본)·live·upcoming·upcoming_meetings·previous_meetings, `from`/`to`, `page_size`≤300, `next_page_token`(15분). 즉시 미팅·만료 미팅 제외, 최대 6개월 |
| `GET` | `/meetings/{id}` | 상세 | LIGHT | `status` `waiting`/`started`. `occurrence_id`, `show_previous_occurrences`. `start_url` 재발급은 이걸로 |
| `PATCH` | `/meetings/{id}` | 수정 | LIGHT | **하루 100회/사용자**(생성과 합산). `start_time`은 미래만. 반복 미팅 한 회차는 `occurrence_id`(변경 가능 필드 제한) |
| `DELETE` | `/meetings/{id}` | 삭제 | LIGHT | 204. 반복은 `occurrence_id` 없으면 **시리즈 전체** 삭제. `cancel_meeting_reminder` 기본 false |
| `PUT` | `/meetings/{id}/status` | `end` 등 상태 변경 | LIGHT | `action`: `end`(진행 중 미팅 강제 종료) · `recover`(삭제한 미팅 복구). 204. scope `meeting:update:status`. 400 3161 호스팅 권한 없음 · 404 3001 |
| `GET` | `/meetings/{id}/invitation` | 초대문 텍스트 | LIGHT | `{"invitation": "…"}` |

**생성 요청의 주요 `settings`**

| 필드 | 값 | 비고 |
| --- | --- | --- |
| `join_before_host` / `jbh_time` | bool / 0·5·10·15 | 예약·반복 미팅만. Basic 호스트면 40분 제한은 그대로 |
| `waiting_room` | bool | |
| `auto_recording` | `local` · `cloud` · `none`(기본) | `cloud`는 Pro + 클라우드 녹화 설정 |
| `breakout_room` | `{enable, rooms:[{name, participants:[email…]}]}` | 사전 배정. 이메일 매칭 |
| `alternative_hosts` | 이메일 `;` 구분 | 같은 계정의 Licensed 사용자여야 함(개인 계정에서는 사실상 불가) |
| `approval_type` | 0 자동승인 · 1 수동 · 2 등록 없음(기본) | 등록은 Basic 불가 |
| `meeting_authentication` / `authentication_domains` | bool / 도메인 | 로그인한 사용자만 입장. 학생 식별에 쓸 수 있으나 외부 계정 이메일 공백 문제는 남음(12절) |
| `mute_upon_entry`, `host_video`, `participant_video` | bool | |

**응답의 주요 필드**: `id`(int64, 미팅 번호), `uuid`, `host_id`, `topic`, `type`, `status`, `start_time`(UTC, 즉시 미팅은 없음), `duration`, `timezone`, `join_url`, `start_url`(**2시간 만료, 호스트 로그인과 동급**), `password`, `encrypted_password`, `settings`, 반복이면 `occurrences[]{occurrence_id, start_time, duration, status available/deleted}`(최대 50개).

**사용자**

| 메서드 | 경로 | 용도 | 등급 | 비고 |
| --- | --- | --- | --- | --- |
| `GET` | `/users/me` | 프로필·플랜 | LIGHT | `type` 1 Basic · 2 Licensed · 4 Unassigned, `account_id`, `pmi`, `timezone`, `personal_meeting_url`, `status` |
| `GET` | `/users/me/settings` | 설정 | MEDIUM | `recording.cloud_recording`, `recording.auto_recording`, `recording.recording_audio_transcript`, `recording.auto_delete_cmr(_days 30·60·90·120)`, `in_meeting.meeting_summary_with_ai_companion.{enable, auto_enable, who_will_receive_summary}`, `feature.meeting_capacity`. Basic에서도 읽히지만 녹화·AI 값은 Pro에서만 의미가 있다 |

Basic에서 되는 웹훅(`meeting.started` · `meeting.ended` · `meeting.participant_joined/left` · `meeting.created/updated`)은 9절.

**4.2 Pro 이상에서만 되는 API**

**종료 후 정보 · 출석**

| 메서드 | 경로 | 용도 | 등급 | 비고 |
| --- | --- | --- | --- | --- |
| `GET` | `/past_meetings/{id}` | 종료된 미팅 실측값 | LIGHT | `start_time`·`end_time`·`duration`(분)·`total_minutes`·`participants_count`·`has_meeting_summary`·`source`(만든 앱 이름). **유료 계정만**(400 code 200). 1년 이내 |
| `GET` | `/past_meetings/{id}/instances` | 반복 미팅의 종료된 인스턴스(uuid) 목록 | MEDIUM | 15개월. 종료된 것만. 플랜 전제 문구는 못 찾았고 상세와 같이 두었다(12절) |
| `GET` | `/past_meetings/{id}/participants` | 참가자(출석) | MEDIUM | **Pro 이상.** `page_size`≤300, 15개월. 1인 미팅은 계정 설정 없으면 미반환. 대규모 미팅은 처리 지연으로 `duration` 0이 올 수 있어 재시도 |
| `GET` | `/report/meetings/{id}/participants` | 참가자 리포트 | HEAVY | admin scope 전용 → 미사용 |

**등록 · 폴**

| 메서드 | 경로 | 용도 | 등급 | 비고 |
| --- | --- | --- | --- | --- |
| `GET/POST` | `/meetings/{id}/registrants`, `…/batch_registrants` | 사전 등록 | MEDIUM/LIGHT/HEAVY | Licensed 호스트 + 등록 켜진 미팅(type 2)만 |
| `GET/POST/PUT/DELETE` | `/meetings/{id}/polls…`, `GET /past_meetings/{id}/polls` | 폴 | LIGHT/MEDIUM | Pro 이상 + 포털 설정 |

**녹화 · 트랜스크립트 · 요약**

| 메서드 | 경로 | 용도 | 등급 | 비고 |
| --- | --- | --- | --- | --- |
| `GET` | `/users/me/recordings` | 녹화 목록 | MEDIUM | `from`/`to`(yyyy-mm-dd UTC, **최대 1개월**, 기본 오늘~내일), `trash`, `meeting_id`, `page_size`, `next_page_token`(15분) |
| `GET` | `/meetings/{id}/recordings` | 미팅의 녹화 파일 | LIGHT | `id` 또는 `uuid`(이중 인코딩). `include_fields=download_access_token`&`ttl=` 로 다운로드 전용 토큰. 응답 `recording_files[]{id, file_type, file_extension, recording_type, status, file_size, download_url, play_url, recording_start, recording_end}` |
| `DELETE` | `/meetings/{id}/recordings` | 미팅 녹화 전체 삭제 | LIGHT | `action=trash`(기본)·`delete`(영구). 204. 404 3301 "no recording" |
| `DELETE` | `/meetings/{id}/recordings/{recordingId}` | 파일 하나 삭제 | LIGHT | scope `cloud_recording:delete:recording_file`. 포털의 "The host can delete cloud recordings" 설정 필요 |
| `GET` | `/meetings/{id}/recordings/settings` | 녹화 공유 설정 | LIGHT | |
| `GET` | `/meetings/{id}/transcript` | AI Companion 미팅 트랜스크립트 | MEDIUM | `can_download`가 true면 `download_url`, 아니면 `download_restriction_reason`(`DELETED_OR_TRASHED`·`UNSUPPORTED`·`NO_TRANSCRIPT_DATA`). 404 3322 |
| `GET` | `/meetings/{uuid}/meeting_summary` | AI 요약 본문 | LIGHT | **uuid만.** `summary_content`(Markdown, 통합 필드), `summary_doc_url`, 레거시 `summary_overview`·`summary_details[]`·`next_steps[]`(deprecated). 400 200 유료만 · 403 2305 "Only share meeting summaries by email" 설정이면 차단 |
| `GET` | `/users/me/meeting_summaries` | 사용자 요약 목록 | MEDIUM | 본문 없음. `GET /meetings/meeting_summaries`는 admin 전용 |
| `DELETE` | `/meetings/{uuid}/meeting_summary` | 요약 삭제 | — | scope `meeting:delete:summary` |

`file_type`: `MP4` · `M4A` · `TRANSCRIPT`(VTT) · `CHAT`(TXT) · `CC`(VTT) · `CSV`(폴) · `TIMELINE`(JSON) · `SUMMARY`(JSON) · `CHAT_MESSAGE` · `TB`. `CC`·`TIMELINE`에는 `id`·`status`·`file_size`·`recording_type`·`play_url`이 없다. `recording_type`: `shared_screen_with_speaker_view` · `gallery_view` · `active_speaker` · `audio_only` · `audio_transcript` · `chat_file` · `summary` · `summary_next_steps` · `summary_smart_chapters` · `timeline` · `closed_caption` 등. 다운로드: `GET download_url` + `Authorization: Bearer <사용자 access token | download_access_token | 웹훅 download_token>`, **리다이렉트 추종**(httpx `follow_redirects=True`).

Pro 전제 웹훅(`meeting.deleted` · `recording.completed` · `recording.transcript_completed` · `meeting.summary_completed`)은 9절.

**4.3 공통**

**페이지네이션**: `page_size` 최대 300(기본 30), `next_page_token`은 **15분** 유효, 빈 문자열이면 끝. `page_number`는 폐지 중이라 쓰지 않는다.

## 5. 요청·응답 샘플

2026-10-05 실측. `samples/zoom/`. 마스킹: 토큰·`start_url`(전체 값 미기록)·참가 링크 `pwd=`·`host_id`·`host_email`·`account_id`·미팅 `uuid`·참가자 이름·학번·IP. 테스트 미팅은 실측 후 전부 삭제했다(유즈케이스 4).

| 파일 | 유즈케이스 | 내용 |
| --- | --- | --- |
| `uc1-host-profile.json` | 1 | `plan_type 1`, `has_40_minute_limit true` |
| `uc2-create-group-meetings.json` | 2-A | 그룹 2개 → POST 2회. `14:00+09:00` → `05:00Z` 변환, 대기실 설정 |
| `uc2b-create-breakout-meeting.json` | 2-B | 계정 설정을 켠 뒤 생성(그 전에는 방 목록이 버려졌다) |
| `uc3-create-recurring-meeting.json` | 3 | 월·수 4회, `occurrences[].id` |
| `uc4-reschedule.json` · `uc4-reschedule-occurrence.json` | 4 | 단일 미팅 변경 / 한 회차만 변경 |
| `uc4-cancel-occurrence.json` · `uc4-after-cancel-occurrence.json` | 4 | 한 회차 취소 → 목록에 `deleted: true`로 남음 |
| `uc4-cancel-series.json` | 4 | `occurrence_id` 없이 시리즈 전체 삭제 |
| `uc5-start.json` | 5 | 307 → `us05web.zoom.us/s/<미팅번호>` |
| `uc6-attendance.json` | 6 | 실제 웹훅 4건으로 집계(재입장 2회 합산) |
| `webhook-{started,ended,participant-joined,participant-left}.json` | 6 | 수신 본문 원형 |
| `error-meeting-not-found.json` | — | 404 `code 3001` |

## 6. 공통 모델 매핑

2026-10-05 확정(`core/models.py`). 변환은 `mapper.meeting_from_zoom`.

| Meeting 필드 | 출처 | 비고 |
| --- | --- | --- |
| `id` | `id`(int64) → `str` | 미팅 번호. 10자리 초과 가능 |
| `topic` | `topic` | |
| `status` | `status` `waiting`→`SCHEDULED`, `started`→`STARTED`, 그 밖→`UNKNOWN` | API에 `ended`가 없다. 종료는 웹훅으로만 알므로 상태 전이는 Synsory가 저장한다 |
| `start_time` | `start_time`(UTC) | 즉시 미팅은 없음 |
| `duration_minutes` | `duration` | **예정 길이**. 실제 길이는 `meeting.ended.end_time - meeting.started.start_time` |
| `timezone` | `timezone` | 표시용. 시각 자체는 UTC로 저장·전송 |
| `join_url` | `join_url` | 학생 배포용. `pwd=`가 들어 있어 링크만으로 입장 가능 |
| `host_id` | `host_id` | |
| `uuid` | `uuid` | 인스턴스 식별자. 반복 미팅·40분 끊김 뒤 재시작마다 새로 생김 |
| `occurrences[]` | `occurrences[]{occurrence_id, start_time, duration, status}` → `MeetingOccurrence{id, start_time, duration_minutes, deleted}` | 취소한 회차는 사라지지 않고 `status: deleted`로 남는다 |
| `has_recording` · `has_transcript` | (Pro) | 현재 유즈케이스에서 채우지 않음 |

**`start_url`은 모델에 넣지 않는다**(2시간 만료 + 호스트 권한). 유즈케이스 결과 묶음은 공통 모델이 아니라 `usecases.py` dataclass다: `HostProfile`(1), `GroupMeetingResult`(2-A), `AttendanceSummary{entries: AttendanceEntry[], unmatched: UnmatchedSession[]}`(6). 출석이 Meet 등 다른 서비스에도 생기면 `core/models.py`로 올린다.

## 7. 에러와 예외 케이스

공식 OpenAPI JSON·에러 가이드에서 확인한 것. 본문 형식은 `{"code": <int>, "message": "…"}`. **2026-10-05 실측**: 없는 미팅 404 `code 3001` "Meeting does not exist: 1."(`error-meeting-not-found.json`), 앱 제거 뒤 기존 토큰 401 `code 124` "Invalid access token.". 소회의실 설정이 꺼진 계정의 `breakout_room`은 **에러가 아니라 200 + 무시**다(10절 10항).

| 상황 | HTTP | code | 메시지(원문) |
| --- | --- | --- | --- |
| 토큰 만료·무효 | 401 | 124 | "Access token is expired." / "Invalid access token." |
| scope 부족·토큰 무효 | 401 | 4700 | "Invalid Access Token: The access token is invalid, expired, or missing required scopes." |
| 미팅 없음(삭제·만료 포함) | 404 | 3001 | "Meeting does not exist: {meetingId}." |
| 사용자 없음 | 404 | 1001 | "User does not exist: {userId}." |
| 유료 전용 API를 Basic으로 호출 | 400 | 200 | "Only available for paid account: {accountId}." |
| 1년 넘은 과거 미팅 | 400 | 12702 | "Cannot access a meeting a year ago." |
| 미팅 호스팅 권한 없음 | 400 | 3161 | "Your user account is not allowed meeting hosting and scheduling capabilities." |
| 타인 미팅 조회 | 403 | 2306 | "Not allowed to view meetings scheduled for others…" |
| PMI 삭제 시도 | 400 | 3018 | "Not allowed to delete PMI." |
| 즉시 미팅에 `schedule_for` | 400 | — | "Instant meetings do not support the `schedule_for` parameter…" |
| 녹화 없음 | 404 | 3301 | "There is no recording for this meeting." |
| 트랜스크립트 없음 | 404 | 3322 | "This meeting transcript does not exist." |
| 요약 접근 제한 설정 | 403 | 2305 | "Access to meeting summaries is restricted by account settings…" |
| 초당 한도 | 429 | 4001 | "You have reached the maximum per-second rate limit for this API. Try again later." |
| 일일 한도 | 429 | — | "You have reached the maximum daily rate limit for this API." |
| 하루 100회 생성·수정 초과 | 429 | — | rate-limits 가이드에 규칙만 있고 코드·메시지는 미확인(12절) |
| 웹훅 scope 미설정 이벤트 구독 | (설정 UI) | — | "The event is not allowed for the app." |

`ZoomApiError(status, code, message, is_rate_limit)`로 올리고, `is_rate_limit`(429)이면 지수 백오프. 일일 한도는 백오프로 안 풀리므로 메시지로 구분해 다음 날(UTC)로 미룬다.

## 8. 쿼터 · rate limit · 플랜 제약

공식 rate-limits 가이드(2026-10-04 확인). **계정 단위**로 적용되고, 그 계정에 설치된 **모든 앱이 공유**한다. 각 엔드포인트의 등급은 4절 표.

| 등급 | Free(Basic) | Pro | Business+ |
| --- | --- | --- | --- |
| Light | **4/초, 6,000/일** | 30/초 | 80/초 |
| Medium | **2/초, 2,000/일** | 20/초 | 60/초 |
| Heavy | **1/초, 1,000/일** | 10/초* | 40/초* |
| Resource-intensive | 10/분, 30,000/일 | 10/분* | 20/분* |

\* Pro는 Heavy+Resource-intensive 합산 30,000/일, Business+는 60,000/일.

- **미팅 생성·수정: 사용자(호스트)당 하루 100회**, 모든 미팅 ID 합산, UTC 00:00 리셋. 삭제가 포함되는지는 미확인(12절).
- 초당 한도 초과 → 429 code 4001. 일일 한도 초과 → 429 "maximum daily rate limit". 응답 헤더(`X-RateLimit-*`·`Retry-After`)는 공식 가이드에 **없다**. 실측(2026-10-05, `GET /users/me` 200)에서는 `x-ratelimit-category: Light`만 왔고 남은 횟수 헤더는 없었다 → 헤더에 의존하지 않고 429면 백오프. 429 응답의 헤더는 미확인(12절).
- 무료 계정 Light 4/초면 미팅 100개를 연속 생성해도 25초다. 쿼터보다 **하루 100회 규칙**이 먼저 걸린다.
- `next_page_token` 15분, `page_size` 300.

**플랜 제약** (support.zoom.com · zoom.us/pricing, 2026-10-04)

| 항목 | Basic(무료) | Pro | 출처 |
| --- | --- | --- | --- |
| 미팅 길이 | **40분**(참가자 1명 이상이면. 호스트 혼자면 예외) | 30시간 | KB0067966 |
| 참가자 | 100명 | 100명(Business 300) | KB0068002 |
| 클라우드 녹화 | **없음**(로컬 녹화만) | 라이선스당 **10GB**, 계정 풀링. 추가 $10/월~ | KB0067670, KB0063923 |
| 오디오 트랜스크립트(VTT) | 없음 | "Create audio transcript" 설정(Recording & Transcript → Advanced). 언어는 문서 간 상충(영어만 vs 한국어 포함 19개) | KB0065911, KB0064927 |
| AI Companion 요약 | UI에서 월 3회(가격 페이지). **API는 유료 전제** | 무제한. "Meeting Summary with AI Companion" 설정 | pricing, KB0057960 |
| 과거 미팅·참가자 API | 불가(400 code 200) | 가능 | OpenAPI 전제조건 |
| 등록·폴·대체 호스트 | 불가 | 가능 | OpenAPI 전제조건 |
| 가격 | $0 | **$16.99/사용자/월**(월납) · $14.16(연납). Business $21.99/$18.33. 한국어 페이지도 USD | zoom.us/pricing, /ko/pricing |
| 녹화 보존 | — | 자동 삭제 설정(30·60·90·120일), 휴지통 30일, 용량 초과 시 새 녹화 불가 | KB0065362, KB0066493, KB0060832 |
| Education 번들 | School and Campus는 라이선스당 5GB, 최소 20석, 온라인 구매 불가 | | KB0057711 |

**호출 수 감각** (2026-10-05 실측: 생성 5회(그룹 2 · 소회의실 2 · 정기 1) + 수정 3회 = 하루 100회 중 8회)

| 작업 | 호출 수 |
| --- | --- |
| 그룹 g개 미팅 예약 | `POST` g회 (하루 100회 한도 → g ≤ 100, 수정까지 합산) |
| 미팅 종료 처리 | 웹훅 수신 0회, 또는 `GET /past_meetings/{uuid}` 1회(Pro) |
| 출석 | 웹훅 누적 0회, 또는 `GET /past_meetings/{uuid}/participants` 1회/300명(Pro) |
| 녹화 수집 | 웹훅 1건 + 파일별 다운로드 GET(파일 수만큼, 쿼터 미적용 URL) |

## 9. 웹훅 (해당 시)

Zoom은 **웹훅이 1급 기능**이다(Google과 반대). 공식 웹훅 가이드·OpenAPI events JSON(2026-10-04).

**설정**: General App → Features → **Event Subscriptions** 켜기 → 수신 URL + 이벤트 선택. 수신 범위는 "Only for users who have added this app"(User-managed 앱에 맞음). 발급되는 **Secret Token**을 `.env`의 `ZOOM_WEBHOOK_SECRET_TOKEN`에. 구독하려는 이벤트의 scope가 앱에 있어야 한다("The event is not allowed for the app").

**수신 URL 요건**: 공개 **https**, TLS 1.2+, CA 인증서, **FQDN**, JSON POST 수신, **3초 안에 200/204**. → 로컬은 ngrok(`https://<ngrok>/zoom/webhook`). ngrok 주소가 바뀌면 Marketplace에서 URL을 바꾸고 재검증한다.

**URL 검증(CRC)**: 저장 시, 그리고 **72시간마다** Zoom이 `{"event":"endpoint.url_validation","payload":{"plainToken":"…"}}`를 POST한다. 응답은 3초 안에 200 + `{"plainToken": <그대로>, "encryptedToken": hex(HMAC_SHA256(secret_token, plainToken))}`. **6회 연속 실패하면 구독이 꺼진다**(ngrok을 내려둔 채 3일이 지나면 꺼질 수 있다. 2026-10-05에는 저장할 때도 이 요청이 오지 않았다, 2.1절 6행).

**서명 검증**(모든 이벤트): 헤더 `x-zm-request-timestamp`, `x-zm-signature`. `message = f"v0:{timestamp}:{raw_body}"`, `expected = "v0=" + hex(HMAC_SHA256(secret_token, message))`, `x-zm-signature`와 상수 시간 비교. **raw body**로 계산해야 하므로 FastAPI에서 `await request.body()`를 먼저 읽고 그 바이트로 검증한 뒤 JSON 파싱한다. 리플레이 허용 시간창은 공식 문서에 없다(12절, 5분 정도를 앱에서 정한다).

**재시도**: 5xx 또는 네트워크 오류(타임아웃·연결 거부)만 **3회**(5분 → 20분 → 60분 후). 3xx·4xx는 재시도 없음. 3회 실패하면 그 이벤트는 유실 → 수신 즉시 2xx를 돌려주고 처리는 비동기로 한다. 중복 전달 여부는 문서에 없으므로 `event_ts`·`uuid`로 멱등 처리한다.

**이벤트와 페이로드 핵심 필드** (공통 봉투 `{"event", "event_ts", "payload": {"account_id", "object": {…}}}`)

| 이벤트 | 전제 | `object` 주요 필드 |
| --- | --- | --- |
| `meeting.started` | 없음(Basic 가능) | `id`(string), `uuid`, `host_id`, `host_email`, `topic`, `type`, `start_time`, `duration`(예정), `timezone` |
| `meeting.ended` | 없음 | 위 + `end_time`. **`duration`은 예정 길이** |
| `meeting.participant_joined` | 없음. scope `meeting:read:participant` | `participant{user_id(미팅 내 임시), user_name, email(계정 밖이면 빈 문자열), join_time, participant_user_id(로그인했으면 `GET /users/{id}`의 `id`, 비로그인·**호스트 계정 밖 사용자는 빈 값**, 2026-10-05 OpenAPI 확인), participant_uuid, registrant_id, customer_key, id(deprecated)}` |
| `meeting.participant_left` | 없음 | 위 + `leave_time`, `leave_reason`("Exceeded free meeting minutes limit." 등) |
| `meeting.created` / `meeting.updated` | 없음 | 포털·클라이언트에서 만든 미팅도 옴 |
| `meeting.deleted` | **Pro** | |
| `recording.completed` | **Pro** + 클라우드 녹화. scope `cloud_recording:read:recording` | 봉투 최상위 `download_token`(**24시간**). `object{id(int64), uuid, host_id, topic, start_time, duration, share_url, total_size, recording_count, recording_files[]{id, file_type, file_extension, recording_type, status completed/processing, download_url, play_url, recording_start/end, file_size}}` |
| `recording.transcript_completed` | **Business 이상**(문서 원문. Pro 설정과 상충, 12절) | 같은 구조, `recording_type: audio_transcript` |
| `meeting.aic_transcript_completed` | AI Companion 요약 + "retain and access meeting transcripts" 설정 | `object.file_id`, `attach_type: durable_transcript` → `GET /meetings/{id}/transcript` |
| `meeting.summary_completed` | **Pro** + Meeting Summary 설정 | `meeting_uuid`, `meeting_id`, `summary_title`, `summary_content`(Markdown), `summary_doc_url`, `summary_start/end_time`, 레거시 `summary_overview`·`summary_details[]`·`next_steps[]` |
| `app_deauthorized` | **게시 앱만** | `payload{account_id, user_id, client_id, deauthorization_time, signature}` |

- 이벤트는 **앱을 인가한 사용자가 호스트인 미팅**에서만 온다(User-managed). 학생이 만든 미팅은 오지 않는다.
- 실측(2026-10-05, 무료 계정, PMI 미팅): `meeting.started`·`ended`·`participant_joined`·`left` 수신. 비로그인 게스트 참가자는 `email`·`participant_user_id`가 빈 값, `user_name`은 입력한 그대로(`20231234 홍길동` 같은 한글 포함). `participant`에는 `user_id`(미팅 내 숫자)·`participant_uuid`·`public_ip`(left에는 `private_ip`도)가 온다. **IP는 개인정보라 저장·샘플에서 뺀다.** 호스트가 미팅을 시작할 때 호스트 본인의 `participant_joined`는 오지 않았다.
- **도착 순서가 바뀔 수 있다.** 종료(13:42:10)가 다음 시작(13:43:46)보다 먼저인데 `ended`가 10초 늦게 왔다. 집계는 도착 순서가 아니라 이벤트 안의 시각으로 정렬한다. `event_ts`는 밀리초(13자리).
- `recording.completed`가 올 때 트랜스크립트가 `processing`이거나 아예 없을 수 있다. 트랜스크립트는 별도 이벤트로 기다린다.
- Verification Token은 폐지(2025-06 sunset). Secret Token + `x-zm-signature`만 쓴다.
- 라우터 설계: `POST /zoom/webhook` 하나로 받고 `event == "endpoint.url_validation"`이면 CRC 응답, 아니면 서명 검증 → 즉시 204 → 백그라운드 처리. 검증·응답 생성 함수는 `usecases.py`(순수 함수)에 두어 옮긴다.

## 10. 함정과 권장 패턴

공식 문서 기준. 실측(2026-10-05)으로 확인된 것에는 날짜를 붙였다.

1. **리다이렉트·웹훅 URL 둘 다 https FQDN.** 테스트 서버는 ngrok 하나로 `https://<ngrok>/auth/zoom/callback`과 `https://<ngrok>/zoom/webhook`을 받는다. 무료 ngrok은 재시작마다 주소가 바뀌어 Marketplace 설정과 `.env`를 같이 바꿔야 하므로 고정 도메인(ngrok 무료 static domain 1개) 사용을 3단계에서 검토한다.
2. **`localhost`는 안 되고 `127.0.0.1` 루프백은 PKCE 전용.** 서버형 앱에 루프백을 등록하지 않는다(2.4).
3. **refresh token은 받는 즉시 저장.** 갱신 응답마다 새 토큰이 오고 최신 것만 유효하다고 봐야 한다. 두 프로세스가 동시에 갱신하면 하나가 무효 토큰을 쥘 수 있으므로 서비스 레포에서는 갱신에 락을 건다. 90일 무사용이면 재연결.
4. **토큰은 헤더로만.** `Authorization: Bearer`(API), `Authorization: Basic`(토큰 엔드포인트). 쿼리스트링은 2023-02부터 거부. 녹화 `download_url`도 동일하고 리다이렉트를 따라간다.
5. **`start_url`은 비밀값.** 2시간 만료, 누구든 호스트로 입장 가능. 저장·로그·샘플에 남기지 않고 교수자가 "시작" 버튼을 누를 때 `GET /meetings/{id}`로 받아 바로 리다이렉트한다.
6. **`id`는 int64 문자열로, `uuid`는 인스턴스별.** 미팅 번호는 10자리 초과 가능. 반복 미팅은 회차마다 `uuid`가 새로 생기고 `past_meetings`·요약·녹화는 `uuid`로 특정 회차를 가리킨다. `uuid`가 `/`로 시작하거나 `//`를 포함하면 `urllib.parse.quote(quote(uuid, safe=""), safe="")`로 **이중 인코딩**. client에 헬퍼 하나.
7. **`status`에 `ended`가 없다.** 상태 머신은 Synsory가 들고, 전이는 웹훅(`started`/`ended`)으로 한다. 웹훅 유실 대비로 `GET /meetings/{id}`가 404(3001)이거나 `past_meetings`가 200이면 종료로 본다(후자는 Pro).
8. **`meeting.ended.duration`은 예정 길이.** 실제는 `end_time - start_time`. 출석 "체류 시간"은 `participant_left.leave_time - participant_joined.join_time`을 `participant_uuid`(또는 `user_id`)로 짝지어 계산하고, 재입장은 새 `user_id`가 되므로 합산한다.
9. **참가자 이메일 공백.** 호스트 계정 밖 사용자는 `email`·`user_email`이 빈 문자열("with some exceptions"). 학생이 개인 Zoom 계정이면 거의 전부 빈 값이다. 식별 후보: ① Synsory가 학생별로 다른 표시 이름을 안내(약함), ② 사전 등록(`registrant_id`, Pro + 등록 켜기, 학생이 등록 링크를 거쳐야 함), ③ `meeting_authentication` + `authentication_domains`(KAIST 도메인 계정 강제. 이메일이 채워지는지는 미확인). **2단계에서 출석 유즈케이스를 넣는다면 이 결정이 먼저다.**
10. **소회의실 사전 배정은 계정 설정이 켜져 있어야 저장된다.** 웹 설정 → 회의 → 회의 중(고급) → 소회의실 아래 **"예약 시 참가자를 소회의실에 할당"**이 꺼져 있으면 `POST /users/me/meetings`가 200을 주면서 `settings.breakout_room`을 조용히 버린다(다시 읽으면 `{"enable": false}`). 2026-10-05 실측: 개인 무료 계정 기본값은 꺼짐, 켠 뒤에는 방 목록까지 저장됨. 생성 직후 `GET /meetings/{id}`로 `breakout_room.rooms`가 있는지 확인하는 것이 안전하다. 이 설정 값은 `GET /users/me/settings`의 `in_meeting.breakout_room_schedule`(scope `user:read:settings`, MEDIUM, 현재 미신청. 2026-10-05 OpenAPI 확인)로 미리 읽을 수 있다. 소회의실 사전 배정은 이메일 매칭이기도 하다. `rooms[].participants`의 이메일로 로그인한 참가자만 자동 배정된다. ⑨와 같은 문제. 학생이 Zoom 계정 없이 들어오면 호스트가 수동 배정해야 한다.
11. **하루 100회 생성·수정.** 수업 하나의 그룹 수가 100을 넘기 어렵지만, "전체 그룹 시간 변경"을 `PATCH`로 돌리면 금방 소진된다. 반복 미팅(type 8) 하나로 여러 회차를 만들면 호출 1회다. 한도 초과 시 다음 날 UTC 00:00(KST 09:00)까지 대기.
12. **무료 계정의 일일 쿼터.** Light 6,000/일이라 평소엔 넉넉하지만 폴링 설계(예: 미팅 상태를 10초마다 `GET`)는 금방 소진된다. 상태는 웹훅으로.
13. **40분 제한은 호스트 플랜을 따른다.** 교수자가 Basic이면 학생이 Pro여도 40분. `participant_left.leave_reason`에 "Exceeded free meeting minutes limit."이 온다. Synsory가 교수자 플랜(`/users/me` `type`)을 보고 40분 넘는 예약에 경고를 띄울 수 있다.
14. **녹화·트랜스크립트·요약은 전부 Pro 이상.** 실측하려면 상현 계정을 Pro로 1개월 올려야 한다($16.99). 그 전까지 관련 유즈케이스는 보류로 두고, Basic으로 되는 예약·`/users/me`를 먼저 끝낸다.
15. **`recording.completed`와 트랜스크립트는 따로 온다.** 녹화 완료 때 `TRANSCRIPT`가 `processing`이거나 없을 수 있다. `recording.transcript_completed`(또는 AI Companion 쪽 `meeting.aic_transcript_completed`)를 별도로 구독한다. 트랜스크립트 소스가 둘(클라우드 녹화 VTT vs AI Companion 트랜스크립트)이라 어느 쪽을 쓸지는 Pro 결제 결정 때 정한다.
16. **요약 API는 `uuid`만 받고 `summary_content`(Markdown)를 쓴다.** `summary_overview`·`summary_details`·`next_steps`는 deprecated. 계정 설정 "Only share meeting summaries by email"이 켜져 있으면 403 2305.
17. **웹훅은 받자마자 2xx, 처리는 뒤에서.** 3초 제한. 4xx를 돌려주면 재시도조차 없으므로 서명 실패가 아닌 한 400을 내지 않는다. 멱등 키는 `event_ts + object.uuid(+participant_uuid)`.
18. **CRC 재검증 72시간·6회 실패 시 구독 중지.** 로컬 ngrok을 내려둔 채 3일 넘기면 구독이 꺼질 수 있다. 꺼지면 Marketplace에서 다시 켠다. 서비스 레포에서는 상시 서버라 문제 없음.
19. **scope를 나중에 늘리면 재인가.** Zoom은 scope가 앱 설정에 있어 추가 즉시 기존 사용자 토큰으론 새 API가 401/4700이 난다. 2단계에서 정한 scope를 한 번에 넣는다.
20. **SDK 없이 REST.** 쓰는 엔드포인트가 10개 안팎이고 전부 JSON이다. httpx로 충분. 예외 근거 없음. 토큰 응답의 `api_url`을 base URL로 받아 client를 만든다.
21. **취소한 회차는 목록에 남는다.** `DELETE …?occurrence_id=`는 회차를 지우지 않고 `occurrences[].status`를 `deleted`로 바꾼다. 화면에 회차를 그릴 때 `MeetingOccurrence.deleted`를 거른다(2026-10-05 실측).
22. **출석 집계는 이벤트 안의 시각으로.** 웹훅은 도착 순서가 바뀔 수 있고(9절), 퇴장 이벤트가 없을 수 있다(수업 중 서버 정지·네트워크). `summarize_attendance`는 접속(`participant_uuid`)마다 입장·퇴장을 짝짓고, 퇴장이 없으면 그 회차의 `meeting.ended`로 닫고, 같은 학생의 겹친 접속은 합쳐 센다. 대리 출석은 막지 못하고 `overlapping_sessions`로 표시만 한다.
23. **Google과 다른 점 정리.** 자격증명은 Basic 헤더 · refresh token 90일·회전 · scope는 앱 설정(인가 URL 아님) · 미공개 앱은 자기 계정만 · 웹훅이 기본이고 서명 검증 필수 · 플랜(Basic/Pro)이 API 가용성을 가른다 · 쿼터가 계정 단위 초당+일일.

## 11. 샘플 코드 (`usecases.py`의 흐름을 기준으로)

`app/services/zoom/usecases.py` 기준. `ZoomClient(access_token)`(base URL 고정 `https://api.zoom.us/v2`. 토큰 응답 `api_url`이 다르면 `base_url=`로 넘긴다), 함수는 FastAPI 없이 동작, 실패는 `ZoomApiError(status, code, message)` + `is_rate_limit`.

```python
from datetime import datetime
from zoneinfo import ZoneInfo
from app.services.zoom.client import ZoomClient
from app.services.zoom import usecases as zoom_uc

zoom = ZoomClient(access_token)
KST = ZoneInfo("Asia/Seoul")

# 1. 플랜 확인 → Basic이면 40분 경고
profile = await zoom_uc.get_host_profile(zoom)          # profile.has_40_minute_limit

# 2. 그룹마다 미팅. 실패한 그룹은 error에 담고 나머지는 계속
results = await zoom_uc.create_group_meetings(
    zoom, ["A조", "B조"], "{{activity_name}} - {{team_name}}",
    datetime(2026, 10, 12, 14, 0, tzinfo=KST), 40, "Asia/Seoul", activity_name="과제1",
    settings={"waiting_room": True},
)                                                       # results[i].meeting.join_url → 학생에게

# 3. 매주 월·수 4회
course = await zoom_uc.create_recurring_meeting(
    zoom, "정기 수업", datetime(2026, 10, 12, 16, 0, tzinfo=KST), 40, "Asia/Seoul", weekly_days=[2, 4], end_times=4,
)

# 4. 한 회차만 옮기기 / 한 회차만 취소 / 전체 취소(occurrence_id=None을 꼭 적는다)
await zoom_uc.reschedule_meeting(zoom, course.id, start_time=datetime(2026, 10, 14, 17, 0, tzinfo=KST), occurrence_id=course.occurrences[1].id)
await zoom_uc.cancel_meeting(zoom, course.id, occurrence_id=course.occurrences[2].id)
await zoom_uc.cancel_meeting(zoom, course.id, occurrence_id=None)

# 5. "시작" 버튼: 받자마자 리다이렉트, 저장 금지
start_url = await zoom_uc.get_start_url(zoom, results[0].meeting.id)

# 6. 웹훅 수신(라우터): 서명 검증 → URL 확인이면 응답, 아니면 저장 후 204
ok = zoom_uc.verify_signature(secret, headers["x-zm-request-timestamp"], raw_body, headers["x-zm-signature"])
#    수업이 끝나면 저장한 이벤트로 집계
summary = zoom_uc.summarize_attendance(
    events, roster={"20231234": "홍길동"}, meeting_id=meeting_id,
    meeting_start=datetime(2026, 10, 12, 14, 0, tzinfo=KST), min_minutes=20, late_after_minutes=10,
)                                                       # summary.entries[i].status, summary.unmatched
```

서비스 레포에서 바꿀 곳: 웹훅 이벤트 저장(`router.EVENT_LOG_PATH` 파일 → DB), 시작 링크 리다이렉트, 스케줄러(due 시각 집계)는 서비스 쪽 책임이다.

## 12. 미확인 · 보류 항목

2026-10-05 6단계 정리 기준. **지금 유즈케이스 1~6의 동작을 막는 항목은 없다.**

**유즈케이스 1~6에 관련된 것**

| 항목 | 현재 상태 · 확인 방법 |
| --- | --- |
| 서명 헤더 `x-zm-request-timestamp`의 단위(초/밀리초)와 리플레이 시간창 | 헤더를 기록하지 않아 미확인(`event_ts`는 밀리초). 서비스 레포에서 첫 수신 때 헤더를 로그로 확인한 뒤 `verify_signature`에 5분 창 검사를 추가한다. 현재는 서명만 검증 |
| URL 검증(CRC)·72시간 재검증 요청이 실제로 오는지 | 2026-10-05에는 한 번도 받지 않음(2.1절 6행). 수신 코드는 준비돼 있다. 서비스 레포에서 서버 로그에 `endpoint.url_validation`이 찍히는지 본다 |
| 처음 이벤트가 안 오던 원인(재설치 vs 구독 재저장) | ngrok 도메인은 원인이 아님을 확인. 재현되면 재저장만 먼저 해 본다. 권장 순서는 2.1절 6행 |
| 웹훅 중복 전달(at-least-once) 여부 | 공식 문서 없음. 2026-10-05 실측에서는 중복 없음. 집계는 `participant_uuid` 단위로 덮어쓰므로 중복이 와도 결과가 같다 |
| 참가자 이름 변경을 Zoom 설정으로 막을 수 있는지("Allow participants to rename themselves") | 미실측. 이름 변경 이벤트가 없어 입장 때 이름만 쓰므로, 막지 못해도 집계는 입장 시 이름 기준이다 |
| 소회의실 사전 배정(2-B)이 로그인한 학생을 실제로 자동 배정하는지 | 설정 저장까지만 실측. 학생 역할 Zoom 계정(개인 계정 1개)이 생기면 확인 |
| 하루 100회 규칙의 DELETE 포함 여부, 101번째 요청의 코드·메시지 | 일부러 넘기지 않음. 포럼은 429라고 함. 2026-10-05 실측은 생성·수정 8회 |
| 429 응답의 헤더(`Retry-After` 등) | 정상 응답에는 `x-ratelimit-category`만 있음. 429는 만나면 기록 |
| 이전 refresh token의 유예 시간 | 갱신 직후에는 이전 토큰도 동작. 항상 최신 것만 쓰므로 영향 없음 |
| "미팅 ID는 마지막 사용 30일 후 만료"(비반복 미팅) | 공식 원문 미확보. 오래 지난 미팅의 `GET /meetings/{id}`가 3001을 내는지는 시간이 지나야 확인 가능 |

**보류한 유즈케이스에 관련된 것 (Pro 결제·학생 계정 결정 뒤)**

| 항목 | 현재 상태 · 확인 방법 |
| --- | --- |
| `GET /past_meetings/{id}/instances`·`GET /meetings/{uuid}/meeting_summary`가 Basic에서 400 code 200인지 | 호출하려면 scope(`meeting:read:past_meeting`·`meeting:read:summary`)를 추가하고 재인가해야 해서 보류. 현재 앱에는 없는 scope다 |
| `recording.transcript_completed` 전제 "Business 이상" vs 트랜스크립트 설정 "Pro 이상" 상충 | Pro 결제 시 실측. 상충하면 AI Companion 트랜스크립트(`meeting.aic_transcript_completed`)로 대체 검토 |
| 트랜스크립트 언어(KB0065911 "영어만" vs KB0064927 한국어 포함 19개) | Pro 결제 시 한국어 미팅으로 실측 |
| 참가자 이메일 표시 규칙의 예외, `meeting_authentication` 시 외부 계정 이메일이 채워지는지 | 로그인 기반 출석 식별을 검토할 때. 학생 역할 Zoom 계정 필요 |
| 웹훅 `meeting.started`·`ended`·`recording.transcript_completed`의 구독 scope 이름 | `started`·`ended`는 2026-10-05 추가해 보니 새 scope 없이 구독됨. 녹화 쪽은 Pro 결정 뒤 |
| 클라우드 녹화 최대 파일 크기, 자동 삭제 설정 가능 일수의 전체 범위 | 녹화 유즈케이스 확정 시 |
| `http://127.0.0.1:8000/…`를 PKCE 없이 등록하면 UI가 거부하는지 | ngrok으로 결정해 확인하지 않음(2.4절) |

**핸드오프(7단계)에서 볼 것**

| 항목 | 메모 |
| --- | --- |
| 다른 교수자 계정 연결 | 미공개 앱은 개발자 계정 사용자만 인가 가능. Beta "Request to Share"(3~4영업일, 4주 한시) 또는 게시 심사(첫 응답 72시간 SLA, 전체 기간 "varies") |
| 서비스 레포의 웹훅 이벤트 저장 | 이 레포는 `.webhooks/zoom_events.jsonl` 파일. 서비스 레포는 DB·큐로 바꾸고 `summarize_attendance`에 이벤트 목록을 넘긴다 |

## 출처 (2026-10-04~05 확인)

- OAuth 가이드(redirect·loopback·PKCE·토큰 수명·revoke) — https://developers.zoom.us/docs/integrations/oauth/
- General App 생성·관리 유형·Dev/Prod 자격증명 — https://developers.zoom.us/docs/integrations/create/ , https://developers.zoom.us/docs/build-flow/create-oauth-apps/ , https://developers.zoom.us/docs/build-flow/basic-info/app-credentials/
- 배포 유형·심사 — https://developers.zoom.us/docs/build-flow/before-you-build/ , https://developers.zoom.us/docs/distribute/ , https://developers.zoom.us/docs/distribute/app-review-process/ , https://developers.zoom.us/docs/distribute/sharing-private-and-beta-apps/ , https://developers.zoom.us/docs/distribute/security-requirements/
- 공개 클라이언트(PKCE) — https://developers.zoom.us/blog/public-pkce/ ; PKCE 루프백 changelog(2026-09-28) — https://developers.zoom.us/changelog/
- deauthorization·Verification Token 폐지 — https://developers.zoom.us/docs/integrations/end-user-auth/ , https://developers.zoom.us/changelog/platform/webhook-url-validation/
- Data Compliance API 폐지, 쿼리스트링 토큰 거부(2023-02-14) — https://developers.zoom.us/docs/platform/announcements/
- Granular scope 목록 — https://developers.zoom.us/docs/integrations/oauth-scopes-granular/ ; classic → granular — https://developers.zoom.us/docs/integrations/migrate/
- Rate limits — https://developers.zoom.us/docs/api/rate-limits/ ; 페이지네이션 — https://developers.zoom.us/docs/api/pagination/ ; 에러 — https://developers.zoom.us/docs/api/errors/ ; 공통 사용법(`me`, 이중 인코딩, `api_url`) — https://developers.zoom.us/docs/api/using-zoom-apis/
- Meetings API 레퍼런스 — https://developers.zoom.us/docs/api/meetings/ (본문은 JS 렌더링. **공식 OpenAPI JSON**: Meetings `https://developers.zoom.us/api-hub/meetings/methods/endpoints.json`, Webhooks `https://developers.zoom.us/api-hub/meetings/events/webhooks.json`, Users `https://developers.zoom.us/api-hub/users/methods/endpoints.json`, Accounts/Dashboards `https://developers.zoom.us/api-hub/accounts/methods/endpoints.json`(2026-10-05 확인. 2026-10-04에 쓴 `/api/zoap/…` 경로는 404로 바뀜). 4·7·9절의 전제조건·에러·scope는 이 JSON의 `description` 원문)
- 웹훅 가이드(요건·CRC·서명·재시도) — https://developers.zoom.us/docs/api/webhooks/ ; 이벤트 레퍼런스 — https://developers.zoom.us/docs/api/meetings/events/
- 시간 제한 — https://support.zoom.com/hc/en/article?id=zm_kb&sysparm_article=KB0067966 ; 참가자 수 — …KB0068002 ; 클라우드 녹화 전제 — …KB0063923 ; 저장 용량 — …KB0067670 ; 용량 한도 — …KB0060832 ; 자동 삭제 — …KB0065362 ; 휴지통 — …KB0066493 ; 오디오 트랜스크립트 — …KB0065911 , …KB0064927 ; AI 요약 — …KB0057960 , …KB0058013 ; 스마트 녹화 — …KB0061101 ; Education — …KB0057711
- 가격 — https://zoom.us/en/pricing , https://zoom.us/ko/pricing
- 웹훅 미수신 사례(2026, 해결책 없음) — https://devforum.zoom.us/t/event-subscription-webhook-meeting-participant-joined-never-delivered-in-development-mode-even-after-fixing-tls-chain-still-zero-delivery-attempts/145728 , https://devforum.zoom.us/t/meeting-participant-joined-webhook-never-trigger-evenet-types-checked-scopes-verified-0-attempts-in-events-dashboard/144850 , https://devforum.zoom.us/t/webhook-events-not-received-meeting-participant-joined-meeting-participant-left/142049
- 사용자 설정 `breakout_room_schedule`·scope `user:read:settings` — Users OpenAPI JSON(위)
