# Synsory API 검증 진행 계획

작성일: 2026-09-30 · 작성자: 상현
살아있는 버전(코멘트·진행 현황 편집용): https://claude.ai/code/artifact/b956b711-3acf-44a8-8c73-385f43cd5e0e

## 전제와 목적

Synsory가 나중에 붙일 SaaS API(Google Docs · Sheets · Slides · Forms · Meet, Zoom)를 서비스 레포와 별개로 먼저 검증하고, 사용 방식을 문서로 확정하는 것이 이 작업의 목표다. 서비스 레포는 다른 개발자가 독립적으로 구축 중이므로, 여기서 나오는 산출물은 그 레포에 이식할 수 있는 형태(스펙 문서, 요청·응답 샘플, 테스트 케이스, 이식 가이드)여야 한다. 서비스 레포는 synsory-studio(TypeScript)로 확인됐다(2026-10-08). 이 레포의 Python 코드는 검증된 참조 구현이고, studio에는 TS로 다시 쓴다. 파일별 대응은 `CLAUDE.md`의 "synsory-studio 대응".

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
7. **핸드오프·검증** — 서비스별 **studio 이식 가이드**를 `docs/<service>.md` 11절 끝 "studio 이식" 하위절에 쓴다(공통 부분은 `docs/STUDIO_PORTING.md`). 담을 것: ① Python 함수 → studio 위치(`infrastructure` · `application` · `domain` · `contracts`) 대응, ② 필요한 port 인터페이스와 메서드 목록, ③ `ToolHandler` 매핑(`activity_type`, `source_key`, `identity`, `external_refs`에 넣을 값), ④ 큐 작업 정의(폴링 주기, 웹훅 → 큐 흐름), ⑤ `samples/` → studio `tests/fixtures`, pytest 케이스 → vitest 케이스 목록. 그다음 상대 개발자가 문서만 보고 studio에서 처음부터 재현해본다. 빠진 설정(API 활성화, 리다이렉트 URI 등)을 문서에 보충한다. 라우터는 이식하지 않는다. 결과: 재현 확인된 문서와 이식 가이드, 회귀 확인용 pytest.

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
| Google Forms | 3 인증 | `drive.file`로 **모든 Forms 메서드**(생성·편집·게시·응답 읽기·watch)가 동작한다(2026-10-04 공식 문서 확인). `forms.body`·`forms.responses.readonly`(민감)는 교수자가 UI에서 만든 폼을 다룰 때만 필요하므로 scope 추가 없음. 응답은 읽기만 되고 API로 응답을 제출·수정·삭제할 수 없다(REST vs Apps Script 비교 문서에 명시). 이 제약을 2단계 유즈케이스에 반영한다. |
| Google Forms | 5 테스트 | 공식 문서는 "2026-06-30 이후 API로 만든 폼은 미게시"지만 **실측(2026-10-06)으로는 `forms.create` 기본이 게시 상태**다. 항상 `unpublished=true`로 만들고 질문을 다 넣은 뒤 `setPublishSettings`로 게시한다. 폼에는 **"링크가 있는 모든 사용자" 응답자 권한(`anyoneWithLink`)이 자동으로 붙어** 학생을 응답자로 추가해도 누구나 응답할 수 있다. 학생 추가 뒤 이 권한을 지워야 제한된다. 마감은 `setPublishSettings(isAcceptingResponses=false)`. "누가 제출했나"는 `emailCollectionType=VERIFIED` + 응답자 제한으로 확보한다. 응답은 API로 넣을 수 없어 수집·집계 실측은 사람이 브라우저로 제출해야 한다. 응답 알림(Pub/Sub)은 제외, 폴링으로 한다. 파일 업로드 질문 생성, 응답 1회 제한 등 설정 대부분, 시트 연결, Drive 내보내기는 API에 없다. 세부는 `docs/google_forms.md` 7절·10절. |
| Google Meet | 1~3 탐색·인증 | 2026-10-05 추가. **개인 Gmail에서 Meet REST API가 되는지 공식 문서에 명시가 없어** 3단계 첫 `spaces.create`로 확인하고, 안 되면 Meet 전체를 보류한다. 기본 scope `meetings.space.created`가 **민감**이라 Google 4종에서 처음으로 앱 검증 대상이 생기고, 추가하면 전원 재동의한다(`drive.file`처럼 앱이 만든 공간만 보인다). 공간(`spaces`)에는 시각이 없어 시각·반복 예약은 Calendar API `events.insert`(`conferenceData`, Calendar scope 추가)이고, Calendar 호출을 둘 폴더는 2단계 결정. 녹화 MP4는 Drive 제한 scope(`drive.meet.readonly`, CASA)라 넣지 않고, 트랜스크립트는 `entries` API로 텍스트를 받는다. 세부는 `docs/google_meet.md` 2·3·10절. |
| Google Meet | 4 환경 | 무료 Gmail: **3명 이상 통화 60분**(1:1은 24시간), 녹화·트랜스크립트·Gemini 회의록·출석 보고서·공동 호스트 **전부 불가**. 녹화는 Google One 2TB+, 트랜스크립트는 Workspace 유료(Google One은 문서 상충). 상현 계정으로 실측 가능한 범위는 공간 생성·설정·종료와 회의 기록·참가자·세션 조회(개인 계정 지원 시)까지. 참가자 실측에 테스트 계정(koreaji8) 사용. |
| Google Meet | 5 테스트 | 쿼터: 읽기 사용자당 분당 600, 쓰기 100, **`spaces.create`만 사용자당 분당 10·프로젝트당 100**. 회의 기록·참가자·발화는 **종료 30일 뒤 삭제**. `meetingCode`는 365일 후 재사용될 수 있어 키는 `spaces/{id}`. 참가자는 `users/{id}`만 오고 이메일은 People API(제한적). 이벤트는 Workspace Events API → **Pub/Sub 전용**(결제 계정, 구독 7일)이라 Forms처럼 폴링(`conferenceRecords.list` + `end_time` 필터)을 기본으로 한다. 세부는 `docs/google_meet.md` 8·9·10절. |
| Zoom | 3 인증 | Marketplace에서 General App(User-managed)으로 만든다. Development/Production 자격증명이 따로 발급된다. **리다이렉트 URI는 https 필수**: `http://localhost`는 등록 불가, `http://127.0.0.1` 루프백은 PKCE 공개 클라이언트 전용이라 서버형 앱은 ngrok https 주소를 쓴다(2026-10-04 공식 문서 확인. 대안 PKCE는 `docs/zoom.md` 2.4). 자격증명은 토큰 요청의 Basic 헤더로. 액세스 토큰 1시간, **refresh token 90일**, 갱신마다 새 refresh token이 오고 "항상 최신 것을 쓰라"가 공식 문구(이전 토큰 즉시 무효화 문장은 미확인). 갱신 즉시 저장. scope는 granular가 새 앱 기본이고 **인가 URL이 아니라 앱 설정**에 들어간다(`scope` 파라미터 처리 방식은 3단계 확인). 미공개 앱은 개발자 본인 계정 사용자만 인가 가능. |
| Zoom | 4 환경 | 개인 무료(Basic) 계정: 미팅 **40분**(1:1 포함, 호스트 혼자만 예외), 100명, 클라우드 녹화·트랜스크립트·AI 요약 API·과거 미팅 상세·참가자·등록·폴 **전부 불가**(400 code 200). 되는 것은 미팅 생성·조회·수정·삭제, `/users/me`, 미팅 시작·종료·참가자 입퇴장 웹훅. Pro는 $16.99/월(월납), 30시간, 녹화 10GB/라이선스(2026-10-04 확인). 녹화·트랜스크립트·요약 시나리오가 필요하면 Pro 1개월 결제 또는 보류. 플랜 결정은 2단계. 출석·소회의실 유즈케이스를 넣으려면 학생 역할 Zoom 계정 1개도 필요. |
| Zoom | 5 테스트 | 웹훅은 Event Subscriptions에서 켜고 수신 URL은 공개 https FQDN이어야 하므로 ngrok. 저장 시와 **72시간마다** URL 검증(CRC: `plainToken` → HMAC-SHA256 `encryptedToken`, 3초 내 응답, 6회 연속 실패 시 구독 중지). 모든 이벤트는 `x-zm-signature`(`v0=` + HMAC-SHA256(secret, `v0:{ts}:{raw body}`))로 검증하고 3초 내 2xx, 처리는 비동기. 재시도는 5xx·네트워크 오류만 3회(5·20·60분). 검증·서명 함수는 `usecases.py` 순수 함수로, 라우터는 호출만. 미팅 **생성·수정은 사용자당 하루 100회**(UTC). rate limit은 계정 단위 등급(Light/Medium/Heavy/Resource-intensive, 무료는 초당 4/2/1 + 일일 6,000/2,000/1,000)이라 쓰는 엔드포인트마다 등급을 적는다(`docs/zoom.md` 4절). 토큰·`download_url`은 헤더로만, 쿼리스트링은 거부. `status`에 `ended`가 없어 종료는 웹훅으로. 참가자 이메일은 호스트 계정 밖이면 빈 문자열. |
| Zoom | 7 핸드오프 | 미공개(private) 앱은 **개발자 계정 사용자만** 인가 가능(user-level 최대 100명). 다른 Zoom 계정 사용자에게 열려면 ① Beta "Request to Share"(심사팀 응답 3~4영업일, 공유 URL 4주 한시, 소수 외부 사용자) 또는 ② 게시(public/unlisted) 심사(첫 응답 72시간 SLA, 전체 기간은 앱에 따라 다름. 약관·개인정보처리방침·지원 URL·기술 설계 문서 필요). 게시 앱만 `app_deauthorized` 이벤트를 받는다. Data Compliance API는 deprecated라 심사 요건 아님(2026-10-04 확인). |

공통 주의: 위 제약 중 플랜·쿼터·토큰 만료 수치는 기억에 의존한 값이다. 각 서비스의 1단계(API 탐색)에서 공식 문서로 확인하고 틀리면 이 표를 고친다. Google 공통·Drive·Docs 행은 2026-09-30에, Sheets·Slides·Forms·Zoom 행은 2026-10-04에, Meet 행은 2026-10-05에 공식 문서로 확인했다(출처는 각 `docs/<service>.md` 끝).

## 참고: 심사 절차

Google 앱 검증과 Zoom 앱 리뷰는 개발 중에는 필요 없다. 서비스가 우리 계정 밖 사용자의 Google/Zoom 계정을 연결하는 시점에 필요하며, 각각 수 주가 걸린다. Google은 scope 등급(비민감 / 민감 / 제한)에 따라 검증 수준이 달라지고, 제한 scope는 CASA 외부 보안 평가가 추가된다. Zoom은 General App을 우리 계정 밖 사용자에게 배포(공개든 비공개든)하려면 리뷰를 통과해야 한다. 3단계에서 scope별 사용 이유를 기록해두면 그대로 심사 제출 자료가 된다.

## 진행 현황

공통 준비(한 번만):

- [x] 상대 레포 스택 확인 — 2026-10-08. synsory-studio는 Node 24 · pnpm · TypeScript(Fastify, React, Supabase, Drizzle, pg-boss, Zod). 이 레포는 Python 유지, 7단계 산출물을 TS 이식 가이드로 바꿈(상현 결정)
- [x] `docs/STUDIO_PORTING.md` 공통 이식 가이드 초안 — 2026-10-08. 배치안·port·오류 변환·연결 흐름·도구 매핑·큐. 결정 필요 항목은 10절 (studio 담당자 확인 전)
- [x] `studio-port/` 골격 — 2026-10-09. studio `255dde3` 설정 복사(tsconfig·eslint·prettier·경계 검사·버전 고정), Node 24.21.0(nvm) + pnpm 10.34.6. `pnpm verify` 통과, 경계·strict·`any` 위반이 잡히는 것 확인. 다음: 공통 fetch 래퍼·외부 오류 분류 → Drive 어댑터 → Forms
- [ ] studio 쪽과 합의: ① 외부 도구 범위 열기(studio `TODO.md` 1절·`AGENTS.md`가 도구 등록과 추가 scope를 막고 있음, `activity_type_allowed` 허용 목록 비어 있음) ② 연결 토큰 테이블 위치(studio는 제품 테이블을 `studio` 스키마 8개로 고정, 후보는 비공개 `studio_auth`) ③ GCP 프로젝트·OAuth 동의 화면과 Zoom 앱을 studio 로그인용과 공유할지, Zoom https 리다이렉트를 studio 로컬(`localhost:5173`)에서 받는 방법
- [x] `synsory-api` FastAPI 골격 생성 (`core/`, `services/`, `samples/`, `docs/`, `.env.example`, `.gitignore`, git init) — 2026-10-02. uv + Python 3.12. `core/oauth.py`(login/callback/status/refresh/scopes), `token_store.py`, Drive·Docs client/mapper/usecases/router 배관, pytest 13개
- [x] GCP 프로젝트 + OAuth 동의 화면(테스트 상태) + 개인 계정 테스트 사용자 등록 — 2026-10-02. 웹 애플리케이션 클라이언트, Drive·Docs API 활성화
- [ ] Zoom Marketplace General App 생성 (개인 계정)
- [x] `app/core/models.py`에 Document, Meeting 초안 — 2026-10-02. Meeting 필드는 Zoom 1단계 후 확정

서비스별 현황:

| 서비스 | 현재 단계 | 상태 | 메모 |
| --- | --- | --- | --- |
| Google Drive | 6 문서화 | 1차 마감(2026-10-03), Picker 추가(2026-10-04) | `docs/google_drive.md` 전 절 작성. Sheets·Slides·Forms에서 새 Drive 호출이 생기면 추가. **Picker**(2026-10-04): 1단계 탐색, 테스트 페이지 `GET /google/picker`, 공통 함수 `create_group_files_from_template`(복사→치환→공유. Slides·Docs가 사용, Sheets는 전환 가능), 실측 완료 — Picker 전 404 → Picker 후 Slides 복사·치환·공유 성공, 토큰 refresh·서버 재시작 뒤 유지. 보류: Sheets·Docs 템플릿 Picker 후 실측, 태그 든 원본 재복사(`docs/google_drive.md` 2.1절·12절) |
| Google Docs | 6 문서화 | 완료 → 7 핸드오프 대기 | 유즈케이스 4개 실측·문서화 완료(2026-10-03). `docs/google_docs.md` 12절 전부 작성. 2026-10-04: 유즈케이스 2에 Google Doc 템플릿 경로(`template_document_id`, Picker) 추가(상현 승인). Picker 후 실측은 보류. 다음: 상대 개발자가 2절·11절만 보고 재현, 빠진 것 보충, studio 이식 가이드 작성 |
| Google Sheets | 6 문서화 | 완료(2026-10-04) → 7 핸드오프 대기 | 유즈케이스 Docs·Slides와 같은 4개 + 마감 후 값 읽기(상현 확정). 템플릿은 xlsx 1회 변환 업로드 → `files.copy` → `findReplace`(수식 안 태그 포함) 실측·채택. 실측·샘플 11개, `docs/google_sheets.md` 12절 전부 작성. 발견: 복사본 `sheetId`≠0, 보호 범위 `editors` 생략 시 학생도 편집 가능(항상 명시), 소유자 API 쓰기는 보호 무시, `RAW`/`USER_ENTERED` 학번 0 소실, csv 내보내기 첫 시트만. **성적표 동기화는 검토 후 보류**(성적 원본은 Synsory DB, 1.2~1.3절). 다음: 상대 개발자 재현, studio 이식 가이드 작성 |
| Google Slides | 6 문서화 | 완료(2026-10-04) → 7 핸드오프 대기 | 유즈케이스는 Docs와 같은 4개(상현 확정). 템플릿은 pptx 1회 변환 업로드 → 그룹마다 Drive `files.copy` → `replaceAllText`. 실측·샘플 10개, `docs/google_slides.md` 12절 전부 작성. 공유·마감·내보내기 함수는 `google_drive/usecases.py`로 옮겨 Docs와 공유(이 레포 안의 이동). Drive `files.copy` 추가. 다음: studio 이식 가이드 작성 |
| Google Forms | 6 문서화 | 완료(2026-10-06) → 7 핸드오프 대기 | 유즈케이스 13개(2026-10-06 상현 확정) 모두 구현·실측, 샘플 21개, 테스트 25개. `docs/google_forms.md` 12절 전부 작성, 12절은 유즈케이스를 막는 미확인 없음. 문서와 다른 실측: 생성 기본값은 게시 상태(항상 미게시로 만들고 게시), 응답 권한 `anyoneWithLink` 자동 부여(제한 시 삭제), 퀴즈의 틀린 답과 비채점 문항 grade가 똑같이 `{}`(배점으로 구분). 퀴즈 점수는 기본이 제출 직후 공개. Picker로 고른 UI 폼도 템플릿 복사 가능. 실측 파일은 휴지통으로 정리. 다음: studio 이식 가이드 작성 |
| Google Calendar | 1 API 탐색 | 완료(2026-10-06) · 보류 | Meet 예약 수단으로 조사. `docs/google_calendar.md` 작성. Meet 링크는 `events.insert` + `conferenceData.createRequest`로 만들고 초대 메일·반복은 Calendar가 처리. 최소 scope는 `calendar.app.created`(보조 캘린더). Calendar가 만든 Meet은 Meet API에서 "다른 앱 공간"이라 출석에 `meetings.space.readonly`가 필요하고, 2026-02부터 Meet 코드 재사용 금지 권고. **2026-10-06 상현: Meet 단독으로 쓰기로 해 보류**(학생 캘린더 불필요) |
| Google Meet | 2 유즈케이스 | 초안(2026-10-06) → 상현 확인 대기 | 1단계 완료(2026-10-05, `docs/google_meet.md`). 2026-10-06 상현 방향: **Meet 단독(Calendar 없음), 출석 포함**. 초안 4개: 그룹별 링크 생성, 명단으로 잠금(`RESTRICTED` + `spaces.members`), 회의 후 출석 집계(`conferenceRecords` → `participants` → `participantSessions`, 식별은 멤버 대응표 A / 표시 이름 학번 B), 링크 회수. 강제 종료·상태 추적은 Zoom과 맞춰 보류. 전제 확인(3단계 첫 작업): 개인 Gmail에서 Meet API 동작, 무료 회의에서 참가자 API가 채워지는지 |
| Zoom | 6 문서화 | 완료(2026-10-05) → 7 핸드오프 대기 | 상현 확정: **무료(Basic) 계정으로 실측 가능한 6개** — 플랜 확인, 그룹별 미팅 예약(A 그룹마다 미팅 / B 소회의실 비교용), 정기(매주 반복) 회의, 일정 변경·취소, 호스트 시작 링크, 출석 자동 집계(참가자 웹훅 + 표시 이름 학번 매칭)(`docs/zoom.md` 1절). 제외: 마감 시 강제 종료, 시작·종료 웹훅 상태 추적. 보류: 로그인·사전 등록 기반 출석 식별, 녹화·트랜스크립트·요약(Pro). scope 6개. 3단계 진행 중(2026-10-05): ngrok 고정 도메인(학교망 차단 → 우회 후 online), General App 생성(무료 계정 가능, ngrok 리다이렉트 등록 가능), 웹훅 수신 코드(`POST /zoom/webhook`) 구현, **로그인·`GET /users/me`(type 1)·refresh 실측 성공**. **웹훅 4종 수신 성공**(무료 계정, 게스트 표시 이름 그대로·이메일 빈 값 확인). 처음 40분 0건이었다가 앱 재설치 + 구독 재저장 뒤 수신. ngrok 주소로 되돌려도 수신돼 도메인은 원인이 아님(`docs/zoom.md` 2.1절). OAuth·웹훅 모두 ngrok 고정 도메인 하나로 받는다. **5단계(2026-10-05)**: 유즈케이스 1~6 구현·실측, 샘플 16개, 테스트 66개. 발견: 소회의실 사전 배정은 계정 설정 "예약 시 참가자를 소회의실에 할당"이 꺼져 있으면 200인데 조용히 버려짐(켠 뒤 저장 확인), 취소한 회차는 `deleted`로 남음. **6단계(2026-10-05)**: `docs/zoom.md` 12절 전부 정리(1~6 동작을 막는 미확인 없음). 다음: 상대 개발자가 2절·11절만 보고 재현, studio 이식 가이드 작성. 다음: 3단계 Marketplace General App 생성, 리다이렉트는 ngrok + client secret 방식으로 결정(2026-10-05, PKCE 미사용) |

## 열린 질문

- Zoom 녹화·트랜스크립트·AI 요약 시나리오 필요 시 Pro 플랜 1개월 결제 여부($16.99). Basic으로는 예약·웹훅만 실측 가능 — 2026-10-05 보류(무료 계정 유즈케이스부터)
- Zoom 출석 유즈케이스의 학생 식별 방식 — 2026-10-05 표시 이름 학번 매칭으로 결정(`docs/zoom.md` 1절 6번). 로그인·사전 등록 방식은 학교 계정·Pro 확인 뒤
- Google Meet을 Zoom과 함께 붙이는지 하나만 붙이는지(Meet 단독 사용은 가능하게 설계, 2026-10-06) — 무료 호스트 제한(Meet 3명 이상 60분 vs Zoom 40분), 예약 방식, 이벤트 방식 비교는 `docs/google_meet.md` 1단계 요약
