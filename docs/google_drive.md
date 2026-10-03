# Google Drive 연동 스펙

상태: Docs 6단계와 함께 1차 마감(2026-10-03). Sheets·Slides·Forms 진행 시 새 Drive 호출을 추가한다
최종 수정: 2026-10-03 · 작성: 상현
확인 기준: 공식 문서는 2026-09-30, 실측은 2026-10-02~03 (개인 Gmail, 테스트 상태 앱)

Drive는 단독 유즈케이스보다 Docs·Sheets·Slides·Forms가 공통으로 기대는 레이어다. 여기에는 각 서비스가 쓰는 Drive 호출과 Google 공통 OAuth 제약을 모은다.

## 1. 이 서비스로 하는 일 (유즈케이스)

서비스별 유즈케이스에서 필요한 Drive 호출을 모아 적는다. Docs 유즈케이스 1~4 기준(2026-10-03 확정·실측):

| 필요한 동작 | Drive 호출 | 쓰는 서비스 |
| --- | --- | --- |
| `Document`의 소유자·생성/수정 시각·URL 채우기 | `files.get` (`fields=id,name,owners,createdTime,modifiedTime,webViewLink`) | Docs, Sheets, Slides, Forms |
| 특정 폴더에 문서 만들기 | `files.create` (`mimeType`, `parents`) 또는 생성 후 `files.update` (`addParents`) | Docs, Sheets, Slides |
| Markdown·HTML·docx를 Docs로 변환해 만들기 | `files.create` 업로드 + `mimeType: application/vnd.google-apps.document` | Docs |
| pptx를 Slides로 변환해 만들기 (Slides 템플릿 업로드) | `files.create` 업로드 + `mimeType: application/vnd.google-apps.presentation` | Slides |
| 템플릿 통째로 복사 (Slides 유즈케이스 2) | `files.copy` (`name`, `parents`) | Slides |
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
| `files.copy` | 파일 복사 (Slides 템플릿 → 그룹 사본) | 50 (편집으로 추정, 미확인) | `parents` 생략 시 원본의 부모를 물려받는다. `drive.file`이면 앱이 접근 가능한 원본만. 사본은 앱이 만든 파일이 된다(2026-10-04 실측: 사본을 Slides `batchUpdate`로 바로 편집 가능) |
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
3. **`drive.file`의 범위.** 앱이 만든 파일은 자동으로 접근 가능. 사용자가 이미 가진 파일은 Picker로 고르게 해야 접근이 생긴다. Picker는 브라우저 JS 컴포넌트라 FastAPI 테스트 프로젝트에서는 간단한 HTML 페이지로 시험해야 한다(필요 시 5단계).
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

## 출처 (2026-09-30 확인)

- Drive API Usage limits — https://developers.google.com/workspace/drive/api/guides/limits
- files.export — https://developers.google.com/workspace/drive/api/reference/rest/v3/files/export
- 내보내기 형식 — https://developers.google.com/workspace/drive/api/guides/ref-export-formats
- 업로드·변환 — https://developers.google.com/workspace/drive/api/guides/manage-uploads
- 푸시 알림 — https://developers.google.com/workspace/drive/api/guides/push
- Drive scopes — https://developers.google.com/workspace/drive/api/guides/api-specific-auth
- OAuth 2.0 개요(토큰 만료) — https://developers.google.com/identity/protocols/oauth2
- 웹 서버 앱 OAuth — https://developers.google.com/identity/protocols/oauth2/web-server
