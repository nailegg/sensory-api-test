# Google Drive 연동 스펙

상태: Docs 6단계와 함께 1차 마감(2026-10-03). Sheets·Slides·Forms 진행 시 새 Drive 호출을 추가한다. Google Picker 절(2.1) 추가(2026-10-04)
최종 수정: 2026-10-04 · 작성: 상현
확인 기준: 공식 문서는 2026-09-30(Drive)·2026-10-04(Picker), 실측은 2026-10-02~04 (개인 Gmail, 테스트 상태 앱)

Drive는 단독 유즈케이스보다 Docs·Sheets·Slides·Forms가 공통으로 기대는 레이어다. 여기에는 각 서비스가 쓰는 Drive 호출과 Google 공통 OAuth 제약을 모은다.

## 1. 이 서비스로 하는 일 (유즈케이스)

서비스별 유즈케이스에서 필요한 Drive 호출을 모아 적는다. Docs 유즈케이스 1~4 기준(2026-10-03 확정·실측):

| 필요한 동작 | Drive 호출 | 쓰는 서비스 |
| --- | --- | --- |
| `Document`의 소유자·생성/수정 시각·URL 채우기 | `files.get` (`fields=id,name,owners,createdTime,modifiedTime,webViewLink`) | Docs, Sheets, Slides, Forms |
| 특정 폴더에 문서 만들기 | `files.create` (`mimeType`, `parents`) 또는 생성 후 `files.update` (`addParents`) | Docs, Sheets, Slides |
| Markdown·HTML·docx를 Docs로 변환해 만들기 | `files.create` 업로드 + `mimeType: application/vnd.google-apps.document` | Docs |
| pptx를 Slides로 변환해 만들기 (Slides 템플릿 업로드) | `files.create` 업로드 + `mimeType: application/vnd.google-apps.presentation` | Slides |
| 템플릿 통째로 복사 (Slides·Sheets 유즈케이스 2) | `files.copy` (`name`, `parents`). 원본은 앱이 변환 업로드한 파일 **또는 교수자가 Picker로 고른 기존 파일**(2.1절) | Slides, Sheets, (Docs: 결정 대기) |
| 교수자가 Drive에 이미 가진 파일을 템플릿으로 쓰기 | Drive API 호출 없음. 브라우저 **Google Picker**로 파일을 고르면 그 파일에 `drive.file` 접근이 생기고, 이후 `files.copy` 등을 그대로 쓴다 (2.1절) | Docs, Slides, Sheets |
| PDF·docx·Markdown으로 내보내기 | `files.export` | Docs, Sheets, Slides |
| 목록·검색 | `files.list` (`q=`) | 공통 |
| 삭제(휴지통) | `files.update` (`trashed: true`) 또는 `files.delete` | 공통 |
| 그룹원에게 편집 권한 부여 (Docs·Slides 유즈케이스 2) | `permissions.create` (`type=user, role=writer`, `sendNotificationEmail`) | Docs, Slides |
| 마감 시 학생 권한 낮추기 (Docs·Slides 유즈케이스 3) | `permissions.list` → `permissions.update` (`role=commenter`) | Docs, Slides, 이후 Sheets |
| (미채택) 문서 잠금 | `files.update` `contentRestrictions.readOnly` — 동작하나 소유자 API 편집도 막혀 제외 | — |
| 액티비티 폴더 생성 (Docs 유즈케이스 1) | `files.create` (folder) | Docs |
| 변경 감지 | `changes.getStartPageToken` → `changes.watch` 또는 `changes.list` | 공통 |

## 2. 인증

GCP 콘솔 설정 절차, 인가·콜백·갱신 흐름, 실측 결과는 `docs/google_docs.md` 2절에 있다(Google 4종 공통, Docs에서 구축). 아래는 Google 공통 OAuth 제약 사실:

- 인가: `https://accounts.google.com/o/oauth2/v2/auth`, 토큰: `https://oauth2.googleapis.com/token`, 철회: `https://oauth2.googleapis.com/revoke`
- 리다이렉트 URI는 localhost라면 http 허용 → `http://localhost:8000/auth/google/callback` 그대로 쓸 수 있다.
- refresh token을 받으려면 `access_type=offline`. 재동의 강제는 `prompt=consent`.
- 서비스가 늘며 scope를 추가할 때는 `include_granted_scopes=true`(증분 인가)로 기존 권한을 유지한 채 추가 동의를 받는다.
- 사용자가 동의 화면에서 일부 scope를 뺄 수 있다(세분화 동의). 토큰 응답의 `scope` 필드(공백 구분)로 실제 받은 scope를 확인하고, 빠졌으면 해당 기능을 막거나 재요청한다.
- **테스트 상태 + 외부 사용자 유형 앱의 refresh token은 7일 후 만료된다.** (공식 문서로 확인됨)
- **refresh token은 Google 계정 × OAuth 클라이언트 ID당 100개까지.** 초과하면 가장 오래된 것부터 조용히 무효가 된다. `prompt=consent`로 로그인을 반복하면 매번 새 refresh token이 나오므로, token_store는 항상 최신 것 하나로 덮어쓴다.
- 6개월간 쓰지 않은 refresh token, 사용자가 시간 제한 접근을 준 뒤 만료된 경우도 무효가 된다.

### 2.1 Google Picker — 교수자가 Drive에 이미 가진 파일을 `drive.file` 앱에 넘기기

공식 문서 확인 2026-10-04 (web-picker 가이드 2026-09-03, overview 2026-09-14, desktop-mobile 가이드 2026-09-29 갱신본). 실측은 아래 "실측" 소절.

**왜 필요한가.** `drive.file`은 "앱이 만든 파일 + 사용자가 Picker(또는 앱의 선택기)로 앱에 공유한 파일"만 접근한다(공식 scope 설명: "Create new Drive files, or modify existing files, that you open with an app or that the user shares with an app while using the Google Picker API or the app's file picker"). 교수자가 Google Docs·Slides·Sheets UI에서 직접 만든 파일을 템플릿으로 쓰려면, 민감 scope(`documents`·`presentations`·`spreadsheets`, `.readonly` 포함)를 추가하는 대신 Picker로 그 파일을 고르게 하면 된다. Google 자신도 "파일 선택기를 쓰는 앱이 `drive.file`이면 충분한데 `drive`·`drive.readonly`를 요청하는 실수"를 지적하며 Picker + `drive.file`을 권장한다(Requesting Minimum Scopes 도움말). 이 레포의 scope는 그대로 `drive.file` 하나다.

**Picker가 `drive.file` 앱에 권한을 주는 조건 3가지 (+1).** 셋 다 `PickerBuilder`에 넣어야 한다.

| 설정 | 값 | 빠뜨리면 | 근거 |
| --- | --- | --- | --- |
| `setDeveloperKey(key)` | GCP **API 키**. 같은 프로젝트에서 **Google Picker API를 사용 설정**한 뒤 생성 | Picker 창에 "API developer key is invalid" | web-picker 가이드 |
| `setAppId(appId)` | **Cloud 프로젝트 번호**(숫자. 프로젝트 ID가 아님). 웹 클라이언트 ID `<번호>-xxx.apps.googleusercontent.com`의 앞 숫자와 같다 | 공식 레퍼런스: "Sets the Id of the application needing to access the user's files via the Drive API. … **required for the `drive.file` scope**". 빠뜨리면 선택 창은 뜨고 콜백도 오지만 **앱에 접근 권한이 기록되지 않아** 이후 `files.get`·`files.copy`가 404 | setAppId 레퍼런스, 커뮤니티 보고(실측은 아래) |
| `setOAuthToken(token)` | `drive.file`로 받은 access token. 여러 계정이 로그인된 브라우저에서 "어느 계정의 파일을 보여 줄지"도 이 토큰이 정한다 | "Your app must send an OAuth 2.0 access token with views that access private user data"(Drive 보기 전부 해당) | web-picker 가이드, setOAuthToken 레퍼런스 |
| (+) 브라우저의 **Google 로그인 세션** | Picker는 `docs.google.com` iframe이라 토큰과 별개로 Google 쿠키를 본다 | **실측(2026-10-04)**: 유효한 토큰을 `setOAuthToken`에 넣어도 Google에 로그인 안 된 브라우저에서는 "Sign in to your Google Account — You must sign in to access this content" 화면만 나온다. 즉 교수자가 Google에 로그인된 브라우저에서 띄워야 하고, 서버 쪽 자동화로 대신 고를 수 없다 | 실측(아래) |

- 권한의 단위는 토큰이 아니라 **(프로젝트 = appId) × 사용자 × 파일**이다. Picker에 넣은 토큰과 서버가 쓰는 토큰이 달라도(예: 프론트가 GIS로 받은 1시간짜리 토큰, 서버는 refresh token으로 갱신한 토큰) 같은 프로젝트의 클라이언트면 서버도 그 파일에 접근할 수 있어야 한다. 공식 문서에 "파일 단위 영구 권한"이라는 문장은 없다(공식 표현은 "the user shares with an app"). 토큰 refresh·서버 재시작 뒤 유지 여부는 아래 실측으로 확인한다.
- **권한이 사라지는 경우(공식 OAuth 문서)**: 사용자가 Google 계정 설정에서 앱 접근을 철회하거나, 앱이 토큰을 `revoke`하면 "All previous granted scopes for this client (and project) will be revoked"이고 refresh token도 함께 죽는다. Google DevRel 글(2025-02, "Secure Google Drive Picker: Token Best Practices")은 Picker용 브라우저 토큰을 쓰고 나서 바로 revoke하라고 권하지만, 그러면 **같은 프로젝트의 서버 refresh token까지 무효**가 된다는 보고가 있다(drive-picker-element issue #47). Synsory는 브라우저 토큰을 revoke하지 않고 1시간 만료에 맡긴다.

**보기(View) 제한 · 폴더 선택.**

- 종류별 보기: `new google.picker.DocsView(ViewId.DOCUMENTS | PRESENTATIONS | SPREADSHEETS | FOLDERS | DOCS)`. `DOCS`는 "All Google Drive document types". 셋을 한 보기에 담으려면 `DocsView(ViewId.DOCS).setMimeTypes("application/vnd.google-apps.document,application/vnd.google-apps.presentation,application/vnd.google-apps.spreadsheet")`(쉼표 구분). 선택 자체를 MIME로 막는 `PickerBuilder.setSelectableMimeTypes`도 있다.
- 폴더: `setIncludeFolders(true)`는 폴더를 **탐색용**으로 보여 주고, `setSelectFolderEnabled(true)`라야 폴더 자체를 고를 수 있다(`ViewId.FOLDERS`와 조합). 폴더를 고르면 `files.get`은 되지만 **그 안의 파일까지 접근이 생기는지는 공식 문서에 없다**(12절, 실측 대상).
- 그 밖에 `setOwnedByMe(true)`(내 소유만), `setParent(folderId)`(시작 폴더), `setEnableDrives(true)`(공유 드라이브), `setMode(GRID|LIST)`, `setQuery`, `setStarred`, `setFileIds`. `Feature.MULTISELECT_ENABLED`(여러 개), `NAV_HIDDEN`(좌측 탐색 숨김), `SUPPORT_DRIVES`, `MINE_ONLY`.
- 콜백 `data.action`은 `PICKED | CANCEL`(+ `loaded`). `data.docs[]`에 `id, name, mimeType, url, parentId, lastEditedUtc` 등. 프론트는 `id`만 Synsory 서버에 넘기면 된다.
- Deprecated ViewId: `PHOTOS, YOUTUBE, MAPS, WEBCAM, IMAGE_SEARCH, VIDEO_SEARCH, PHOTO_ALBUMS, PHOTO_UPLOAD, RECENTLY_PICKED`(Drive 밖 소스). 우리와 무관.

**GCP 콘솔 설정(한 번).**

1. API 및 서비스 > 라이브러리 > **Google Picker API 사용 설정**(Drive API와 별개).
2. 사용자 인증 정보 > API 키 생성. **키 제한 권장**: 애플리케이션 제한 = "웹사이트"에 앱 도메인(테스트는 `http://localhost:8000/*`)과 **`https://docs.google.com/*`** 둘 다. 후자를 빼면 "API developer key is invalid"(공식). API 제한 = Google Picker API(서버가 쓰는 Drive API는 이 키를 쓰지 않으므로 넣지 않아도 된다). 키는 브라우저에 노출되는 값이라 시크릿은 아니지만 `.env`(`GOOGLE_PICKER_API_KEY`)에만 둔다.
3. OAuth 클라이언트는 기존 웹 클라이언트 그대로. 프론트가 GIS로 직접 토큰을 받는다면 "승인된 JavaScript 원본"에 프론트 도메인을 추가한다.
4. `setAppId` 값 = 프로젝트 번호(콘솔 대시보드 "프로젝트 번호"). 이 레포는 `GOOGLE_PROJECT_NUMBER`가 비어 있으면 클라이언트 ID 앞 숫자를 쓴다(`config.picker_app_id`).

**앱 심사에 미치는 영향.** 없다(scope가 늘지 않는다). `drive.file`은 비민감 → "non-sensitive scope만 쓰면 앱 검증이 필수가 아니다", 동의 화면에 앱 이름·로고를 띄우려면 가벼운 **브랜드 검증**만(OAuth App Verification 도움말). Picker API 사용 설정·API 키는 심사 항목이 아니다. 반대로 Picker 없이 기존 파일을 다루려고 `documents`·`presentations`·`spreadsheets`(민감)를 넣으면 scope 심사가 생기고, `drive`·`drive.readonly`(제한)는 CASA까지 붙는다.

**모바일·웹뷰 제약.**

- 웹앱(Synsory 프론트): JS Picker(iframe). 브라우저가 Google에 로그인돼 있어야 한다(위 표 +1). 서드파티 쿠키를 막는 브라우저·시크릿 창에서의 동작은 미확인(12절).
- 데스크톱·모바일 **네이티브 앱**: "Can no longer be displayed within an embedded webview". 시스템 브라우저 **새 탭**에서 OAuth URL(`accounts.google.com/o/oauth2/v2/auth` + `prompt=consent&trigger_onepick=true`)로 띄우고, 사용자가 고르면 `redirect_uri`로 `picked_file_ids`(쉼표 구분)와 `code`가 돌아와 code를 토큰으로 바꿔 쓴다. 이 흐름은 **`drive.file`만 가능하고 다른 scope와 조합 불가**, 플랫폼별 OAuth 클라이언트 ID가 따로 필요하다(desktop-mobile 가이드, 2026-09-29). Synsory가 나중에 앱을 만들면 웹뷰에 Picker 페이지를 넣지 말고 이 흐름을 써야 한다.

**2026년 기준 대체·변경 공지.** Google Workspace 개발자 릴리스 노트(2025~2026)에 Picker 항목은 없고, Picker 문서는 2026-09에 갱신됐다(위 날짜). 대체 API 공지 없음. 변화로 볼 것은 ① 네이티브 앱의 웹뷰 금지·새 탭 OAuth 흐름(위), ② Google이 제공하는 웹 컴포넌트 `@googleworkspace/drive-picker-element`(`<drive-picker client-id app-id>` + `<drive-picker-docs-view mime-types …>`, GIS 토큰 자동 처리, 이벤트 `picker-picked|canceled|error`). 프론트가 React 등이면 이 컴포넌트가 가장 짧다. 이 레포의 테스트 페이지는 의존성 없이 `gapi.load('picker')`로 직접 띄운다.

**테스트 페이지.** `GET /google/picker`(`app/services/google_drive/picker.py`, 이식하지 않음). 서버 token_store의 토큰을 `/google/picker/config`로 브라우저에 넘겨 Picker를 띄우고, 고른 파일 ID로 바로 `GET /google/drive/file-meta/{id}`를 불러 서버 접근 여부를 보여 준다. JS 주석에 프론트엔드용 설명(GIS 토큰 대안 포함)을 달았다. 체크박스로 `setDeveloperKey`·`setAppId`를 일부러 빼고 띄워 볼 수 있다.

**실측 (2026-10-04, 상현 개인 Gmail)**

샘플: `samples/google_drive/picker-before-file-meta.json`, `picker-after-file-meta.json`, `picker-persistence.json`, `samples/google_slides/uc2-*picker*.json`.

| 확인한 것 | 결과 |
| --- | --- |
| 로그인 안 된 브라우저(앱 내장 브라우저)에서 유효 토큰으로 띄움 | "Sign in to your Google Account" 화면. 토큰만으로는 안 되고 Google 세션이 필요하다(위 표 +1) |
| Picker 전: 교수자가 웹에서 만든 Slides·Sheets·Docs `files.get`, `files.copy`(그룹 생성) | 세 종류 모두 **404 `notFound`**. 그룹 생성은 그룹마다 `error`에 404가 담기고 복사본 없음 |
| Picker에서 **내 드라이브 목록을 클릭해** Slides를 고른 뒤 `files.get` | **200**. `files.list`(앱 접근 가능 목록)에도 나타난다 |
| 같은 Slides를 템플릿으로 그룹 2개 생성 | **`files.copy` 200 → Slides `replaceAllText` 200 → 그룹원 공유 200**. 코드 변경 없음. 복사본은 앱 폴더에 교수자 소유로. 원본은 수정 안 함 |
| **소유자가 다른 사람인(공유받은) Doc**을 고름 | 접근 생김(`files.get` 200, `owners`는 그 사람). `parent_folder_id`는 null(앱이 그 폴더를 못 봄) |
| 토큰 refresh 뒤 / 서버 워커 재시작 뒤 `files.get` | 둘 다 **200**. 권한은 토큰에 묶이지 않는다 |
| 태그 치환 | 고른 덱에 `{{…}}` 태그가 없어 `replaced`가 전부 0. 태그를 넣은 뒤 재복사(원본 수정 반영) 실측은 **보류** |
| Sheets·Docs 템플릿을 Picker로 고른 뒤 | **보류**(상현이 이번에 고르지 않음). 전 단계 404는 확인 |
| `setAppId` 생략, API 키 생략 | **미실측**(페이지 체크박스로 가능) |

주의할 관찰 2가지(원인 미확인, 12절):

- `DocsView.setFileIds(id)`로 그 파일만 보여 주는 보기에서 골랐을 때는 페이지의 서버 확인이 404였고, 같은 파일을 **내 드라이브 목록에서 클릭**해 고르니 200이 됐다. 프론트에서는 목록·검색 보기로 고르게 하고, 결과를 서버 `files.get`으로 반드시 확인한다.
- 첫 시도에서 템플릿이 Picker 목록에 보이지 않다가 다시 열었을 때 보였다. 브라우저에 여러 Google 계정이 로그인돼 있으면 Picker가 보여 주는 계정(토큰 계정)과 파일을 만든 계정이 다를 수 있다. 프론트는 "서버에 연결된 계정 = Picker에 보이는 계정"을 화면에 알려 준다.

## 3. scope 표

| scope | 등급 | 판단 |
| --- | --- | --- |
| `drive.file` | 비민감 | **기본값.** 앱이 만든 파일과 사용자가 Google Picker(또는 앱의 파일 선택기)로 공유한 파일만 접근. Google도 `drive.file` + Picker 조합을 권장한다 |
| `drive.appdata` | 비민감 | 앱 설정 저장용. 현재 필요 없음 |
| `drive.metadata.readonly`, `drive.readonly`, `drive` | **제한** | 쓰지 않는다. 메타데이터 읽기 전용도 제한 등급이다 |

## 4. 엔드포인트 표

Base URL: `https://www.googleapis.com/drive/v3` (업로드는 `https://www.googleapis.com/upload/drive/v3`)

| 메서드 | 용도 | 쿼터 단위 | 비고 |
| --- | --- | --- | --- |
| `files.get` | 메타데이터 조회 | 5 | `fields`로 필요한 필드만 요청 |
| `files.list` | 목록·검색 | 100 | 비싸다. `drive.file`이면 앱이 접근 가능한 파일만 나온다 |
| `files.create` | 생성·업로드·변환 | 50 (편집으로 추정, 5단계 확인) | 5MB 이하는 multipart, 초과는 resumable |
| `files.copy` | 파일 복사 (Slides·Sheets 템플릿 → 그룹 사본) | 50 (편집으로 추정, 미확인) | `parents` 생략 시 원본의 부모를 물려받는다. `drive.file`이면 앱이 접근 가능한 원본만(앱이 만든 파일 또는 **Picker로 고른 파일**, 2.1절). 사본은 앱이 만든 파일이 된다(2026-10-04 실측: 사본을 Slides `batchUpdate`로 바로 편집 가능) |
| `files.update` | 이름·폴더 이동(`addParents`/`removeParents`)·휴지통 | 50 | |
| `files.export` | Google 문서 → 다른 형식 | 200 (다운로드) | **내보낸 결과는 10MB까지** |
| `files.delete` | 영구 삭제 | 50 (추정) | 휴지통을 거치지 않는다 |
| `permissions.create` | 공유 | 미확인 | |
| `changes.getStartPageToken` | 변경 추적 시작점 | 5 (추정) | |
| `changes.list` | 변경 폴링 | 100 (추정) | |
| `changes.watch` / `files.watch` | 푸시 채널 등록 | 미확인 | 9절 |
| `channels.stop` | 채널 중지 | 미확인 | |

**Docs 내보내기 형식 (`files.export` mimeType)**: docx, odt, rtf, pdf, `text/plain`, `text/html`, zip(HTML), epub, **`text/markdown`**

**Slides 내보내기 형식**: pptx, odp, pdf, `text/plain`. **이미지 형식 없음**(`image/png` 요청 시 400 `badRequest` "The requested conversion is not supported.", 2026-10-04 실측). 슬라이드 이미지는 Slides `pages.getThumbnail`.

**Docs로 가져오기(변환) 가능한 원본**: Word, ODT, HTML, RTF, 일반 텍스트, **Markdown**. 이미지·PDF는 OCR로 변환(`ocrLanguage`).

## 5. 요청·응답 샘플

`samples/google_drive/` (요청·응답은 우리 엔드포인트 또는 client 호출 기준, 이름·이메일 마스킹). 2026-10-03 기준:

| 시나리오 | 파일 |
| --- | --- |
| 폴더 생성 (앱 폴더 / 사용자 폴더 아래 액티비티 폴더) | `create-folder.json`, `uc1-create-activity-folder.json` |
| Markdown 업로드 → Docs 변환, 사용자 폴더에 직접 생성 | `create-from-markdown-into-user-folder.json` |
| 휴지통 이동 7건 + 목록 확인 | `move-to-trash.json` |
| 에러: 앱이 못 보는 사용자 폴더 조회, 없는 ID 휴지통 | `error-user-folder-not-visible.json`, `error-trash-not-found.json` |
| 공유·권한·내보내기 | `samples/google_docs/uc2-*`, `uc3-*`, `uc4-export.json` (Docs 유즈케이스 안에서 캡처) |

## 6. 공통 모델 매핑

`google_drive/mapper.py::document_from_drive_file(files.get 응답) → Document`. 필드 표는 `docs/google_docs.md` 6절. Drive가 책임지는 필드: `id`, `kind`(mimeType → doc/sheet/slides/form/folder/file), `url`, `owner`(표시 이름만), `created_at`, `modified_at`, `parent_folder_id`, `trashed`, `locked`. 요청 필드 마스크는 `client.DOCUMENT_META_FIELDS` 한 곳에서 관리한다. `owners(displayName)`만 요청해 이메일이 응답에 안 들어오게 한다.

## 7. 에러와 예외 케이스

| 상황 | 예상 응답 | 출처 |
| --- | --- | --- |
| 사용자별 rate limit 초과 | 403 `userRateLimitExceeded` | limits 문서 |
| 프로젝트 rate limit 초과 | 429 `rateLimitExceeded` | limits 문서 |
| 내보내기 결과 10MB 초과 | 실패 (미확인. 과제 문서는 보통 1MB 미만이라 보류) | files.export 레퍼런스 |
| `drive.file` 범위 밖 파일 접근 | **404 `notFound` 확인됨**(2026-10-02). 403이 아니다 | 실측 |

403도 rate limit일 수 있으므로, 403을 곧바로 "권한 없음"으로 처리하지 말고 `error.errors[].reason`을 보고 분기한다.

**실측 (2026-10-02~03)**

| 상황 | 응답 | 샘플 |
| --- | --- | --- |
| 오타 ID / 앱이 못 보는 파일 `files.get` | 404 `notFound` "File not found: {id}." 두 경우가 구분되지 않는다 | `error-user-folder-not-visible.json`, `error-trash-not-found.json` |
| 휴지통 파일 `files.get` | **200**. `trashed: true`만 다르다 | `samples/google_docs/read-trashed.json` |
| Google 계정 아닌 이메일 `permissions.create` (알림 끔) | 400 `invalidSharingRequest` | `samples/google_docs/uc2-share-errors.json` |
| 형식 틀린 이메일 | 400 `invalid` | 같은 파일 |
| `expirationTime` 지정 (개인 계정) | 403 `cannotSetExpiration` | `uc3-share-with-expiration-fails.json` |
| 없는 파일에 `permissions.list` | 404 `notFound`. `close_submissions`는 이를 문서별 error로 담고 계속 진행 | `uc3-close-submission.json` |
| Picker로 고르지 않은 교수자 파일을 `files.get`·`files.copy` 원본으로 | **404 `notFound` 확인**(2026-10-04). Slides·Sheets·Docs 모두 같다 | `picker-before-file-meta.json`, 각 서비스 `uc2-template-picker-before.json` |
| 같은 파일을 Picker로 고른 뒤 `files.get`·`files.copy` | **200 확인**(Slides). refresh·재시작 뒤에도 200 | `picker-after-file-meta.json`, `picker-persistence.json` |

## 8. 쿼터 · rate limit · 플랜 제약

Drive는 요청 수가 아니라 **쿼터 단위(quota unit)** 로 센다.

| 구분 | 한도 |
| --- | --- |
| 프로젝트당 / 분 | 1,000,000 단위 |
| 사용자당(프로젝트별) / 분 | 325,000 단위 |
| 프로젝트당 / 일 (무료 구간) | 400,000,000 단위. 초과분 과금 계획 있음 |
| 다운로드 트래픽 / 일 | 1TB 초과 시 과금 계획 |
| 업로드 / 사용자 / 일 | 750GB (초과 시 24시간 업로드 불가) |
| 파일 크기 | 업로드 5TB, 복사 750GB |

작업별 비용: 읽기 5, 목록 100, 다운로드 200, 편집 50, 기타 5.

- 요금: 현재 무료. 2026년 중 한도 초과분 과금을 계획 중이며 시행 90일 전 공지한다고 되어 있다.
- 테스트 규모에서는 한도에 닿을 일이 없다. `files.list`를 폴링에 쓰는 설계만 피한다(목록 1회 = 읽기 20회).
- 개인 Google 계정의 저장 용량(무료 15GB)은 테스트 파일 수준에서는 문제없다.
- Docs 유즈케이스 기준 쿼터 단위(그룹 g, 학생 m): 생성 g×(50 + m×5 추정), 마감 g×(5 + m×50 추정), 내보내기 g×(5 + 200). 30그룹 × 4명이면 전부 합쳐 1만 단위 안쪽으로 사용자당 분당 한도(325,000)의 3% 수준. `permissions.*`의 정확한 단위는 12절.

## 9. 웹훅 (해당 시)

Docs·Sheets·Slides 변경 감지는 모두 여기서 한다. 테스트는 이 서비스에서 한 번만 한다(`docs/PLAN.md`).

- 등록: `changes.watch`(사용자 Drive 전체 변경) 또는 `files.watch`(파일 하나). 요청에 채널 `id`, `type: web_hook`, `address`(받을 URL)를 넣는다.
- 받는 URL은 **HTTPS + 유효한 인증서** 필수. 자체 서명·신뢰할 수 없는 발급자·만료·호스트명 불일치 인증서는 안 된다. 로컬 테스트는 ngrok HTTPS 주소를 쓴다.
- **채널 최대 수명: `files` 1일(86,400초), `changes` 1주(604,800초).** 자동 갱신이 없으므로 만료 전에 `watch`를 다시 불러 새 채널로 교체한다.
- **알림 본문은 항상 비어 있다**(`Content-Length: 0`). 무엇이 바뀌었는지는 헤더 `X-Goog-Resource-State`(`sync`, `add`, `remove`, `update`, `trash`, `untrash`, `change`)로만 알 수 있고, 실제 내용은 `changes.list`로 다시 조회한다.
- 채널 등록 직후 `sync` 알림이 한 번 온다. 무시하고 200을 반환한다.
- 중지: `channels.stop`(채널 ID + 리소스 ID). 사용자 계정 채널은 만든 사용자만 중지할 수 있다.
- 폴링 대안: `changes.getStartPageToken`으로 시작점을 잡고 주기적으로 `changes.list(pageToken)`. 공개 URL이 필요 없어 테스트·초기 서비스에는 이쪽이 단순하다.

## 10. 함정과 권장 패턴

1. **`fields` 파라미터를 항상 지정한다.** 응답이 작아지고, 필요한 필드가 명시돼 mapper와 1:1로 맞는다.
2. **403 ≠ 권한 없음.** 7절 참고. `reason`으로 분기한다.
3. **`drive.file`의 범위.** 앱이 만든 파일은 자동으로 접근 가능. 사용자가 이미 가진 파일은 **Picker**로 고르게 해야 접근이 생긴다(2.1절: API 키 + `setAppId`(프로젝트 번호) + `drive.file` 토큰 + 로그인된 브라우저). 테스트 페이지는 `GET /google/picker`. 고른 파일은 **템플릿 원본으로만** 쓰고 앱이 수정하지 않는다. 복사본(`files.copy`)만 치환한다.
4. **웹훅보다 폴링을 먼저.** 채널 1주 만료·재등록·빈 본문 처리를 감안하면, 실시간성이 꼭 필요한 시나리오가 아니면 `changes.list` 폴링이 운영 부담이 적다.
5. **refresh token 100개 한도.** 2절. 테스트 중 로그인을 반복해도 저장소에는 최신 것 하나만 둔다.

**`drive.file`의 실제 경계 (2026-10-02 실측, `samples/google_drive/*user-folder*.json`)**

- 앱이 만들지 않은 폴더는 `files.get`이 404 `notFound`, `files.list`에도 안 나온다. "폴더가 있는데 404"는 권한 문제이지 ID 오타가 아닐 수 있다.
- 그런데 그 폴더 ID를 `files.update`의 `addParents`나 `files.create`의 `parents`에 넣는 것은 **된다**. 사용자가 소유한 폴더면 앱이 못 보는 폴더라도 그 안에 파일을 만들거나 옮길 수 있다. 옮긴 뒤에도 앱은 자기가 만든 파일을 계속 읽는다.
- 따라서 "사용자가 지정한 기존 폴더에 문서를 넣는다"는 유즈케이스는 Picker 없이 폴더 ID(URL에서 복사)만 받으면 `drive.file`로 가능하다. Picker가 필요한 것은 "기존 폴더·문서의 **내용을 읽는**" 경우뿐이다.
- 단, 잘못된 ID를 넣어도 같은 404가 나므로 사용자 입력 폴더 ID는 미리 검증할 방법이 없다. 넣기 전에 확인하려면 Picker로 고르게 해야 한다.

**휴지통 (2026-10-02 실측)**

- 휴지통에 보낸 파일도 `files.get`과 Docs `documents.get`이 200으로 정상 응답한다. "삭제됨"은 `files.get`의 `trashed` 필드로만 안다. 그래서 `DOCUMENT_META_FIELDS`에 `trashed`를 넣고 `Document.trashed`로 노출한다. 문서를 읽는 쪽은 이 값을 확인해야 한다.
- `files.list`는 기본적으로 휴지통 파일도 돌려주므로 `q="trashed = false"`를 항상 붙인다.
- 폴더를 휴지통에 넣으면 안의 파일도 같이 간다. 사용자 소유의 앱이 못 보는 폴더에 넣은 문서는 폴더가 아니라 문서 자체를 휴지통에 보내야 한다.

**편집 잠금 `contentRestrictions` (2026-10-03 실측)**

- `files.update` 본문 `{"contentRestrictions": [{"readOnly": true, "reason": "..."}]}`. 개인 계정 + `drive.file`에서 동작. `readOnly: false`로 해제.
- 응답의 `restrictingUser`에 이메일·사진 URL이 들어 있어 샘플 저장 시 마스킹한다. `DOCUMENT_META_FIELDS`에는 `contentRestrictions(readOnly,reason,restrictionTime)`만 요청해 이를 피한다.
- 잠긴 파일에 Docs `batchUpdate`는 소유자 토큰으로도 403. `files.export`는 된다. **이 때문에 마감 처리에는 쓰지 않는다**(2026-10-03 결정). 마감 처리는 `permissions.update`로 하고 순서는 **권한 낮추기 → 내보내기**.

**Markdown 내보내기 `files.export(text/markdown)` (2026-10-09 실측, studio-port TS 어댑터)**

- Markdown 변환 업로드로 만든 문서를 다시 `md`로 내보내면 제목·굵게·목록은 유지되지만 **`_`가 `\_`로 이스케이프된다**: `{{team_name}}` → `{{team\_name}}`. 줄바꿈 일부는 끝에 공백 두 칸이 붙는다.
- 내보낸 Markdown에서 태그나 원문 문자열을 찾는 로직을 만들지 않는다. 본문 확인은 Docs `documents.get` 평문(`docs/google_docs.md`)으로 한다.

**공유 `permissions` (2026-10-03 실측)**

- `permissions.create` `type=user, role=writer`는 `drive.file`로 앱이 만든 파일에 동작한다. 소유자는 `role=owner` 권한 건으로 따로 있어 편집자만 골라 바꿀 수 있다.
- 같은 이메일을 다시 공유하면 200 + 기존 permission id. 재시도에 안전하다.
- Google 계정이 아닌 이메일은 `sendNotificationEmail=false`면 400 `invalidSharingRequest`. 초대하려면 알림을 켜야 한다.
- `expirationTime`은 개인 Gmail 소유 파일에서 403 `cannotSetExpiration`. Workspace에서만 될 것으로 보이며, 서비스가 개인 계정 사용자를 받는다면 쓸 수 없다.
- `permissions.list` 응답에 이메일·표시 이름이 들어 있다. 샘플 저장 시 마스킹.

## 11. 샘플 코드 (`usecases.py`의 흐름을 기준으로)

Drive 단독 흐름은 폴더 생성·메타데이터 조회·목록·휴지통이다. 여기에 더해 **Docs·Slides가 같이 쓰는 공통 흐름**(그룹원 공유 `share_file`, 마감 `close_submissions`·`downgrade_editors`·`restore_editors`, 내보내기 `export_file`, 제목 템플릿 `render_template`)도 `google_drive/usecases.py`에 있다(2026-10-04 Docs에서 옮김. `docs_uc.close_submissions` 같은 기존 이름도 그대로 동작). `DriveClient` 메서드와 대응 API:

```python
from app.services.google_drive.client import DriveClient, DriveApiError, MIME_DOC, EXPORT_MIME
from app.services.google_drive import usecases as drive_uc

drive = DriveClient(access_token)

folder = await drive_uc.create_folder(drive, "액티비티", parent_folder_id)      # files.create (folder)
meta   = await drive_uc.get_document_meta(drive, file_id)                        # files.get → Document
files  = await drive_uc.list_app_files(drive)                                    # files.list q="trashed = false" (앱이 만든 것만 보임)
await drive_uc.move_to_trash(drive, file_id)                                     # files.update {trashed: true}

raw = await drive.create_from_content("제목", "# md", "text/markdown", MIME_DOC, folder.id)   # files.create multipart + 변환 (≤5MB)
raw = await drive.move_file(file_id, to_folder_id)                                           # files.update addParents
raw = await drive.copy_file(template_id, "발표 1차 - A조", folder.id)                          # files.copy (Slides 템플릿)
perm = await drive.share_with_user(file_id, "s@gmail.com", role="writer", notify=False)      # permissions.create
perms = await drive.list_permissions(file_id)                                                # permissions.list
await drive.update_permission_role(file_id, perm["id"], "commenter")                         # permissions.update
pdf = await drive.export_file(file_id, EXPORT_MIME["pdf"])                                   # files.export (≤10MB)

try:
    await drive.get_file("unknown")
except DriveApiError as e:
    e.status, e.reason, e.message, e.is_rate_limit   # 404 notFound / 403 userRateLimitExceeded / 429 …
```

`DriveApiError.is_rate_limit`은 429와 403 `rateLimitExceeded`·`userRateLimitExceeded`를 묶는다. 403을 "권한 없음"으로 바로 처리하지 않는 이유다.

### 11.1 studio 이식

공통 배치·형식은 `docs/STUDIO_PORTING.md`. TS 이식본은 `studio-port/`에 있고 `pnpm verify` 통과, 실측 통과(2026-10-09, 어댑터 17개 항목·흐름 7개 항목). port에는 실측된 흐름(`usecases.py`)이 쓰는 호출만 옮겼다.

1. **파일 대응**

   | synsory-api | studio |
   | --- | --- |
   | `google_drive/client.py` `DriveClient` + `mapper.py` | `packages/infrastructure/src/google-drive.ts` `createGoogleDrive(accessToken)` → `GoogleDrivePort`, `documentFromDriveFile`, `kindFromMime`, `EXPORT_MIME` |
   | `DriveApiError` | `packages/infrastructure/src/external-http.ts` `ExternalApiError extends AppError`. `code`·`status`는 Synsory 기준(`EXTERNAL_NOT_FOUND` 404 · `EXTERNAL_RATE_LIMITED` 429 · `EXTERNAL_FAILED` 502), Google 값은 `externalStatus`·`reason`·`apiStatus`(`details`에도 같은 값). Google 원문 메시지는 `externalMessage`에만 두고 응답·`details`에는 넣지 않는다. 응답 모양 불일치는 `ExternalResponseError`(AppError 아님 → 버그로 올라감) |
   | `core/models.py` `Document` | `packages/domain/src/integrations.ts` `externalDocument`(Zod). 시각은 ISO 문자열 |
   | `usecases.render_template` · `group_variables` | `packages/domain/src/integrations.ts` `renderTemplate` · `groupVariables` |
   | `usecases.share_file` · `create_group_files_from_template` · `downgrade_editors` · `close_submissions` · `restore_editors` | `packages/application/src/google-files.ts` 같은 이름(camelCase). `DriveApiError`를 잡던 자리는 `AppError`를 잡는다(application은 infrastructure를 import할 수 없음). `replace_errors` 인자는 없앴다: 호출하던 Docs·Slides가 자기 API 오류만 넘겼고, TS에서는 그것도 `AppError`라 같은 동작이다. `ShareResult.ok`는 `error === null`로 대신한다 |
   | `usecases.get_document_meta` · `list_app_files` · `create_folder` · `move_to_trash` · `export_file` | port 메서드 하나씩이라 application 함수를 두지 않는다(`getFile` · `listFiles` · `createFolder` · `trashFile` · `exportFile`) |
   | `client.set_read_only` | 이식하지 않음. 마감은 권한 낮추기로 정했다(10절 편집 잠금) |
   | `client.rename_file` · `delete_file` · `create_empty_native_file` · `get_start_page_token` · `list_changes` | 이식하지 않음. 어떤 흐름도 쓰지 않는다(`create_empty_native_file`은 Forms 실험용). 필요해지면 Python client를 보고 추가 |

2. **port 메서드** (`packages/application/src/integration-ports.ts` `GoogleDrivePort`)

   | 메서드 | Drive 호출 | Python 대응 |
   | --- | --- | --- |
   | `getFile(id)` | `files.get` | `get_file` |
   | `createFolder(name, parent?)` | `files.create` | `create_folder` |
   | `createFromContent({ name, content, source, target, parentFolderId? })` | `files.create` multipart 업로드(5MB 이하) | `create_from_content`. MIME 대신 `source` = `'markdown' \| 'docx' \| 'pptx' \| 'xlsx' \| 'csv'`, `target` = `'doc' \| 'slides' \| 'sheet'` |
   | `copyFile(id, name, parent?)` · `moveFile(id, toFolderId)` | `files.copy` · `files.update` `addParents` | 같은 이름. `removeParents`는 쓰는 흐름이 없어 뺐다(단일 부모라 `addParents`만으로 옮겨진다, 2026-10-09 실측) |
   | `listFiles(pageSize?)` | `files.list` `q=trashed = false` | usecase `list_app_files` |
   | `exportFile(id, format)` | `files.get` + `files.export` | usecase `export_file`. 파일 종류별 형식표를 어댑터가 고르고, 안 되는 형식은 `AppError UNSUPPORTED_EXPORT_FORMAT` |
   | `trashFile` | `files.update` | 같은 이름 |
   | `shareWithUser(id, email, role, { notify, message })` | `permissions.create` | `share_with_user`. `expiration_time`은 개인 계정에서 403이고 쓰는 흐름이 없어 뺐다 |
   | `shareAsResponder(id, email \| null)` | `permissions.create` `view=published` | `share_as_responder`. 알림은 항상 보내지 않는다 |
   | `listPermissions(id, { includePublishedView })` · `updatePermissionRole` · `deletePermission` | `permissions.*` | 같은 이름 |

3. **도구 매핑**: Drive 단독 도구는 없다. 그룹 파일 도구(Docs·Slides·Sheets)의 `external_refs` 항목이 `ExternalDocument` + `team_id`다(`STUDIO_PORTING.md` 7절).
4. **큐 작업**: 없음.
5. **테스트**: `tests/google_drive/test_mapper.py` 5개 → `studio-port/tests/unit/google-drive.test.ts` 첫 묶음. 요청 모양 9개·외부 오류 분류 6개를 추가했다. 가짜 HTTP는 `tests/fixtures/http.ts` `recordingFetch`. `test_usecases.py` 3개와 `tests/google_docs/test_usecases.py`의 Drive 흐름 4개(render·downgrade·restore·close)와 부분 공유 실패 1개 → `studio-port/tests/unit/google-files.test.ts`(가짜 port `tests/fixtures/fake-drive.ts`). 실측 스크립트 `studio-port/scripts/live-google-drive.ts` · `live-google-files.ts`는 이식하지 않는다.

## 12. 미확인 · 보류 항목

| 항목 | 확인 방법 · 시점 |
| --- | --- |
| `files.create`·`delete`·`permissions.create`·`changes.*`·`watch`의 정확한 쿼터 단위 | limits 문서는 분류(읽기/목록/다운로드/편집/기타)만 제공. 5단계에서 분류 기준 재확인 |
| 푸시 알림에 도메인 소유 확인이 필요한지 | 현재 가이드에는 HTTPS·유효 인증서 요건만 있고 도메인 확인 언급이 없다. 9절 테스트 때 확인 |
| `drive.file`로 `changes.list`를 부를 때 앱이 접근 가능한 파일 변경만 오는지 | 보류. Docs 유즈케이스에 변경 감지가 없다. 필요한 서비스에서 확인 |
| ~~`drive.file` 범위 밖 파일 접근 시 에러 코드~~ | 확인 완료: 404 `notFound` (2026-10-02) |
| Markdown → Docs 변환의 서식 보존 | 제목·굵게·목록·소프트 줄바꿈 확인(2026-10-03). 표·코드 블록·이미지는 미확인. `batchUpdate` 방식보다 우월함은 확인 |
| ~~테스트 상태 앱의 테스트 사용자 수 상한~~ | 100명 (콘솔 안내, 2026-10-02) |
| `permissions.create`·`update`의 정확한 쿼터 단위 | 8절 계산은 "기타 5 / 편집 50"으로 추정. 7단계 전 limits 문서 재확인 |
| 하루 공유 횟수 제한(수강생 수백 명 일괄 공유 시) | 공식 수치 없음. 대규모 액티비티 전 확인 |
| 5MB 초과 템플릿 업로드(resumable) | 미구현. 템플릿은 텍스트라 필요성 낮음 |
| 과금 계획의 실제 시행 여부 | 핸드오프 직전 |
| ~~Picker로 고른 파일의 접근이 토큰 refresh·서버 재시작 뒤에도 유지되는지~~ | 확인(2026-10-04): 둘 다 유지. **며칠 뒤 장기 유지**는 핸드오프 전 같은 ID로 재확인 |
| `setFileIds` 보기에서 고르면 권한이 기록되지 않는 듯한 관찰(1회) | 2.1절. 재현되면 공식 이슈 트래커 확인. 프론트는 목록 보기로 고르게 한다 |
| Picker 후 Sheets·Docs 템플릿 복사·치환, 원본에 태그 넣고 재복사 시 최신 내용 반영 | 보류(2026-10-04 상현). 코드는 준비됨. 다음 실측 때 `uc2-*-picker.json` 추가 |
| Picker로 **폴더**를 고르면 그 안의 파일까지 접근이 생기는지 | 공식 문서 없음. 폴더 템플릿 유즈케이스가 생기면 실측 |
| 서드파티 쿠키 차단 브라우저·시크릿 창에서 Picker 동작 | 로그인 세션 필요는 확인(2.1절). 쿠키 차단 설정은 미실측 |
| 교수자가 **소유하지 않은**(공유받은) 파일을 Picker로 고를 때 | `files.get`은 됨(2026-10-04). `files.copy`는 미실측 |
| `setAppId`·API 키를 뺐을 때 실제 응답 | 테스트 페이지 체크박스로 확인 가능. 미실측 |

## 출처 (2026-09-30 확인)

- Drive API Usage limits — https://developers.google.com/workspace/drive/api/guides/limits
- files.export — https://developers.google.com/workspace/drive/api/reference/rest/v3/files/export
- 내보내기 형식 — https://developers.google.com/workspace/drive/api/guides/ref-export-formats
- 업로드·변환 — https://developers.google.com/workspace/drive/api/guides/manage-uploads
- 푸시 알림 — https://developers.google.com/workspace/drive/api/guides/push
- Drive scopes — https://developers.google.com/workspace/drive/api/guides/api-specific-auth
- OAuth 2.0 개요(토큰 만료) — https://developers.google.com/identity/protocols/oauth2
- 웹 서버 앱 OAuth — https://developers.google.com/identity/protocols/oauth2/web-server

Google Picker (2026-10-04 확인):

- Picker 개요(웹 vs 데스크톱·모바일, 웹뷰 금지) — https://developers.google.com/workspace/drive/picker/guides/overview
- 웹앱 통합 가이드(Picker API 사용 설정, API 키 제한, appId) — https://developers.google.com/workspace/drive/picker/guides/web-picker
- 코드 샘플 — https://developers.google.com/workspace/drive/picker/guides/sample
- PickerBuilder.setAppId("required for the drive.file scope") — https://developers.google.com/workspace/drive/picker/reference/picker.pickerbuilder.setappid
- PickerBuilder.setOAuthToken — https://developers.google.com/workspace/drive/picker/reference/picker.pickerbuilder.setoauthtoken
- DocsView(setMimeTypes·setIncludeFolders·setSelectFolderEnabled) — https://developers.google.com/workspace/drive/picker/reference/picker.docsview
- ViewId — https://developers.google.com/workspace/drive/picker/reference/picker.viewid
- 데스크톱·모바일 앱(새 탭 OAuth 흐름, drive.file 전용) — https://developers.google.com/workspace/drive/picker/guides/desktop-mobile-picker
- 웹 컴포넌트 drive-picker-element — https://developers.google.com/workspace/drive/picker/guides/web-component
- drive.file scope 설명(Picker 언급) — https://developers.google.com/workspace/drive/api/guides/api-specific-auth
- 최소 scope 요청(Picker + drive.file 권장) — https://support.google.com/cloud/answer/13807380
- OAuth 앱 검증(비민감 scope는 검증 비필수, 브랜드 검증) — https://support.google.com/cloud/answer/13463073
- (비공식, 참고) Google DevRel: Picker 토큰 관리 — https://dev.to/googleworkspace/secure-google-drive-picker-token-best-practices-43al
- (비공식, 참고) revoke 시 다른 scope까지 철회 — https://github.com/googleworkspace/drive-picker-element/issues/47
