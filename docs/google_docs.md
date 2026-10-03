# Google Docs 연동 스펙

상태: 6단계(스펙 문서화) 완료 · 7단계(핸드오프) 대기
최종 수정: 2026-10-03 · 작성: 상현
확인 기준: 공식 문서는 2026-09-30, 실측은 2026-10-02~03 (개인 Gmail 계정, 테스트 상태 OAuth 앱)

옮기는 파일: `app/services/google_docs/{client,mapper,scopes,usecases}.py`와 `app/services/google_drive/{client,mapper,scopes,usecases}.py`, 그리고 이 문서와 `docs/google_drive.md`. `router.py`·`core/oauth.py`·`core/token_store.py`는 테스트 서버용이라 옮기지 않고, 2절·11절을 참고해 서비스 레포 방식으로 다시 쓴다.

Drive API 쪽 내용(파일 메타데이터, 폴더, 내보내기, 변경 감지)은 `docs/google_drive.md`에 있다. 이 문서는 Docs API(`docs.googleapis.com/v1`)만 다룬다.

## 1. 이 서비스로 하는 일 (유즈케이스)

2026-10-03 상현 확정. 전제: OAuth로 연결하는 사용자는 **교수자**다. 문서는 교수자 Drive에 교수자 소유로 만들어지고, 학생(그룹원)은 Drive 공유로 편집 권한을 받는다. 학생은 Synsory에 Google 계정을 연결할 필요가 없고 Google 계정 이메일만 있으면 된다.

| # | 유즈케이스 | 호출 순서 | usecases 함수 |
| --- | --- | --- | --- |
| 1 | 특정 액티비티에 해당하는 폴더를 만든다 | Drive `files.create` (folder, `parents`=강의 폴더 ID 선택) | `google_drive.usecases.create_folder` |
| 2 | 교수자가 템플릿(본문 틀 + 팀명으로 포맷되는 문서명)으로 폴더 안에 그룹마다 문서를 만들고 그룹원에게 편집 권한을 준다 | 그룹마다: Drive `files.create` (Markdown 업로드 + Docs 변환, `parents`=액티비티 폴더) → 그룹원마다 Drive `permissions.create` (`type=user, role=writer`) | `google_docs.usecases.create_group_documents` |
| 3 | 마감(due) 시점에 편집을 비활성화한다 | 문서마다: Drive `permissions.list` → 학생(writer)마다 `permissions.update` `role=commenter`. 교수자(owner)·`keep_emails`는 그대로. Synsory 스케줄러가 due 시각에 호출 | `close_submissions` (→ `downgrade_editors`) |
| 4 | 같은 시점에 파일로 내보내 Turnitin 등 다른 API로 보낸다 | Drive `files.export` (`mimeType`=docx 또는 pdf, 10MB 상한) → 바이트를 호출자에게 반환 | `export_document` |

**유즈케이스별 메모**

- 1: 강의 폴더가 교수자가 Drive 웹에서 직접 만든 폴더여도 ID만 알면 그 안에 만들 수 있다(`docs/google_drive.md` 10절 실측). 폴더 ID 검증은 불가능하므로 잘못된 ID면 404.
- 2: 템플릿은 **Synsory가 보관하는 Markdown 텍스트**와 제목 포맷 문자열로 가정한다(플레이스홀더 `{{team_name}}`, `{{activity_name}}`, `{{due}}`). 교수자가 Drive에 이미 가진 Google Doc을 템플릿으로 쓰려면 앱이 그 문서를 읽을 수 있어야 하므로 Picker가 필요하다. 이 경우는 보류. 생성 방식은 Markdown 변환(A)을 기본으로 하고, Docs `create`+`batchUpdate`(B)를 비교용으로 함께 구현한다.
- 2: 공유는 그룹원 이메일이 Google 계정이어야 한다(실측: 아니면 400 `invalidSharingRequest`, 알림 메일을 켜야 초대 가능). 같은 이메일 재공유는 200으로 멱등. 공유 알림 메일은 기본 끔(`sendNotificationEmail=false`)이고 알림 없이도 URL로 바로 열린다. 7절 실측 표.
- 3: **권한 낮추기 방식으로 확정(2026-10-03 상현).** 교수자(owner)는 마감 뒤에도 웹·API 모두 편집 가능, 학생은 보기·댓글만. 조교 등은 `keep_emails`로 제외. 검토했다가 뺀 방식: ① 문서 잠금(`contentRestrictions.readOnly`)은 동작하지만 교수자도 API 편집이 403이라 제외. ② `permissions.create`의 `expirationTime`은 개인 계정에서 403 `cannotSetExpiration`으로 불가. "비활성화 = 읽기·댓글은 유지"다. Google에 예약 기능이 없으므로 due 시각에 호출하는 스케줄러는 Synsory 서비스 쪽 책임이고 여기서는 `close_submissions`만 제공한다(10절 11항).
- 4: Turnitin API 연동은 이 레포 범위 밖이다. 여기서는 내보낸 바이트와 MIME, 파일명을 돌려주는 데까지 한다. 3번 잠금 뒤에 내보내야 제출 시점 내용이 고정된다.
- scope: 네 유즈케이스 모두 앱이 만든 파일만 다루므로 `drive.file` 하나로 충분하다. Docs API는 B 방식과 본문 확인(`documents.get`)에만 쓴다.

## 2. 인증

Google 4종이 공유하는 OAuth 2.0 사용자 동의 흐름이다. 코드는 `app/core/oauth.py`(테스트 서버용, 옮기지 않음). 공통 제약(refresh token 7일·100개 한도, 증분 인가, 세분화 동의)은 `docs/google_drive.md` 2절에 있다. 여기서는 **처음부터 재현하는 절차**를 적는다.

**2.1 GCP 콘솔 설정 (개발자가 한 번, 2026-10-02 실제 수행 순서)**

| 순서 | 메뉴 | 값 | 빠뜨리면 |
| --- | --- | --- | --- |
| 1 | 새 프로젝트 | 이름 자유, 조직 없음 | — |
| 2 | API 및 서비스 → 라이브러리 | **Google Drive API**, **Google Docs API** 사용 설정 | 로그인은 되는데 호출마다 403 "API has not been used in project…". 에러 본문에 활성화 링크가 들어 있다 |
| 3 | Google Auth Platform → 브랜딩 | 앱 이름, 지원 이메일. 대상(Audience)은 **외부** (개인 계정은 내부 불가) | — |
| 4 | Google Auth Platform → 대상 | 게시 상태 **테스트** 유지. 테스트 사용자에 로그인할 Google 계정 추가 (최대 100명) | 미등록 계정 로그인 시 "액세스 차단됨: 이 앱은 Google의 인증 절차를 완료하지 않았습니다" |
| 5 | Google Auth Platform → 데이터 액세스 | `…/auth/drive.file` 추가 (비민감. 선택이지만 심사 대비해 등록) | 테스트 로그인에는 영향 없음 |
| 6 | Google Auth Platform → 클라이언트 | 유형 **웹 애플리케이션**. 승인된 리디렉션 URI `http://localhost:8000/auth/google/callback` (글자 단위 일치, 끝 슬래시 없음). JavaScript 원본은 비움 | `redirect_uri_mismatch` |
| 7 | 발급된 ID·Secret | `.env`의 `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`. Secret은 생성 화면을 닫으면 다시 못 봄 | 서버가 500으로 ".env에 없습니다" 안내 |

서비스 배포 시 추가로: 리디렉션 URI에 실제 도메인 추가, 개인정보처리방침·약관 URL, 게시 상태를 프로덕션으로 전환 + 앱 검증(`drive.file`은 비민감이라 브랜드 확인 수준). 테스트 상태로 두면 refresh token이 7일마다 만료되고 테스트 사용자만 로그인된다.

**2.2 인가 요청**

- 인가 URL: `https://accounts.google.com/o/oauth2/v2/auth`, 파라미터 `client_id`, `redirect_uri`, `response_type=code`, `scope`(공백 구분), `state`, **`access_type=offline`, `prompt=consent`, `include_granted_scopes=true`**.
- `scope`는 등록된 서비스들의 `scopes.py`를 provider별로 합친 것이다(`core/oauth.py::collect_scopes`). 현재 Google은 `drive.file` 하나. 서비스가 늘어 scope가 추가되면 **사용자가 재동의**해야 한다.
- `state`는 CSRF 방지용 난수. 테스트 서버는 메모리 set에 두지만 서비스 레포는 세션·DB에 둔다.

**2.3 콜백·토큰 교환**

- `GET /auth/google/callback?code=…&state=…&scope=…`. Google은 `code`를 쿼리로 보내므로 **서버 접근 로그에 code가 남는다**. 1회용이라 위험은 낮지만 로그를 문서·샘플에 붙일 때 가린다.
- 토큰 URL `https://oauth2.googleapis.com/token`, `grant_type=authorization_code`, `code`, `redirect_uri`, `client_id`, `client_secret`(본문). 응답: `access_token`(1시간), `refresh_token`(첫 동의 또는 `prompt=consent` 때만), `expires_in`, `scope`(실제 부여된 것), `token_type`.
- 응답의 `scope`를 요청한 것과 비교해 사용자가 동의 화면에서 뺀 scope를 찾는다(`missing_scopes`). `drive.file`이 빠지면 네 유즈케이스 모두 불가하므로 재요청한다.

**2.4 갱신**

- 같은 토큰 URL에 `grant_type=refresh_token`, `refresh_token`, `client_id`, `client_secret`. 응답에 `refresh_token`은 **없다**(Google은 회전하지 않음). 기존 것을 유지한다.
- 저장소에는 사용자 × provider당 최신 토큰 한 벌만 둔다. 만료 60초 전부터 갱신한다.
- 실측(2026-10-03): 만료된 access token 상태에서 첫 API 호출 → 자동 갱신 → 성공. `POST /auth/google/refresh`로 강제 갱신 시 `refresh_token_rotated: false`.
- 갱신 실패(`invalid_grant`)는 refresh token 만료·철회다. 테스트 상태 7일, 미사용 6개월, 사용자가 https://myaccount.google.com/permissions 에서 연결 끊음, 100개 한도 초과가 원인이다. **마감 처리는 교수자가 로그인해 있지 않은 시각에 돌아가므로**, 이 실패를 교수자에게 "다시 연결" 알림으로 바꾸는 처리가 서비스 레포에 필요하다(10절 11항).

**2.5 사용자 모델**

OAuth로 연결하는 사람은 **교수자**뿐이다. 문서는 교수자 Drive에 교수자 소유로 만들어지고, 학생은 Drive 공유(`permissions.create`)로 편집 권한을 받는다. 학생은 Synsory에 Google 계정을 연결하지 않으며 Google 계정 이메일만 필요하다. 교수자가 여러 명이면 교수자마다 토큰 한 벌이다.

## 3. scope 표

**확정(2026-10-03 실측):** 유즈케이스 1~4 모두 `drive.file` 하나로 동작했다. `services/google_docs/scopes.py`는 빈 dict이고 인가는 `services/google_drive/scopes.py`의 `drive.file`로 이루어진다. 아래 민감·제한 scope는 쓰지 않는다.

| scope | 등급 | 가능한 범위 | 판단 |
| --- | --- | --- | --- |
| `drive.file` | 비민감 (권장) | 앱이 만든 파일, 사용자가 Picker로 고른 파일만 | **기본값.** `documents.create` · `get` · `batchUpdate` 모두 이 scope를 받는다 |
| `documents.readonly` | 민감 | 사용자 모든 Docs 읽기 | 기존 문서를 Picker 없이 읽어야 할 때만 |
| `documents` | 민감 | 사용자 모든 Docs 읽기·쓰기 | 기존 문서를 Picker 없이 편집해야 할 때만 |
| `drive.readonly` / `drive` | 제한 | Drive 전체 | 쓰지 않는다. CASA 보안 평가 대상 |

`drive.file`로 되는 것과 안 되는 것의 경계(앱이 만든 파일만 읽기, 사용자 폴더에 넣기는 가능)는 `docs/google_drive.md` 10절. 교수자가 Drive에 이미 가진 Google Doc을 템플릿으로 쓰는 요구가 생기면 Google Picker를 붙이거나 `documents.readonly`를 추가해야 하고, 후자는 민감 scope라 심사 수준이 올라간다.

## 4. 엔드포인트 표

Base URL: `https://docs.googleapis.com/v1`

| 메서드 | 경로 | 용도 | 쿼터 구분 | 비고 |
| --- | --- | --- | --- | --- |
| `documents.create` | `POST /documents` | 빈 문서 생성 | 쓰기 | `title` 외 모든 필드 무시. 폴더 지정 불가. **현재 유즈케이스에서는 미사용**(Markdown 변환이 대신함, 10절 9항) |
| `documents.get` | `GET /documents/{documentId}` | 문서 구조·내용 읽기 | 읽기 | `includeTabsContent=true` 고정. 본문 확인·평문 추출(`read_document`)에 사용 |
| `documents.batchUpdate` | `POST /documents/{documentId}:batchUpdate` | 모든 편집 | 쓰기 | 요청 배열을 한 번에 원자적으로 적용. 현재는 비교용 방식 B에서만 사용. 생성 후 부분 수정이 필요해지면 여기 |

유즈케이스 1~4의 호출 대부분은 Drive API다(`docs/google_drive.md` 4절). Docs API는 읽기 확인에만 쓴다.

**`documents.get` 파라미터**

| 파라미터 | 기본값 | 의미 |
| --- | --- | --- |
| `includeTabsContent` | `false` | `false`면 **첫 번째 탭 내용만** `body` 등 최상위 필드에 담긴다. `true`면 `tabs[]`에 모든 탭이 담기고 최상위 텍스트 필드는 비어 있다 |
| `suggestionsViewMode` | `DEFAULT_FOR_CURRENT_ACCESS` | 제안을 인라인으로 보일지, 수락·거절한 상태로 미리 볼지 |
| `commentsViewMode` | `COMMENTS_VIEW_MODE_OMITTED` | 댓글 포함 여부. `includeTabsContent=true`(또는 tabs 필드 마스크)가 필요하다 |

**`batchUpdate` 요청 종류** (Request union 필드 전체)

| 분류 | 요청 |
| --- | --- |
| 텍스트 | `insertText`, `deleteContentRange`, `replaceAllText`, `updateTextStyle` |
| 문단·목록·스타일 | `updateParagraphStyle`, `createParagraphBullets`, `deleteParagraphBullets`, `updateNamedStyle` |
| 이름 있는 범위 | `createNamedRange`, `deleteNamedRange`, `replaceNamedRangeContent` |
| 표 | `insertTable`, `insertTableRow`, `insertTableColumn`, `deleteTableRow`, `deleteTableColumn`, `updateTableColumnProperties`, `updateTableCellStyle`, `updateTableRowStyle`, `mergeTableCells`, `unmergeTableCells`, `pinTableHeaderRows` |
| 이미지·개체 | `insertInlineImage`, `replaceImage`, `deletePositionedObject` |
| 레이아웃 | `insertPageBreak`, `insertSectionBreak`, `updateSectionStyle`, `updateDocumentStyle` |
| 머리글·바닥글·각주 | `createHeader`, `createFooter`, `deleteHeader`, `deleteFooter`, `createFootnote` |
| 탭 | `addDocumentTab`, `deleteTab`, `updateDocumentTabProperties` |
| 스마트 칩 | `insertPerson`, `insertRichLink`, `insertDate` |
| 댓글·제안 (Developer Preview) | `insertComment`, `addCommentReply`, `updateCommentPost`, `deleteComment`, `deleteCommentReply`, `acceptSuggestion`, `rejectSuggestion`, `deleteSuggestion` |

**`batchUpdate` 응답**: `replies[]`(요청과 1:1, 비어 있을 수 있음), `writeControl`(적용 후 revision), `suggestionResponses[]`.

## 5. 요청·응답 샘플

`samples/google_docs/`, `samples/google_drive/` (요청·응답은 우리 엔드포인트 기준, 소유자 이름·이메일 마스킹). 2026-10-03 기준:

| 유즈케이스 | 파일 |
| --- | --- |
| 1 폴더 생성 | `google_drive/uc1-create-activity-folder.json` |
| 2 그룹 문서 생성 (A Markdown / B Docs API) | `uc2-create-group-documents-markdown.json`, `uc2-create-group-documents-docs-api.json` |
| 2 공유 · 공유 에러 | `uc2-share-on-create.json`, `uc2-share-errors.json` |
| 3 마감 처리(권한 낮추기) · 만료 공유 불가 | `uc3-revoke-edit-access.json`, `uc3-close-submission.json`, `uc3-share-with-expiration-fails.json` |
| 3 (미채택) 잠금 · 잠긴 채 편집 · 해제 | `uc3-lock-for-submission.json` (기록용) |
| 4 내보내기 | `uc4-export.json` |
| 배관·에러 | `create-empty.json`, `read.json`, `read-trashed.json`, `error-not-found.json`, `create-empty-into-user-folder.json` |

## 6. 공통 모델 매핑

`Document` ← Drive `files.get` + (읽기 시) Docs `documents.get`. 구현: `google_drive/mapper.py::document_from_drive_file`, `google_docs/mapper.py::document_from_docs`.

| Document 필드 | 출처 | 비고 |
| --- | --- | --- |
| `id` | Drive `id` = Docs `documentId` | 같은 값 |
| `kind` | Drive `mimeType` | `application/vnd.google-apps.document` → `doc`, 폴더 → `folder` |
| `title` | Docs `title` 우선, 없으면 Drive `name` | 같은 값이지만 Docs 응답이 있으면 그쪽 |
| `url` | Drive `webViewLink` | |
| `owner` | Drive `owners[0].displayName` | 이메일은 넣지 않는다 |
| `created_at` / `modified_at` | Drive `createdTime` / `modifiedTime` | RFC3339 → datetime |
| `parent_folder_id` | Drive `parents[0]` | 루트면 내 드라이브 루트 ID |
| `trashed` | Drive `trashed` | 휴지통 문서도 API는 200이므로 필수 |
| `locked` | Drive `contentRestrictions[].readOnly` | 유즈케이스 3 잠금 상태 |
| `text` | Docs `body` 또는 `tabs[]` 평문 | 읽기 시나리오에서만. 모든 탭·표 셀 포함 |

> 확정된 전제: `Document.title`과 `id`는 Docs 응답(`title`, `documentId`)에서, `owner` · `created_at` · `modified_at` · `url`은 Drive `files.get`에서 온다(`CLAUDE.md` 규칙). Docs 응답에는 이 네 필드가 없다.

## 7. 에러와 예외 케이스

공식 문서에서 확인한 것(아직 실측하지 않음):

| 상황 | 예상 응답 | 출처 |
| --- | --- | --- |
| `batchUpdate` 요청 중 하나라도 잘못됨 | 전체 실패, 아무것도 적용 안 됨 | batchUpdate 레퍼런스 |
| `requiredRevisionId`가 최신 revision이 아님 | 400 Bad Request | batchUpdate 레퍼런스 |
| 쿼터 초과 | 429 Too many requests | limits 문서 |
| 이미지가 50MB 이상 또는 25메가픽셀 초과 | 요청 실패 (코드 5단계 확인) | Request 레퍼런스 |

**실측 (2026-10-02 ~ 03)**

| 상황 | 응답 | 샘플 |
| --- | --- | --- |
| 없는 ID로 `documents.get` | 404 `NOT_FOUND` "Requested entity was not found." | `error-not-found.json` |
| 휴지통 문서 `documents.get` | **200** 정상. `Document.trashed`로 판단 | `read-trashed.json` |
| 잠긴(`readOnly`) 문서에 `batchUpdate` | **403 `PERMISSION_DENIED`** "The caller does not have permission". 소유자 토큰이어도 같다 | `uc3-lock-for-submission.json` |
| 이미 공유된 이메일에 다시 `permissions.create` | 200, 같은 permission id (멱등) | `uc2-share-errors.json` |
| Google 계정 아닌 이메일 공유, 알림 끔 | 400 `invalidSharingRequest`. 초대하려면 `sendNotificationEmail=true` 필요 | `uc2-share-errors.json` |
| 형식이 틀린 이메일 | 400 `invalid` | `uc2-share-errors.json` |
| `expirationTime` 붙여 공유 (개인 계정) | 403 `cannotSetExpiration` | `uc3-share-with-expiration-fails.json` |

## 8. 쿼터 · rate limit · 플랜 제약

| 구분 | 프로젝트당 / 분 | 사용자당(프로젝트별) / 분 |
| --- | --- | --- |
| 읽기 요청 (`get`) | 3,000 | 300 |
| 쓰기 요청 (`create`, `batchUpdate`) | 600 | 60 |

- `batchUpdate` 한 번은 안에 요청이 몇 개든 쓰기 1회다. 사용자당 분당 60회 제한 때문에 편집은 반드시 모아서 한 번에 보낸다.
- 429를 받으면 지수 백오프로 재시도한다: 대기 = `min(2^n초 + 무작위 0~1000ms, 최대 32~64초)`. 최대치에 도달해도 같은 간격으로 계속 재시도할 수 있다.
- 요금: 현재 무료. 단, 공식 문서에 "쿼터 초과분에 대해 2026년 중 Cloud 결제 계정에 과금할 계획"이라고 적혀 있다. 테스트 규모에서는 영향 없음. 서비스 레포 핸드오프 때 한 줄 알린다.
- 쿼터 증가는 Cloud 콘솔 Quotas 페이지에서 요청 가능 (승인 보장 없음).
- 개인 Google 계정이므로 Workspace 플랜 제약은 없다.

**유즈케이스별 호출 수 (그룹 g개, 그룹당 학생 m명 기준, 2026-10-03 구현 기준)**

| 유즈케이스 | Docs API | Drive API | 비고 |
| --- | --- | --- | --- |
| 1 폴더 생성 | 0 | 1 (`files.create`) | |
| 2 그룹 문서 생성 + 공유 | 0 | g × (1 `files.create` + m `permissions.create`) | 30그룹 × 4명 = 150회. Drive 사용자당 분당 325,000 단위 안에서 여유 |
| 3 마감 처리 | 0 | g × (1 `permissions.list` + m `permissions.update`) | 같은 시각 마감이 여러 액티비티면 몰린다 |
| 4 내보내기 | 0 | g × (1 `files.get` + 1 `files.export`) | export는 다운로드 단위(200) |
| 본문 확인 `read_document` | 1 (`get`) | 1 (`files.get`) | 사용자당 분당 300회 |

Docs API 쓰기 쿼터(사용자당 분당 60회)는 현재 유즈케이스가 건드리지 않는다. 쓰기 쿼터가 문제가 되는 것은 생성 후 `batchUpdate`로 문서를 개별 수정하는 기능이 추가될 때다.

## 9. 웹훅 (해당 시)

Docs API 자체에는 웹훅이 없다. 문서 변경 감지는 Drive API로 한다 → `docs/google_drive.md` 9절.

## 10. 함정과 권장 패턴

1. **인덱스는 UTF-16 코드 단위, 0부터.** Python `len(str)`과 다르다. 한글은 BMP 안이라 1글자=1단위지만 이모지 등 보조 평면 문자는 2단위다. 인덱스 계산은 `len(s.encode("utf-16-le")) // 2`로 한다. 5단계에서 이모지 포함 케이스를 에러 케이스로 남긴다.
2. **삽입하면 뒤쪽 인덱스가 밀린다.** 한 `batchUpdate` 안에서 여러 위치를 고칠 때는 뒤에서 앞으로(인덱스 내림차순) 요청을 정렬한다. 가능하면 인덱스 대신 `replaceAllText`나 이름 있는 범위(`replaceNamedRangeContent`)를 쓴다.
3. **본문 인덱스 1부터 시작.** 새 문서 본문의 첫 삽입 위치는 인덱스 1이다(0은 구조 요소). 문서 끝 삽입은 `endOfSegmentLocation`을 쓰면 인덱스 계산이 필요 없다. 5단계에서 확인.
4. **탭.** `tabId`를 생략하면 대부분의 요청이 **첫 번째 탭**에 적용된다. 예외로 `replaceAllText`, `deleteNamedRange`, `replaceNamedRangeContent`는 **모든 탭**에 적용된다. 읽을 때 `includeTabsContent`를 안 켜면 첫 탭만 보인다. 사용자가 만든 문서를 읽는 시나리오라면 항상 `includeTabsContent=true`로 읽고 `tabs[].childTabs`까지 재귀 순회한다.
5. **동시 편집.** 사용자가 문서를 열어 편집 중일 수 있다. `writeControl.requiredRevisionId`는 그사이 변경이 있으면 400으로 실패하고, `targetRevisionId`는 API를 또 한 명의 협업자로 보고 변경을 병합한다. 인덱스 기반 편집은 `requiredRevisionId` + 실패 시 재조회·재계산을 기본으로 권장한다.
6. **만들고 나서 폴더 지정은 따로.** `documents.create`는 폴더를 못 받는다. 폴더가 필요하면 Drive `files.create`(`mimeType: application/vnd.google-apps.document`, `parents` 지정)로 만들거나, 만든 뒤 Drive `files.update`(`addParents`)로 옮긴다. 이 흐름은 `google_docs/usecases.py`에 둔다.
7. **Markdown 가져오기 경로.** 긴 텍스트를 서식과 함께 넣는 경우 `batchUpdate`로 조립하는 것보다 Drive에 `text/markdown`을 올리며 Docs로 변환하는 편이 호출 수·인덱스 문제 모두 적다. 결과 서식의 차이는 5단계에서 비교한다.
8. **SDK 없이 REST.** 세 메서드뿐이라 SDK 없이 httpx로 충분하다. 예외로 둘 근거 없음.
9. **Markdown 변환 vs Docs API 비교 결과 (2026-10-03 실측).** 같은 템플릿으로 A(Markdown 업로드)는 호출 1회에 제목·굵게·목록이 서식으로 들어갔고, B(`create`+`batchUpdate`)는 호출 3회에 Markdown 기호가 평문 그대로 들어갔다. 템플릿 기반 생성은 **A를 쓴다.** Docs API는 생성 후 부분 수정(치환, 특정 위치 삽입)에만 쓴다. A에서 Markdown의 두 칸 공백 줄바꿈은 소프트 줄바꿈(U+000B)으로 변환된다.
10. **잠긴 문서는 API로도 못 고친다.** `contentRestrictions.readOnly=true`인 문서에 `batchUpdate`하면 소유자여도 403. 이 때문에 마감 처리에 잠금을 쓰지 않는다. 교수자가 웹에서 직접 잠근 문서는 `Document.locked`로 드러나므로, 서비스가 API 편집 전에 확인한다.
11. **마감 처리 패턴 (스케줄러는 서비스 레포 책임).** Google에는 "이 시각에 권한을 바꿔라"는 예약 기능이 없다(개인 계정은 `expirationTime`도 불가). Synsory가 액티비티의 due와 그룹별 문서 ID를 저장해 두고, due 시각에 `close_submissions(document_ids, keep_emails)` → 문서마다 `export_document`를 순서대로 호출한다. 내보내기는 반드시 권한을 낮춘 뒤에 한다. 유의점: ① 두 함수 모두 재실행해도 안전하다(이미 commenter면 건너뜀). ② 그 시각에 교수자 refresh token이 살아 있어야 한다. 무효면 마감 처리가 실패하므로 교수자에게 재연결 알림이 필요하다. ③ 문서별로 결과·에러를 돌려주므로 실패한 문서만 재시도한다. ④ 호출 수는 문서당 1 + 학생 수. 같은 시각에 마감되는 액티비티가 많으면 분산을 고려한다. ⑤ due는 UTC로 저장한다.

12. **학생 계정에서 확인한 공유 동작 (2026-10-04, 테스트 Google 계정으로 실측).** ① `sendNotificationEmail=false`로 공유해도 링크를 열면 "액세스 요청" 없이 **즉시 편집자로 열린다.** ② 다른 조 문서 링크는 "액세스 요청" 화면이 나온다. 그룹 간 격리는 Drive 권한만으로 충분하다. ③ 알림 없이 공유한 문서는 학생의 Drive "공유 문서함"에 **학생이 문서를 한 번 열기 전까지 보이지 않았다.** Drive 쪽 동작이라 코드로 못 바꾼다. 따라서 **서비스가 문서 링크를 직접 전달해야 한다**(학생이 Drive에서 찾을 것으로 기대하지 않는다). ④ 학생 브라우저에 Google 계정이 여럿 로그인되어 있으면 기본 계정으로 열려 "액세스 권한 필요"가 뜬다. 공유받은 계정으로 전환하면 열리고, 그 뒤로는 바로 열린다. 서비스가 보내는 링크에 `?authuser=<공유받은 이메일>`을 붙이면 이 문의를 줄일 수 있다.
13. **마감 처리 순간 열려 있는 문서의 동작 (2026-10-04 실측).** 학생이 편집 화면을 열어둔 채 `permissions.update`로 commenter가 되면, 화면은 **잠시 편집을 받아들이는 것처럼 보이다가** 곧 Google의 정정 알림이 뜨고 그 사이 입력한 내용이 **되돌려진다.** 서버가 저장을 거부한 것이다. 새로고침하면 "댓글 작성자"로 표시된다. 의미: ① 마감 뒤 입력은 서버에 남지 않으므로 바로 이어서 `files.export`해도 제출본에 섞이지 않는다. ② 학생에게는 "몇 초 동안 쓴 것이 사라지는" 경험이므로 서비스가 마감 수 분 전부터 문서 밖(Synsory 화면·알림)에서 경고하는 것이 좋다. 문서 안에 경고를 넣으려면 `batchUpdate`가 필요하고 그건 학생이 지울 수 있다.
14. **commenter 상태의 학생이 할 수 있는 것 (2026-10-04 실측).** 댓글 달기 가능, 파일 메뉴 다운로드 가능, 다른 사람에게 공유 **불가**. 즉 마감 뒤에도 학생은 자기 제출본을 보관하고 피드백 댓글을 주고받을 수 있으며, 문서를 외부로 퍼뜨리는 경로는 막힌다. 다운로드까지 막아야 하면 `files.update`의 `copyRequiresWriterPermission=true`를 추가로 검토한다(미실측). **마감 연장**: `restore_editors`로 다시 writer로 올리면 학생은 새로고침 후 바로 편집 가능(2026-10-04 실측).

## 11. 샘플 코드 (`usecases.py`의 흐름을 기준으로)

아래는 `app/services/google_docs/usecases.py`·`app/services/google_drive/usecases.py`의 실제 함수 호출 순서다. FastAPI 없이 동작하며 `access_token`만 있으면 된다. 전체 흐름은 "학기 초 1·2 → 마감 시각에 3·4"이고, 1·2는 교수자 요청으로, 3·4는 서비스 스케줄러가 실행한다.

```python
from app.services.google_docs.client import DocsClient
from app.services.google_docs import usecases as docs_uc
from app.services.google_drive.client import DriveClient
from app.services.google_drive import usecases as drive_uc

drive = DriveClient(access_token)   # 교수자 토큰. 만료됐으면 호출 전에 refresh
docs = DocsClient(access_token)

# 1. 액티비티 폴더. 강의 폴더는 교수자가 Drive 웹에서 만든 것이어도 ID만 있으면 된다.
folder = await drive_uc.create_folder(drive, "팀 프로젝트 1차", parent_folder_id=course_folder_id)

# 2. 템플릿으로 그룹 문서 생성 + 그룹원 편집 권한. 그룹·이메일 단위로 부분 실패해도 계속 진행.
results = await docs_uc.create_group_documents(
    docs, drive,
    folder_id=folder.id,
    activity_name="팀 프로젝트 1차",
    title_template="{{activity_name}} - {{team_name}}",
    body_template=(
        "# {{activity_name}}\n\n**팀:** {{team_name}}  \n**마감:** {{due}}\n\n"
        "## 1. 문제 정의\n\n## 2. 접근 방법\n\n## 3. 결과\n"
    ),
    groups=[
        docs_uc.GroupSpec("A조", ["a1@gmail.com", "a2@gmail.com"]),
        docs_uc.GroupSpec("B조", ["b1@gmail.com"]),
    ],
    due="2026-10-10 23:59",
    notify=False,          # True면 Google이 공유 알림 메일을 보낸다. Google 계정이 아닌 이메일은 True여야 초대 가능
)
for r in results:
    if r.error:                     # 문서 생성 자체가 실패한 그룹
        ...
    else:
        save(team=r.team_name, document_id=r.document.id, url=r.document.url)   # due 처리에 쓰므로 반드시 저장
        for sh in r.shares:
            if not sh.ok: ...        # 예: Google 계정 아닌 이메일 → 400 invalidSharingRequest

# 3. 마감 시각 (스케줄러). 학생 writer → commenter. 교수자(owner)·조교(keep_emails)는 유지. 재실행 안전.
closed = await docs_uc.close_submissions(
    drive, document_ids=[...], to_role="commenter", keep_emails=["ta@gmail.com"]
)
for c in closed:
    if c.error: retry_later(c.document_id)      # 예: 교수자가 문서를 지웠으면 404

# 4. 제출본 확보. 반드시 3 다음에. Turnitin 전송은 서비스 레포 책임.
for document_id in [...]:
    exported = await docs_uc.export_document(drive, document_id, fmt="docx")   # docx | pdf | txt | md | html
    send_to_turnitin(exported.filename, exported.mime_type, exported.content)

# 보조: 본문 확인 (모든 탭·표 셀 포함 평문). Document.trashed·locked도 여기서 확인.
doc = await docs_uc.read_document(docs, drive, document_id)
```

에러는 `DriveApiError`(`status`, `reason`, `message`, `is_rate_limit`)와 `DocsApiError`(`status`, `status_text`, `message`, `is_rate_limit`)로 올라온다. `is_rate_limit`이면 지수 백오프로 재시도하고, 그 외 4xx는 7절 표로 분기한다. 토큰 만료(401)는 client가 처리하지 않으므로 호출 전에 갱신한다.

## 12. 미확인 · 보류 항목

| 항목 | 확인 방법 · 시점 |
| --- | --- |
| 댓글·제안 API(Developer Preview) | **보류.** 확정된 유즈케이스에 댓글이 없다. 필요해지면 Drive `comments` API(정식)부터 검토 |
| `batchUpdate` 요청 개수·페이로드 상한, 문서 최대 크기 | **보류.** 현재 유즈케이스는 batchUpdate를 쓰지 않는다. 개별 수정 기능이 생기면 확인 |
| `drive.file`로 만든 문서를 사용자가 웹에서 다른 폴더로 옮기거나 사본을 만들 때 앱 접근이 유지되는지 | 부분 확인: 앱이 API로 옮긴 경우는 유지(2026-10-02). 교수자가 웹에서 옮기거나 **사본**을 만든 경우는 미확인. 사본은 앱이 만든 파일이 아니므로 접근 불가로 예상 |
| 스마트 칩 삽입 | 보류. 유즈케이스에 없음 |
| 2026년 중 쿼터 초과 과금 계획의 실제 시행 여부 | 핸드오프(7단계) 직전 다시 확인 |
| ~~`contentRestrictions.readOnly` 동작 여부~~ | 확인 완료(2026-10-03): 개인 계정 + `drive.file`에서 동작. 잠긴 문서 `batchUpdate`는 403 `PERMISSION_DENIED`. 7절·10절 |
| ~~`permissions.create`의 `expirationTime`~~ | 확인 완료(2026-10-03): 개인 계정 불가, 403 `cannotSetExpiration`. 3안 제외 |
| 교수자가 Drive에 가진 기존 Google Doc을 템플릿으로 쓰는 경우(Picker 필요) | 보류. 2단계 전제는 Markdown 템플릿 |
| ~~공유 대상이 Google 계정이 아닌 이메일~~ | 확인 완료(2026-10-03): 400 `invalidSharingRequest`. 단, `notify=true`로 하면 초대 메일이 가는지는 미확인(실제 메일 발송이라 보류) |
| ~~마감 비활성화 방식~~ | 결정 완료(2026-10-03): 권한 낮추기. 잠금 방식 미사용 |
| ~~권한이 commenter로 낮아진 학생 입장에서 문서 UI~~ | 확인 완료(2026-10-04): 10절 12·13·14항 |
| Markdown 변환의 표·코드 블록·이미지 서식 보존 | 제목·굵게·목록·소프트 줄바꿈은 확인. 템플릿에 표가 들어가면 확인 |
| `notify=true`로 Google 계정 아닌 이메일 초대 시 실제 동작 | 실제 메일이 발송되므로 테스트 계정 합의 후 |
| 교수자가 학생 수십 명을 한 번에 공유할 때 Drive 공유 한도(일일 공유 횟수 제한 존재 여부) | 공식 문서에 수치 없음. 7단계 전 Drive 공유 제한 문서 재확인 |
| 잠금 상태에서 `files.export` 가능 여부 | 확인 완료(2026-10-03): 가능. `uc4-export.json`은 잠금 중 캡처 |

## 출처 (2026-09-30 확인)

- Docs API Usage limits — https://developers.google.com/workspace/docs/api/limits
- documents.create — https://developers.google.com/workspace/docs/api/reference/rest/v1/documents/create
- documents.get — https://developers.google.com/workspace/docs/api/reference/rest/v1/documents/get
- documents.batchUpdate — https://developers.google.com/workspace/docs/api/reference/rest/v1/documents/batchUpdate
- Request 타입 — https://developers.google.com/workspace/docs/api/reference/rest/v1/documents/request
- 탭 작업 가이드 — https://developers.google.com/workspace/docs/api/how-tos/tabs
- Docs API scopes — https://developers.google.com/workspace/docs/api/auth
- Docs API release notes — https://developers.google.com/workspace/docs/release-notes
