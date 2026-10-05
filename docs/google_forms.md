# Google Forms 연동 스펙

상태: 2단계(유즈케이스 확정) 완료 · 3단계(인증, Docs 결과 재사용) 대기
최종 수정: 2026-10-06 · 작성: 상현
확인 기준: 공식 문서 2026-10-04. 실측 없음(3단계는 Docs 결과 재사용, 4~5단계에서 실측)

옮기는 파일(예정): `app/services/google_forms/{client,mapper,scopes,usecases}.py`와 이 문서. Drive 호출(폴더 지정, 메타데이터, 공유·응답자 권한, 삭제, 복사)은 `app/services/google_drive/`와 `docs/google_drive.md`에 두고 이 문서는 Forms API(`forms.googleapis.com/v1`)만 다룬다.

---

## 1단계 요약: 할 수 있는 일 · 못 하는 일 · 눈에 띄는 제약

2단계에서 유즈케이스를 고를 때 보는 한 장이다. 아래 3~12절은 이 요약의 근거다.

**리소스.** 폼(`formId`, Drive 파일 ID와 같음) 하나 안에 항목(`items[]`, 질문·섹션 구분·텍스트·이미지·동영상)이 순서대로 들어 있다. 질문에는 `questionId`가 있고, 응답(`responses[]`)은 `questionId`를 키로 답을 담는다. 위치는 0부터 시작하는 항목 인덱스로 지정한다(Docs의 문자 인덱스, Sheets의 A1과 다름). 폼은 **편집 화면**(`webViewLink`)과 **응답 화면**(`responderUri`, `…/viewform`)이 따로 있다.

**할 수 있는 일**

| 분류 | 내용 | 메서드 |
| --- | --- | --- |
| 생성 | 제목만으로 빈 폼 생성. 폴더 지정 불가 → Drive로 | `forms.create` |
| 설문 구성 | 질문 추가·수정·삭제·이동, 섹션(페이지) 나누기, 설명 텍스트·이미지·YouTube 동영상 넣기, 제목·설명 변경 | `forms.batchUpdate` (`createItem`, `updateItem`, `deleteItem`, `moveItem`, `updateFormInfo`) |
| 질문 종류 | 객관식(단일·복수·드롭다운), 단답·장문, 선형 배율, 별점, 날짜, 시간, 격자(행렬) | `createItem`의 `questionItem` / `questionGroupItem` |
| 분기 | 객관식 선택지별로 "다음 섹션 / 특정 섹션으로 / 제출"로 이동 | `Option.goToAction` / `goToSectionId` |
| 퀴즈 | 퀴즈 모드 켜기, 정답·배점·정답/오답 피드백 설정, 자동 채점 | `updateSettings`(`quizSettings.isQuiz`) + `Question.grading` |
| 이메일 수집 | 수집 안 함 / 로그인 계정 자동 수집(검증됨) / 응답자가 입력 | `updateSettings`(`emailCollectionType`) |
| 게시·마감 | 게시 / 게시 취소, **응답 받기 중단**(게시 유지) | `forms.setPublishSettings` |
| 응답자 제한 | 특정 이메일만 응답 가능하게, 또는 "링크가 있는 모든 사용자" | Drive `permissions.create` (`view=published, role=reader`) |
| 응답 읽기 | 전체 목록(5,000개 단위 페이지), 시각 이후 필터, 응답 1건 조회. 퀴즈면 점수까지 | `forms.responses.list` / `get` |
| 응답 알림 | 새 응답·수정 응답, 폼 구조 변경을 Cloud Pub/Sub으로 푸시 | `forms.watches.create` / `renew` / `list` / `delete` |
| 읽기 | 폼 구조·설정·질문 ID·게시 상태·연결된 시트 ID | `forms.get` |
| 조회·관리 | 파일 메타데이터(소유자·수정 시각·URL), 폴더 이동, 공동 편집자 공유, 휴지통, 복사 | Drive API (`docs/google_drive.md`) |

**못 하는 일 · 다른 API로 해야 하는 일**

- **응답을 API로 제출·수정·삭제할 수 없다.** 응답은 응답자가 웹 폼에서 내는 것만 들어온다. Synsory가 대신 제출하거나 지우는 시나리오는 불가.
- **파일 업로드 질문을 API로 만들 수 없다**(레퍼런스 명시). 읽기는 된다(응답에 Drive `fileId`).
- **폼 설정 중 API에 있는 것은 퀴즈 여부와 이메일 수집 방식뿐이다.** "응답 1회로 제한", "제출 후 수정 허용", "확인 메시지", "질문 순서 섞기", "진행률 표시", "응답 사본 보내기"는 API에 없어 교수자가 UI에서 바꿔야 한다.
- **응답을 시트에 연결하는 것은 UI에서만 된다.** `linkedSheetId`는 읽기 전용. 응답 CSV·xlsx가 필요하면 `responses.list`로 받아 Synsory가 만든다.
- **폼은 Drive `files.export`가 안 된다**(내보내기 형식 표에 Forms 없음). PDF 보관 불가.
- **수동 채점·점수 공개는 API에 없다.** 자동 채점(객관식·단답 정답 일치)만. 점수는 응답의 `totalScore`로 읽는다.
- 폴더 지정 생성, 공유, 삭제, 복사는 Forms API에 없다. 전부 Drive API.
- 푸시 알림에는 **응답 내용이 들어 있지 않다.** 알림을 받으면 `responses.list`로 다시 조회한다.

**눈에 띄는 제약**

| 항목 | 값 | 비고 |
| --- | --- | --- |
| **게시 기본값** | **2026-06-30 이후 API로 만든 폼은 미게시 상태**로 생성 | 지금(2026-10)은 이 규칙 적용 중. 만들고 `setPublishSettings`로 게시해야 응답을 받는다. 빠뜨리면 응답 링크가 열리지 않는다 |
| scope | `drive.file`로 **모든 Forms 메서드**(응답 읽기·watch 포함) 호출 가능 | `forms.body`·`forms.responses.readonly`는 민감 등급. 앱이 만든 폼만 다루면 불필요. PLAN.md의 "scope가 본문·응답으로 나뉜다"는 사용자 전체 폼을 다룰 때 얘기다 |
| 읽기 쿼터 | 프로젝트당 분당 975 · 사용자당 분당 390 | Docs 읽기(300/사용자)보다 높다 |
| **응답 목록 쿼터** | `responses.list`는 별도 "expensive read": 프로젝트당 분당 450 · **사용자당 분당 180** | 폴링 주기 설계의 기준 |
| 쓰기 쿼터 | 프로젝트당 분당 375 · 사용자당 분당 150 | `batchUpdate` 1회 = 1회(안의 요청 수 무관) |
| 응답 페이지 | `pageSize` 기본·최대 5,000 | 한 폼의 응답이 수강생 수 수준이면 1페이지 |
| 알림(watch) | 수명 **7일**, `renew`로 연장. watch당 **30초에 1회**로 묶어서 옴. 프로젝트·폼·이벤트당 20개(사용자당 1개), 폼당 50개 | Cloud **Pub/Sub 토픽 + 결제 계정 연결**이 전제. 폴링이 먼저 |
| `revisionId` | 반환 후 24시간만 유효 | `writeControl.requiredRevisionId`(Docs와 같은 낙관적 잠금 있음) |
| 요금 | 무료. "쿼터 초과분 2026년 중 과금 계획" 문구 있음 | Docs·Drive·Sheets와 같은 문구 |
| 응답자 이메일 | `respondentEmail`은 `emailCollectionType`이 수집으로 설정된 폼에만 들어온다 | "누가 제출했나"가 필요하면 생성 시 `VERIFIED`(로그인 필요) 설정 |
| 선택지 답은 문자열 | 객관식 답은 선택지 **텍스트**로 온다(ID 아님) | 선택지 문구를 바꾸면 기존 응답과 매칭이 어긋난다. 10절 |

**유즈케이스**: 2026-10-06 확정, 13개. 1절에 있다. 검토 후 제외한 아이디어도 1절 끝에 남겼다.

---

## 1. 이 서비스로 하는 일 (유즈케이스)

2026-10-06 상현 확정. 1단계 API만으로 가능한 아이디어 17개를 교수자 입장에서 뽑은 뒤 12개를 남겼다. 같은 날 "시트로 내보내기" 13번을 추가했다. 전제는 Docs·Sheets·Slides와 같다. OAuth로 연결하는 사람은 **교수자**이고, 폼은 교수자 Drive에 교수자 소유로 만들어진다. 다른 점은 학생 권한이다. 학생은 편집자가 아니라 **응답자**(Drive 권한 `view=published`)이고 `responderUri` 링크로 응답한다. 응답은 API로 제출·수정·삭제할 수 없고 읽기만 된다.

**응답은 기본적으로 폼에서 직접 가져온다.** Forms는 응답을 폼 자체에 저장하고, Sheets 연결은 교수자가 UI에서 직접 켜야 하는 선택 기능이다(공식 도움말 확인 2026-10-06, 10절 11항). 성적과 결과의 원본은 Synsory DB다(`docs/google_sheets.md` 1.2절 결정, 2026-10-04). 그래서 9~12번은 응답을 Synsory로 가져오는 데까지가 Forms의 일이다. 13번은 교수자가 Sheets에서 응답을 보고 싶을 때 쓰는 **한 방향 사본**이다. 시트를 원본으로 두거나 동기화하지 않는다.

| # | 유즈케이스 | 호출 순서 | usecases 함수 (예정) |
| --- | --- | --- | --- |
| 1 | Synsory 템플릿(질문 목록)으로 액티비티 설문을 만들어 게시하고 응답 링크를 학생에게 준다 | Forms `create` (`info.title`, `documentTitle`) → `batchUpdate` 1회 (`updateFormInfo` 설명 + `updateSettings` 이메일 수집 + `createItem` × 질문 수) → `setPublishSettings` (`isPublished=true`, `isAcceptingResponses=true`) → Drive `files.update` (`addParents`=액티비티 폴더) → `forms.get` (`responderUri`) + Drive `files.get` | `create_form` |
| 2 | 정답·배점을 넣은 퀴즈를 만든다 | 1과 같고, `batchUpdate` 맨 앞에 `updateSettings` (`quizSettings.isQuiz=true`), 문항마다 `grading` (`pointValue`, `correctAnswers`, 피드백) | `create_form(quiz=True)` |
| 3 | 조마다 동료평가 폼을 만들고 그 조원만 응답하게 한다 | 그룹마다: 1의 흐름 (평가 항목마다 격자 질문 `questionGroupItem`, 행=조원 이름, 열=척도) → 조원마다 Drive `permissions.create` (`type=user, role=reader, view=published`) | `create_group_forms` |
| 4 | 교수자가 예전에 만든 폼을 Picker로 고르면 이번 액티비티용으로 복사한다 | 교수자 브라우저에서 Picker → Drive `files.copy` (`name`, `parents`) → `forms.get` (복사본의 질문 ID) → `batchUpdate` (`updateFormInfo` 제목 등) → `setPublishSettings` | `create_form_from_template` |
| 5 | 응답자를 수강생으로 제한하고 로그인 이메일을 수집해 누가 냈는지 안다 | 1의 `batchUpdate`에 `updateSettings` (`emailCollectionType=VERIFIED`) → 학생마다 Drive `permissions.create` (`view=published`). 해제: `permissions.list` (`includePermissionsForView=published`) → `permissions.delete` | `restrict_responders` / `remove_responders` |
| 6 | 제출 현황을 명단과 비교해 미제출자를 알려 준다 | `responses.list` (`fields`로 `responseId`·`respondentEmail`·`lastSubmittedTime`만) → Synsory 명단과 대조 → 제출·미제출 목록 반환 | `get_submission_status` |
| 7 | 마감(due) 시각에 응답 받기를 멈추고, 연장하면 다시 연다 | `setPublishSettings` (`isPublished=true`, `isAcceptingResponses=false`). 재개는 `true`로 같은 호출. Synsory 스케줄러가 due 시각에 호출 | `close_form` / `reopen_form` |
| 8 | 수업 중 미니 퀴즈·설문을 정해진 시각에 열고 닫는다 | 미리 1·2로 만들어 두되 게시하지 않음 → 시작 시각: `setPublishSettings` (게시 + 응답 받기) → 종료 시각: 7과 같은 호출 | `create_form(publish=False)` → `open_form` → `close_form` |
| 9 | 응답을 Synsory로 가져와 문항별 분포·평균을 보여 준다 | (저장해 둔 질문 ID 매핑, 없으면 `forms.get`) → `responses.list` (`filter=timestamp >= 마지막 조회`, `pageToken`) → mapper가 응답 목록과 문항별 집계로 변환 | `collect_responses` / `summarize_responses` |
| 10 | 퀴즈 자동 채점 점수를 가져와 Synsory 성적에 반영한다 | `responses.list` (필터 없이 전체) → 응답마다 `totalScore`, 문항별 `grade{score, correct}` → 학생 이메일별 점수 반환 | `collect_quiz_scores` |
| 11 | 동료평가 응답을 학생별 평균 점수로 집계한다 | 3의 폼마다 `responses.list` → 격자 행 질문 ID를 조원으로 매핑 → 평가자·피평가자·항목별 점수 → 학생별 평균 반환 | `summarize_peer_reviews` |
| 12 | 응답 결과를 CSV·xlsx 파일로 받는다 | `responses.list` → Synsory 서버가 파일 생성. 9와 같은 Google 호출이고 그 외 호출은 없다 | `export_responses` |
| 13 | 응답을 교수자 Drive의 스프레드시트로 내보낸다 | (저장해 둔 질문 ID 매핑, 없으면 `forms.get`) → `responses.list` → 처음: Sheets `create` (시트 이름 "응답") + Drive `files.update` (`addParents`=액티비티 폴더) → `values.update` 1회 (`RAW`, 헤더 + 전체 행). 다시 내보내기: 같은 스프레드시트에 `values.clear` → `values.update` | `export_responses_to_sheet` (Sheets의 `create_empty_spreadsheet`·`write_values` 재사용) |

**유즈케이스별 메모**

- 1: 지금은 API로 만든 폼이 **미게시 상태로 생성**된다(2026-06-30부터). 게시를 빠뜨리면 학생 링크가 열리지 않으므로 생성 함수가 게시까지 한다. 질문을 다 넣은 뒤 게시해야 학생이 미완성 폼을 보지 않는다(10절 1항). `create`는 제목 외 필드를 받지 않아 질문은 반드시 `batchUpdate`로 넣는다(10절 2항).
- 1: 템플릿은 **Synsory가 보관하는 `createItem` 배열(JSON)**로 가정한다. Docs의 Markdown, Slides의 pptx, Sheets의 xlsx에 대응한다. Forms에는 `replaceAllText` 같은 치환 요청이 없으므로 Synsory가 JSON 안의 `{{team_name}}`, `{{activity_name}}`, `{{due}}`를 먼저 치환하고 보낸다.
- 1: `batchUpdate` 응답의 `replies[].createItem.questionId`를 **반드시 저장**한다. 9~12가 응답을 해석할 때 이 매핑을 쓴다(10절 6항).
- 1: Drive `files.create` (`mimeType=application/vnd.google-apps.form`, `parents`)로 폴더 안에 바로 만들 수 있으면 `files.update` 1회를 줄인다. 공식 문서에 명시가 없어 실측한다(12절).
- 2: 1과 따로 두는 이유(2026-10-06 상현 결정): 채점만 보면 Synsory가 템플릿의 정답과 비교해도 같은 결과가 나온다. 하지만 **제출 직후 학생이 폼 안에서 점수·정답 여부·피드백을 보는 것**은 퀴즈 모드로만 된다. Synsory는 제출 순간을 알 수 없고(실시간 알림 제외) 제출 뒤 폼 화면에 무언가를 띄울 API도 없다. 교수자가 Forms 화면에서 서술형을 손으로 채점하거나 점수를 고치면 그 값이 응답 총점에 반영되는 것도 퀴즈 모드에서만 된다. 점수 공개 시점(제출 직후 / 검토 후)은 UI 설정뿐이라 기본값을 실측한다(12절).
- 2: 퀴즈 설정을 질문보다 **같은 배치 안에서 앞에** 둔다. 자동 채점은 객관식과 단답(정답 문자열 완전 일치)만 된다. 수동 채점과 점수 공개는 교수자가 UI에서 한다(10절 9항).
- 3: 기본 방식(A)은 조마다 폼 하나다. Docs 유즈케이스 2와 같은 "그룹마다 파일" 구조라 공유 코드를 재사용한다. 다만 공유 역할은 `writer`가 아니라 `reader` + `view=published`다. 자기 평가를 뺄지는 질문 구성의 문제라 Synsory 템플릿에서 정한다.
- 3: **비교용 방식(B)**: 폼 하나에 "내 조" 객관식을 두고 선택지마다 그 조 섹션으로 이동시킨다(`goToSectionId`, 조마다 `pageBreakItem`). 폼이 하나라 폴링·마감이 1회로 끝난다. 대신 다른 조를 골라 들어가는 것을 막을 수 없다. 이메일 수집(5)을 켜고 Synsory가 "응답자 조 ≠ 선택한 조"인 응답을 버리는 것으로 보완한다. 5단계에서 A를 기본으로 구현하고 B를 비교한다.
- 4: Picker로 고른 **원본은 수정하지 않고 복사본만 바꾼다**(Docs·Slides와 같은 원칙, 2026-10-04 결정). Forms에는 치환 요청이 없어 복사본에서 바꿀 수 있는 것은 제목·설명·질문 단위 수정뿐이다. 실측 전제 3가지가 미확인이다. ① Picker에서 폼이 보이고 골라지는지. ② `files.copy`로 폼이 복사되는지. ③ 복사본의 게시 상태와 응답이 따라오는지. 하나라도 안 되면 4는 보류한다(12절).
- 5: 학생 이메일은 Google 계정이어야 한다(Docs 유즈케이스 2와 같은 제약). 응답자를 제한하면 학생도 Google 로그인을 해야 하므로 `VERIFIED` 이메일 수집과 함께 쓴다. 개인 계정 폼에서 `VERIFIED`가 동작하는지는 12절 실측. 6·10·11은 이 이메일로 학생을 식별하므로 **5가 전제**다.
- 6: 독촉 알림은 Synsory가 보낸다. Google은 응답자에게 메일을 보내지 않는다. `responses.list`는 별도 쿼터(사용자당 분당 180)라 응답을 받는 중인 폼만 분 단위로 폴링한다(8절, 10절 8항).
- 7: Docs의 권한 낮추기에 해당하는 Forms의 마감이다. 학생이 링크를 열면 "더 이상 응답을 받지 않습니다"가 뜨고 교수자는 결과를 계속 본다. 연장은 **폼 단위**라 학생 개인별 연장은 안 된다. 스케줄러는 Docs 10절 11항과 같이 Synsory 서비스 책임이다. 마감 처리 시각에 교수자 refresh token이 살아 있어야 한다는 점도 같다.
- 8: 7의 함수를 수업 시간에 맞춰 짧게 쓰는 경우다. 매주 반복 설문(1분 설문 등)도 이 조합이라 따로 두지 않는다. 주차마다 새 폼을 만들지 하나를 계속 쓸지는 템플릿 운영 문제다.
- 9: 응답은 `core/models.py`의 새 공통 모델로 바꾼다(6절, 예: `FormSubmission`). 객관식 답은 선택지 **문구**로 오므로 생성 후 문구를 바꾸면 예전 응답과 어긋난다(10절 6항). 증분 조회는 `>=` 경계 중복이 있어 `responseId`로 멱등 처리한다.
- 10: `lastSubmittedTime`은 채점 변경을 반영하지 않는다(레퍼런스 명시). 교수자가 UI에서 점수를 고친 뒤에는 증분 필터로 잡히지 않으므로 **점수 수집은 필터 없이 전체를 다시 읽는다.** 응답 수가 5,000개 이하면 호출 1회다.
- 11: 격자 질문은 행마다 질문 ID가 따로 있다(10절 7항). 1에서 저장한 "행 질문 ID → 조원" 매핑으로 피평가자를 찾는다.
- 12: Sheets 1.2절 결정에 따라 Sheets를 거치지 않고 Synsory 서버가 만든다. 폼은 Drive 내보내기가 안 된다(10절 11항).
- 13: UI의 "Sheets에 연결"을 대신하는 기능이다. 차이는 세 가지다. ① UI 연결 시트는 새 응답이 자동으로 쌓이지만, 13은 **호출한 시점의 사본**이다. 마감(7) 직후 한 번 내보내는 것을 기본으로 하고, 진행 중 갱신이 필요하면 Synsory가 다시 내보낸다. ② 앱이 만든 시트라 `drive.file`로 계속 다룰 수 있다. UI에서 연결한 시트는 Forms가 만든 파일이라 앱이 못 읽을 것으로 본다(12절). ③ 열 구성을 Synsory가 정한다.
- 13: 열은 제출 시각, 이메일(5를 켠 경우), 점수(퀴즈인 경우), 질문별 한 열이다. 헤더는 질문 제목이다. 체크박스 답은 ", "로 이어 한 칸에 넣고, 격자 질문은 "질문 [행]"처럼 행마다 한 열로 편다. 값은 `RAW`로 쓴다. 그래야 학번처럼 앞자리가 0인 답이 숫자로 바뀌지 않는다(`docs/google_sheets.md` 10절 3항).
- 13: 다시 내보낼 때는 같은 스프레드시트를 덮어쓴다. 그래서 서비스는 처음 만든 스프레드시트 ID를 폼 ID와 함께 저장한다. 교수자가 시트에 메모 열을 덧붙였다면 덮어쓰기에서 지워질 수 있다. 그래서 `values.clear`는 Synsory가 쓴 범위(헤더 열 수까지)만 지운다. 응답이 많아도 쓰기는 1회라 Sheets 쓰기 쿼터(사용자당 분당 60)에 걸리지 않는다.
- 13: 시트는 교수자 소유이고 학생에게 공유하지 않는다. 학생 이메일과 답이 들어 있기 때문이다. 조교 공유가 필요하면 Drive 공유 함수로 따로 한다.
- scope: 열세 유즈케이스 모두 `drive.file` 하나. `services/google_forms/scopes.py`는 빈 dict다. 4의 Picker도 scope를 늘리지 않는다(`docs/google_drive.md` 2.1절).

**검토 후 제외 (2026-10-06 상현)**

| 아이디어 | 제외 이유 |
| --- | --- |
| 매주 수업 후 반복 설문 자동 생성 | 폼 형식 문제이고 자동화 자체는 8로 이미 된다 |
| 장문 응답을 Docs 문서 한 장으로 정리 | 이번 범위에서 제외 |
| 사전 설문으로 조 편성 후 Docs·Slides 문서와 Zoom 미팅 생성 | 이번 범위에서 제외 |
| Slides 발표 마감 뒤 조별 평가 폼 열기 + 결과 시트 기록 | 이번 범위에서 제외 |
| 제출 즉시 반응 (Pub/Sub 푸시 알림) | 이번 범위에서 제외. 결제 계정 연결이 필요하고 폴링으로 대신한다(9절) |

**API가 막아서 처음부터 후보에 넣지 않은 것**: Synsory 화면에서 응답 제출, 과제 파일 제출 폼(파일 업로드 질문 생성 불가), 응답 1회 제한·제출 후 수정·확인 메시지(UI 전용), 학생 개인별 마감 연장, 수동 채점·점수 공개, 잘못된 응답 삭제, 응답 시트 자동 연결, 폼 PDF 보관. 근거는 1단계 요약 "못 하는 일".

## 2. 인증

Google 4종이 공유하는 OAuth 흐름이다. 콘솔 설정·인가·갱신 절차는 `docs/google_docs.md` 2절, 공통 제약은 `docs/google_drive.md` 2절. Forms에서 추가로 할 일:

- GCP 콘솔 "API 및 서비스 → 라이브러리"에서 **Google Forms API**를 사용 설정한다. 빠뜨리면 호출마다 403 "API has not been used in project…".
- 앱이 만든 폼만 다루는 동안은 scope 추가가 없으므로 **재동의가 필요 없다**. `forms.body`·`forms.responses.readonly`를 추가하게 되면 사용자가 재동의해야 한다.
- 푸시 알림(9절)을 쓰면 **Cloud Pub/Sub API 사용 설정과 결제 계정 연결**이 추가로 필요하다. 이것은 OAuth 동의와 무관한 우리 프로젝트 쪽 설정이다.
- 사용자 모델: OAuth 연결은 교수자. 학생은 Google 계정을 연결하지 않고 응답 링크로 응답한다. 응답자 제한·이메일 수집을 켜면 학생도 Google 로그인은 해야 한다(앱 연결은 아님).

## 3. scope 표

공식 레퍼런스(2026-10-04 확인) 기준. `forms.create` · `get` · `batchUpdate` · `setPublishSettings` · `responses.get` · `responses.list` · `watches.*` 모두 `drive.file`을 허용 scope로 나열한다.

| scope | 등급 | 가능한 범위 | 판단 |
| --- | --- | --- | --- |
| `drive.file` | 비민감 | 앱이 만든 폼, 사용자가 Picker로 고른 폼만. 본문·응답·watch 전부 | **기본값.** `services/google_forms/scopes.py`는 빈 dict로 시작하고 인가는 `google_drive/scopes.py`의 `drive.file`로 한다(Docs·Sheets와 동일) |
| `forms.body` | 민감 | 사용자의 모든 폼 읽기·편집·게시 | 교수자의 기존 폼을 Picker 없이 편집해야 할 때만 |
| `forms.body.readonly` | 민감 | 사용자의 모든 폼 읽기 | 기존 폼 구조만 읽을 때 |
| `forms.responses.readonly` | 민감 | 사용자의 모든 폼의 응답 읽기 | 교수자가 UI에서 만든 폼의 응답을 가져와야 할 때만 |
| `drive.readonly` / `drive` | 제한 | Drive 전체 | 쓰지 않는다. CASA 보안 평가 대상 |

- 메서드별 허용 scope: `forms.get`·`watches.create`는 위 전부 + `drive.readonly`. `responses.*`는 `drive`, `drive.file`, `forms.responses.readonly`. `create`·`batchUpdate`·`setPublishSettings`는 `drive`, `drive.file`, `forms.body`.
- 응답자 관리는 Drive `permissions.*`라 `drive.file`로 된다(앱이 만든 폼). 응답자 **목록**은 공식 가이드가 `drive.metadata.readonly`를 예시로 들지만, 앱이 만든 파일의 `permissions.list`는 `drive.file`로도 될 것으로 본다 → 12절.
- Forms 세 scope는 Google Workspace 관리자 콘솔의 "고위험 scope" 목록에도 들어 있다. KAIST 계정을 쓰지 않는 이유와 같은 맥락이고, 개인 계정에서는 영향 없음.

## 4. 엔드포인트 표

Base URL: `https://forms.googleapis.com/v1`. Discovery: `https://forms.googleapis.com/$discovery/rest?version=v1`.

**폼 단위 (`forms`)**

| 메서드 | 경로 | 용도 | 쿼터 | 비고 |
| --- | --- | --- | --- | --- |
| `forms.create` | `POST /forms` (`?unpublished=true`) | 빈 폼 생성 | 쓰기 | 본문은 `info.title`(응답자에게 보이는 제목)과 `info.documentTitle`(Drive 파일명)만 허용. **그 외 필드(설명·items·settings)는 400**. `unpublished`는 2026-06-30까지 의미가 있던 파라미터이고 지금은 기본이 미게시. 폴더 지정 불가 → 생성 후 Drive `files.update`(`addParents`) |
| `forms.get` | `GET /forms/{formId}` | 구조·설정·질문 ID·게시 상태·`responderUri`·`linkedSheetId` | 읽기 | 응답은 안 들어 있다. `fields` 마스크로 줄일 수 있다 |
| `forms.batchUpdate` | `POST /forms/{formId}:batchUpdate` | 제목·설명·설정·항목 **모든 변경** | 쓰기 | 요청 배열을 **원자적으로** 적용. 하나라도 실패면 전체 미적용. `includeFormInResponse=true`면 결과 폼을 같이 받는다. `writeControl.requiredRevisionId`/`targetRevisionId`(Docs와 동일) |
| `forms.setPublishSettings` | `POST /forms/{formId}:setPublishSettings` | 게시 / 게시 취소 / 응답 받기 중단·재개 | 쓰기 | 본문 `publishSettings.publishState{isPublished, isAcceptingResponses}` + `updateMask`. `isPublished=false`면 `isAcceptingResponses`는 강제로 false. 2025-04 이전 "레거시 폼"은 `publishSettings`가 없어 에러 |

**응답 단위 (`forms.responses`)** — 읽기 전용. 생성·수정·삭제 메서드가 없다.

| 메서드 | 경로 | 용도 | 쿼터 | 비고 |
| --- | --- | --- | --- | --- |
| `responses.list` | `GET /forms/{formId}/responses` | 응답 목록 | **expensive read** | `filter`는 `timestamp > N` / `timestamp >= N`(RFC3339 UTC)만 지원. `pageSize` 기본·최대 5,000, `nextPageToken`. 목록 응답의 각 항목에는 `formId`가 빠진다 |
| `responses.get` | `GET /forms/{formId}/responses/{responseId}` | 응답 1건 | 읽기 | |

**알림 단위 (`forms.watches`)** — 9절.

| 메서드 | 경로 | 용도 | 비고 |
| --- | --- | --- | --- |
| `watches.create` | `POST /forms/{formId}/watches` | watch 생성 | 본문 `watch{target.topic.topicName, eventType}`, `watchId`(선택, 4~63자 `[a-z0-9-]`). 7일 후 만료 |
| `watches.renew` | `POST /forms/{formId}/watches/{watchId}:renew` | 7일 연장 | 만료 전에 호출. 자동 갱신 없음 |
| `watches.list` | `GET /forms/{formId}/watches` | 이 프로젝트가 만든 watch 목록 | |
| `watches.delete` | `DELETE /forms/{formId}/watches/{watchId}` | 삭제 | |

**`batchUpdate` 요청 종류** (Request union 전체, 6종)

| 요청 | 필드 | 비고 |
| --- | --- | --- |
| `updateFormInfo` | `info{title, description}`, `updateMask` | `documentTitle`은 출력 전용이라 여기서 못 바꾼다(Drive `files.update` `name`) |
| `updateSettings` | `settings{quizSettings.isQuiz, emailCollectionType}`, `updateMask` | `isQuiz=false`로 바꾸면 모든 문항의 `grading`이 삭제된다 |
| `createItem` | `item`, `location.index` | 인덱스는 `[0..N]`(N=현재 항목 수). 한 배치 안에서 **순서대로 검증**되므로 인덱스 0 요청이 1보다 앞에 와야 한다. 응답 `replies[].createItem{itemId, questionId[]}` |
| `updateItem` | `item`, `location.index`, `updateMask` | ID를 주면 유지, 비우면 새로 생성 |
| `deleteItem` | `location.index` | |
| `moveItem` | `originalLocation.index`, `newLocation.index` | |

**주요 객체**

- `Item`: `itemId`(생성 시 지정 가능), `title`, `description`, kind = `questionItem{question, image}` · `questionGroupItem{questions[], grid{columns, shuffleQuestions}}` · `pageBreakItem` · `textItem` · `imageItem{image}` · `videoItem{video.youtubeUri, caption}`.
- `Question`: `questionId`(읽기 전용), `required`, `grading`, kind = `choiceQuestion{type: RADIO|CHECKBOX|DROP_DOWN, options[]{value, image, isOther, goToAction, goToSectionId}, shuffle}` · `textQuestion{paragraph}` · `scaleQuestion{low, high, lowLabel, highLabel}` · `ratingQuestion{ratingScaleLevel, iconType: STAR|HEART|THUMB_UP}` · `dateQuestion{includeTime, includeYear}` · `timeQuestion{duration}` · `rowQuestion{title}`(격자 행) · `fileUploadQuestion{folderId, types[], maxFiles, maxFileSize}`(**API 생성 불가**).
- `Grading`: `pointValue`(0 이상 필수), `correctAnswers.answers[]{value}`(필수), `whenRight`/`whenWrong`(객관식만), `generalFeedback`.
- `FormSettings.emailCollectionType`: `DO_NOT_COLLECT`(개인 계정 기본) · `VERIFIED`(로그인 계정 자동 수집, Workspace 기본) · `RESPONDER_INPUT`(응답자가 직접 입력, 검증 안 됨).
- `FormResponse`: `responseId`, `createTime`, `lastSubmittedTime`(채점 변경은 제외), `respondentEmail`(수집 설정 시), `answers{questionId: Answer}`, `totalScore`(퀴즈·채점된 경우). `Answer`: `questionId`, `grade{score, correct, feedback}`, `textAnswers.answers[]{value}` 또는 `fileUploadAnswers.answers[]{fileId, fileName, mimeType}`.
- `TextAnswer.value` 형식: 단일 선택은 선택지 문자열 1개, 체크박스는 여러 개, 배율은 숫자 문자열, 날짜는 `MM-DD` / `YYYY-MM-DD` / `… HH:MM`, 시간은 `HH:MM`.
- `Watch`: `id`, `target.topic.topicName`, `eventType: SCHEMA|RESPONSES`, `createTime`, `expireTime`, `state: ACTIVE|SUSPENDED`, `errorType: PROJECT_NOT_AUTHORIZED|NO_USER_ACCESS|OTHER_ERRORS`.

## 5. 요청·응답 샘플

5단계에서 `samples/google_forms/`에 채운다. 1단계에서는 없음.

## 6. 공통 모델 매핑

`Document`(`kind=form`) ← Drive `files.get` + `forms.get`. 2단계 유즈케이스가 정해지면 확정하되, 1단계에서 보이는 대응은 다음과 같다.

| Document 필드 | 출처 | 비고 |
| --- | --- | --- |
| `id` | Drive `id` = `formId` | 같은 값 |
| `kind` | Drive `mimeType` `application/vnd.google-apps.form` → `form` | |
| `title` | `forms.get` `info.title` 우선, 없으면 Drive `name`(= `info.documentTitle`) | 둘이 다를 수 있다. 응답자에게 보이는 것은 `info.title` |
| `url` | Drive `webViewLink` = **편집 화면** | 학생에게 줄 링크는 `responderUri`(`…/viewform`)라 **별도 필드가 필요**하다. `core/models.py`에 `responder_url`을 추가하거나 usecases 반환 타입에 두는 것을 2단계에서 결정 |
| `owner` · `created_at` · `modified_at` · `parent_folder_id` · `trashed` | Drive `files.get` | Docs와 동일 |
| `locked` | 사용 안 함 또는 `publishSettings.publishState.isAcceptingResponses == false` | Forms의 "마감"은 Drive 잠금이 아니라 응답 받기 중단이다. 의미가 다르므로 별도 필드(`accepting_responses`)가 더 정직하다. 2단계에서 결정 |
| `text` | 사용 안 함 | 질문 목록을 평문으로 넣을 이유가 없다 |

응답(`FormResponse`)은 `Document`에 담기지 않는다. 응답 가져오기(유즈케이스 9~12)가 확정되었으므로 5단계에서 `core/models.py`에 공통 응답 모델(예: `FormSubmission{id, form_id, submitted_at, respondent_email, answers{question_id: [str]}, score}`)을 추가한다. 서비스 폴더에 모델을 두지 않는 규칙에 따라 `core/models.py`에서만 정의한다.

## 7. 에러와 예외 케이스

공식 문서에서 확인한 것(미실측). 5단계에서 실측 표를 추가한다.

| 상황 | 예상 응답 | 출처 |
| --- | --- | --- |
| `forms.create` 본문에 `info.title` 외 필드(`items`, `settings`, `description`) 포함 | 400 ("disallowed") | create 레퍼런스 |
| `batchUpdate` 요청 중 하나라도 실패 | 400, 전체 미적용 | batchUpdate 레퍼런스 |
| `createItem` 인덱스가 `[0..N]` 밖, 또는 배치 안 순서가 어긋남 | 400 | update 가이드 |
| `requiredRevisionId`가 최신이 아님 | 400 | WriteControl 레퍼런스. `revisionId`는 24시간만 유효 |
| 퀴즈가 아닌 폼에 `grading` 넣기 | 400 예상 (레퍼런스에 명시 없음, 실측) | — |
| `fileUploadQuestion` 생성 | 실패 ("API currently does not support") | Question 레퍼런스 |
| 레거시 폼(2025-04 이전 생성)에 `setPublishSettings` | 에러 (`publishSettings` 필드 없음) | setPublishSettings 레퍼런스. 앱이 만드는 폼에는 해당 없음 |
| 미게시 폼의 `responderUri` 접근 | 응답 불가 화면 (API 에러 아님) | publish 가이드 |
| 쿼터 초과 | 429 → 지수 백오프 | limits 문서 |
| watch 대상 토픽에 발행 권한 없음 / 다른 프로젝트 토픽 | `watches.create` 실패 또는 `errorType=PROJECT_NOT_AUTHORIZED` | watches 레퍼런스 |
| 사용자가 폼 접근을 잃거나 앱 연결을 끊음 | watch `state=SUSPENDED`, `errorType=NO_USER_ACCESS`. 재시도 없음 | push 가이드 |
| 없는 ID · 휴지통 · Google 계정 아닌 이메일 공유 등 | Docs와 동일(Drive 영역) | `docs/google_docs.md` 7절 |

## 8. 쿼터 · rate limit · 플랜 제약

공식 limits 문서(2026-10-04 확인). 하루 한도는 전부 "무제한".

| 구분 | 프로젝트당 / 분 | 사용자당(프로젝트별) / 분 |
| --- | --- | --- |
| 읽기 요청 (`get`, `responses.get`, `watches.list`…) | 975 | 390 |
| **expensive 읽기 (`responses.list`)** | 450 | **180** |
| 쓰기 요청 (`create`, `batchUpdate`, `setPublishSettings`, `watches.*`) | 375 | 150 |

- 요청 수로 센다. `batchUpdate` 안의 요청 수, 응답 목록의 응답 수는 무관하다. 질문 20개짜리 폼도 `batchUpdate` 1회로 만든다.
- `responses.list`가 별도 쿼터인 것은 Docs·Sheets에 없던 구분이다. 폼 f개를 주기 t분으로 폴링하면 분당 f/t회. 액티비티 100개를 1분마다 돌면 100회로 한도(180)에 근접하므로 **활성(응답 받는 중) 폼만, 5분 주기** 정도로 설계한다.
- 429 → 지수 백오프 `min(2^n초 + 무작위 ms, 32~64초)`. Docs·Drive·Sheets와 같은 패턴. `FormsApiError.is_rate_limit`을 둔다.
- 요금: 무료. "쿼터 초과분에 대해 2026년 중 Cloud 결제 계정에 과금 계획" 문구는 Docs·Drive·Sheets와 동일. 핸드오프 때 한 줄 알린다.
- **Pub/Sub은 별도 요금 체계**(월 10GiB 무료 구간 뒤 과금)이고, 사용하려면 프로젝트에 결제 계정이 연결되어 있어야 한다. 알림 1건은 수백 바이트라 테스트 규모에서는 무료 구간 안이지만, 결제 계정 연결 자체가 개인 계정 테스트의 문턱이다.
- 개인 Google 계정이므로 Workspace 플랜 제약은 없다. `emailCollectionType`의 기본값만 다르다(개인: 수집 안 함, Workspace: 검증 수집).
- 폼당 질문 수·응답 수 한도는 공식 API 문서에 수치가 없다 → 12절.

**호출 수 감각 (유즈케이스 확정 전 추정)**

| 작업 | Forms API | Drive API |
| --- | --- | --- |
| 폼 생성 + 질문 n개 + 게시 + 폴더 이동 | `create` 1 + `batchUpdate` 1 + `setPublishSettings` 1 | `files.update` 1 |
| 응답자 m명 제한 | 0 | `permissions.create` m |
| 마감(응답 중단) | `setPublishSettings` 1 | 0 |
| 응답 가져오기(폼 1개, 5,000건 이하) | `responses.list` 1 (+ 질문 매핑용 `forms.get` 1, 캐시 가능) | 0 |
| 시트로 내보내기(유즈케이스 13, 처음 / 다시) | `responses.list` 1 | 처음: Sheets `create` 1 + `values.update` 1 + Drive `files.update` 1 / 다시: Sheets `values.clear` 1 + `values.update` 1 |
| 알림 유지 | `watches.renew` 폼당 주 1회 | 0 |

## 9. 웹훅 (해당 시)

Forms API에는 **있다**(Google 4종 중 유일). 단 HTTP 콜백이 아니라 **Cloud Pub/Sub**이다. Drive `changes.watch`와는 별개 체계.

**구조**

1. 우리 GCP 프로젝트에 Pub/Sub API 사용 설정 + 결제 계정 연결.
2. 토픽 생성(토픽은 **호출하는 프로젝트 소유**여야 한다).
3. 토픽에 `serviceAccount:forms-notifications@system.gserviceaccount.com`을 `roles/pubsub.publisher`로 추가.
4. 구독 생성: push(우리 HTTPS 엔드포인트로 POST, ngrok 필요) 또는 pull(우리가 당겨감).
5. 교수자 토큰으로 `watches.create`(`eventType=RESPONSES`, `topicName=projects/<p>/topics/<t>`). 폼마다 하나.

**동작**

- 이벤트: `RESPONSES`(새 응답·수정된 응답), `SCHEMA`(폼 내용·설정 변경).
- 알림 본문: 속성 `formId`, `watchId`, `eventType`과 Pub/Sub의 `messageId`, `publishTime`뿐. **응답 데이터 없음** → 받으면 `responses.list?filter=timestamp >= 마지막 시각`으로 조회.
- watch당 **30초에 최대 1회**. 그 사이 여러 응답은 알림 하나로 합쳐진다. 전달은 at-least-once(중복 가능 → `responseId`로 멱등 처리).
- 수명 **7일**. `renew`로 7일씩 연장. 자동 갱신 없음 → Synsory 스케줄러가 주기적으로 `renew`.
- 한도: 프로젝트·폼·이벤트당 20개(사용자당 1개), 폼당 50개(모든 프로젝트 합).
- 교수자가 폼 접근을 잃거나 앱 연결을 끊으면 `SUSPENDED`. 재인가 후 `renew`하면 재개.

**판단(PLAN.md 예외 행의 "폴링으로 충분한지 먼저 판단")**: 설문·동료평가는 마감 뒤에 한 번 가져오면 되는 경우가 많고, 진행 중 현황도 수 분 지연이면 충분하다. `responses.list` 쿼터(사용자당 분당 180)도 여유가 있다. **5단계는 폴링으로 구현한다.** "제출 즉시 반응" 아이디어는 2단계에서 제외했다(2026-10-06, 1절). 그래서 Pub/Sub은 테스트하지 않는다. 나중에 필요해지면 결제 계정 연결과 ngrok(push) 또는 pull 구독이 필요하다.

## 10. 함정과 권장 패턴

공식 문서 기준(미실측). 5단계에서 확인된 것은 날짜를 붙여 갱신한다.

1. **만들면 미게시다.** 2026-06-30 이후 API로 만든 폼은 미게시 상태로 생성된다. `create` → `batchUpdate` → `setPublishSettings{isPublished: true, isAcceptingResponses: true}` 순서를 usecases 함수 하나로 묶어, 게시를 빠뜨린 폼이 남지 않게 한다. 질문을 다 넣은 뒤 게시해야 학생이 미완성 폼을 보지 않는다.
2. **`create`는 제목만.** `info.title`과 `documentTitle` 외 필드를 보내면 400. 질문·설명·설정은 전부 두 번째 호출 `batchUpdate`로. Docs와 달리 Drive 변환 업로드 같은 우회 경로가 없다(Forms로 변환되는 업로드 형식 없음).
3. **마감 = 응답 받기 중단.** `setPublishSettings{isPublished: true, isAcceptingResponses: false}`. 게시는 유지되어 학생이 링크를 열면 "더 이상 응답을 받지 않습니다"가 뜬다. 교수자는 결과를 계속 본다. Docs의 권한 낮추기에 해당하며 되돌리기도 같은 호출. Google에 예약 기능이 없으므로 due 시각 호출은 Synsory 스케줄러 책임(Docs 10절 11항과 같은 구조).
4. **응답자 제한은 Drive 권한이다.** "특정 사용자만 응답"은 `permissions.create{type: user, role: reader, view: published, emailAddress}`. "링크가 있는 모든 사용자"는 `{type: anyone, role: reader, view: published}`. 목록은 `permissions.list?includePermissionsForView=published`에서 `view=published`인 것. 폼 **편집** 공유(`role: writer`, `view` 없음)와 구분해야 한다. 응답자 제한 없이 게시했을 때 기본값이 "링크가 있는 모든 사용자"인지 "소유자만"인지는 12절(실측).
5. **"누가 제출했나"는 설정으로 확보한다.** `respondentEmail`은 `emailCollectionType`이 `VERIFIED`(로그인 계정, 신뢰 가능) 또는 `RESPONDER_INPUT`(입력값, 검증 안 됨)일 때만 온다. 학생 식별이 필요하면 생성 직후 `updateSettings`로 `VERIFIED`를 켠다. 4항의 응답자 제한을 걸면 어차피 로그인이 필요하므로 둘을 함께 쓴다.
6. **응답의 답은 선택지 텍스트다.** 객관식 답은 `options[].value` 문자열로 온다. 생성 후 선택지 문구를 바꾸면 이전 응답과 매칭이 어긋난다. Synsory가 폼을 만들 때 `questionId`(응답 `replies[].createItem.questionId`로 받음)와 선택지 문구를 저장해 두고, 응답 해석은 그 저장본으로 한다. `forms.get`을 매번 부르지 않아도 된다.
7. **격자(행렬) 질문은 행마다 `questionId`.** `questionGroupItem.questions[]`의 각 `rowQuestion`이 별도 ID를 가지며 응답도 행별로 온다. 동료평가(평가 항목 × 척도)를 격자로 만들면 응답 매핑이 "행 ID → 값"이 된다.
8. **`responses.list`는 "expensive"다.** 사용자당 분당 180. 폴링은 활성 폼만, 주기는 분 단위로. `filter=timestamp >= <마지막 lastSubmittedTime>`로 증분 조회하되 `>=`는 경계 응답이 중복되므로 `responseId`로 멱등 처리. 수정 허용 폼에서는 같은 `responseId`가 다시 오고 `lastSubmittedTime`만 바뀐다.
9. **퀴즈는 순서가 있다.** `updateSettings{quizSettings.isQuiz: true}`를 먼저 (같은 배치 안에서 앞에) 두고 `grading`이 있는 `createItem`을 뒤에 둔다. `isQuiz=false`로 되돌리면 정답·배점이 **전부 삭제**된다. 자동 채점은 객관식(정답/오답 피드백 가능)과 단답(정답 문자열 완전 일치, 일반 피드백만)만. 수동 채점·점수 공개는 UI.
10. **설정 대부분은 UI다.** 응답 1회 제한, 제출 후 수정, 확인 메시지, 순서 섞기, 응답 사본 메일은 API에 없다. 교수자에게 "폼 생성 후 설정에서 바꿔 주세요"로 안내하거나, 그 설정이 꼭 필요한 유즈케이스는 보류한다. "응답 1회 제한"은 Synsory 쪽에서 `respondentEmail` 중복으로 걸러 대체할 수 있다.
11. **응답의 기본 저장소는 폼이고, 시트는 선택이다.** 공식 도움말 기준(2026-10-06 확인)으로 응답은 폼에 저장된다. 시트 연결은 교수자가 응답 탭에서 "응답 저장 위치 선택"으로 새 시트나 기존 시트를 고르는 직접 동작이고, 새 폼을 자동으로 연결하는 설정은 없다. 연결된 시트는 별도 파일이라 지워도 폼과 응답은 남고, 연결을 끊으면 새 응답만 시트로 가지 않는다. API로는 연결할 수 없다(`linkedSheetId`는 읽기 전용). 그래서 Synsory는 항상 `responses.list`로 폼에서 가져온다. Sheets가 필요하면 유즈케이스 13으로 앱이 만든 시트에 사본을 쓰고, CSV·xlsx 파일은 유즈케이스 12로 Synsory 서버가 만든다. 폼은 Drive 내보내기가 안 된다.
12. **템플릿은 질문 목록 JSON으로.** Synsory가 보관하는 템플릿은 `createItem` 배열 자체로 두는 것이 가장 단순하다(플레이스홀더 치환 후 `batchUpdate`). 대안으로 앱이 만든 원본 폼을 Drive `files.copy`로 복사하는 방식이 있는데, 폼 복사가 API로 되는지와 복사본에 응답이 딸려오지 않는지는 12절(실측).
13. **`responderUri`와 `webViewLink`는 다르다.** Drive가 주는 링크는 편집 화면(`/edit`)이다. 학생에게는 `forms.get`의 `responderUri`(`/viewform`)를 준다. Docs 10절 12항처럼 `?authuser=<이메일>`을 붙이는 것도 검토.
14. **낙관적 잠금은 Docs와 같다.** `writeControl.requiredRevisionId`로 교수자가 UI에서 동시에 편집한 변경을 덮어쓰지 않게 한다. `revisionId`는 24시간만 유효하므로 `forms.get` 직후에만 쓴다.
15. **SDK 없이 REST.** 메서드가 11개뿐이고 Pub/Sub도 REST(또는 pull은 `google-cloud-pubsub` 없이 REST `subscriptions:pull`)로 된다. httpx로 충분. 예외 근거 없음. Pub/Sub 쪽을 실제로 구현하게 되면 그때 SDK 필요성을 다시 본다.
16. **Docs·Sheets와 다른 점 정리.** 생성 후 **게시 단계가 하나 더 있다.** 마감은 권한이 아니라 게시 설정. 학생은 편집자가 아니라 응답자(Drive 권한의 `view=published`). 응답 읽기가 별도 쿼터. 웹훅이 있지만 Pub/Sub. 내보내기 없음. 설정 대부분이 API 밖.

## 11. 샘플 코드 (`usecases.py`의 흐름을 기준으로)

5단계에서 `app/services/google_forms/usecases.py`를 구현한 뒤 작성한다. 구조는 Docs와 같다: `FormsClient(access_token)` + `DriveClient`, 유즈케이스 함수는 FastAPI 없이 동작, 에러는 `FormsApiError(status, status_text, message, is_rate_limit)`. 1단계에서 보이는 뼈대:

```python
# 생성: create → batchUpdate(설정 + 질문 전부) → setPublishSettings → Drive 폴더 이동 → (선택) 응답자 제한
# 마감: setPublishSettings(isAcceptingResponses=False)
# 수집: responses.list(filter="timestamp >= <last>") → 저장된 questionId 매핑으로 해석 → FormSubmission 목록
```

## 12. 미확인 · 보류 항목

| 항목 | 확인 방법 · 시점 |
| --- | --- |
| 게시 후 응답자 제한을 걸지 않았을 때 기본 응답 가능 범위(링크가 있는 모든 사용자 vs 소유자만) | 5단계 첫 게시 때 테스트 계정(koreaji8)으로 `responderUri` 접속 |
| `permissions.create{view: published}`가 `drive.file`로 되는지, `permissions.list?includePermissionsForView=published`가 `drive.file`로 되는지 | 5단계. 가이드는 응답자 목록에 `drive.metadata.readonly`를 예시로 듦 |
| `emailCollectionType=VERIFIED`가 개인 계정 폼에서 동작하는지, 응답자에게 로그인 화면이 뜨는지 | 5단계. 테스트 계정으로 응답 |
| `responses.list`의 `filter=timestamp`가 `createTime`·`lastSubmittedTime` 중 어느 것인지 | 5단계. 수정 허용 폼에서 재제출 후 확인 |
| 퀴즈가 아닌 폼에 `grading`을 넣었을 때 에러인지 무시인지, `isQuiz`와 `createItem`을 같은 배치에 넣어도 되는지 | 5단계 |
| Drive `files.copy`로 폼 복사가 되는지, 복사본에 응답·게시 상태가 딸려오는지 | 5단계. 템플릿 방식 결정에 필요 |
| 퀴즈의 점수 공개 시점 기본값(제출 직후 / 검토 후), 교수자가 UI에서 정답을 바꾸면 기존 응답이 다시 채점되는지 | 유즈케이스 2·10. 5단계에서 테스트 계정으로 응답 후 확인. API로 바꿀 수 없으므로 기본값이 "검토 후"면 교수자 안내가 필요하다 |
| Picker에서 폼이 보이고 골라지는지(`DocsView(ViewId.FORMS)` 또는 `setMimeTypes("application/vnd.google-apps.form")`), 고른 뒤 `drive.file`로 `forms.get`·`files.copy`가 되는지 | 유즈케이스 4의 전제. 5단계에서 `GET /google/picker`에 폼 보기를 추가해 확인. 안 되면 4 보류 |
| Drive `files.create`(`mimeType: application/vnd.google-apps.form`)로 폴더 안에 바로 생성되는지 | 5단계. 되면 `files.update(addParents)` 1회를 줄인다. Drive 문서에 명시 없음 |
| 교수자가 UI에서 "Sheets에 연결"로 만든 응답 시트를 `drive.file`로 읽을 수 있는지(`linkedSheetId`로 ID는 얻는다) | Forms가 만든 파일이라 접근 불가로 예상. 안 되면 13으로 대신한다는 현재 설계가 맞다. 5단계에서 교수자 계정으로 UI 연결 후 `values.get` 시도 |
| 파일 업로드 질문 응답의 Drive 파일을 `drive.file` 토큰으로 읽을 수 있는지 | API로 파일 업로드 질문을 못 만드니 유즈케이스에 들어올 가능성 낮음. 보류 |
| 폼당 질문 수·응답 수 상한 | 공식 API 문서에 수치 없음. 수강생 규모에서는 문제없을 것으로 보고 보류 |
| watch 한도 표현 차이(가이드 "프로젝트·폼·이벤트당 20개, 사용자당 1개" vs 레퍼런스 "프로젝트·폼·이벤트당 1개") | Pub/Sub을 테스트하게 되면 두 번째 `watches.create`로 확인 |
| ~~Pub/Sub 테스트 여부~~ | 결정 완료(2026-10-06): 제외. 1절 "검토 후 제외" |
| `unpublished` 쿼리 파라미터가 2026-06-30 이후 무시되는지 | 5단계 첫 생성 응답의 `publishSettings`로 확인 |
| 2026년 중 쿼터 초과 과금 계획의 실제 시행 여부 | 핸드오프 직전 재확인(Docs와 공통) |

## 출처 (2026-10-04 확인)

- Forms API 개요 — https://developers.google.com/workspace/forms/api/guides
- REST 리소스 목록 — https://developers.google.com/workspace/forms/api/reference/rest
- Form 리소스(Item, Question, FormSettings, PublishSettings) — https://developers.google.com/workspace/forms/api/reference/rest/v1/forms
- forms.create — https://developers.google.com/workspace/forms/api/reference/rest/v1/forms/create
- forms.get — https://developers.google.com/workspace/forms/api/reference/rest/v1/forms/get
- forms.batchUpdate(Request 타입) — https://developers.google.com/workspace/forms/api/reference/rest/v1/forms/batchUpdate
- forms.setPublishSettings — https://developers.google.com/workspace/forms/api/reference/rest/v1/forms/setPublishSettings
- forms.responses(FormResponse, list 필터) — https://developers.google.com/workspace/forms/api/reference/rest/v1/forms.responses
- forms.responses.list — https://developers.google.com/workspace/forms/api/reference/rest/v1/forms.responses/list
- forms.watches(Watch, create) — https://developers.google.com/workspace/forms/api/reference/rest/v1/forms.watches
- Usage limits — https://developers.google.com/workspace/forms/api/limits
- 폼 만들기 가이드 — https://developers.google.com/workspace/forms/api/guides/create-form-quiz
- 폼 수정 가이드 — https://developers.google.com/workspace/forms/api/guides/update-form-quiz
- 게시·응답자 관리 가이드 — https://developers.google.com/workspace/forms/api/guides/publish-form
- API 변경 안내(2026-06-30 미게시 기본값) — https://developers.google.com/workspace/forms/api/guides/api-changes-to-google-forms
- 퀴즈 채점 가이드 — https://developers.google.com/workspace/forms/api/guides/setup-grading
- 응답 가져오기 가이드 — https://developers.google.com/workspace/forms/api/guides/retrieve-forms-responses
- 푸시 알림 가이드 — https://developers.google.com/workspace/forms/api/guides/push-notifications
- REST vs Apps Script 비교(응답 제출 미지원) — https://developers.google.com/workspace/forms/api/guides/compare-rest-apps-script
- 릴리스 노트 — https://developers.google.com/workspace/forms/release-notes
- 응답 저장 위치 선택(Forms 도움말, 2026-10-06 확인) — https://support.google.com/docs/answer/2917686
- Drive MIME 타입 — https://developers.google.com/workspace/drive/api/guides/mime-types
- Drive 내보내기 형식(Forms 없음) — https://developers.google.com/workspace/drive/api/guides/ref-export-formats
