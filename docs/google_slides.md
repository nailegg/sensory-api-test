# Google Slides 연동 스펙

상태: 6단계(스펙 문서화) 완료 · 7단계(핸드오프) 대기
최종 수정: 2026-10-04 · 작성: 상현
확인 기준: 공식 문서 2026-10-04, 실측 2026-10-04 (개인 Gmail 계정, 테스트 상태 OAuth 앱, Docs와 같은 GCP 프로젝트)

옮기는 파일: `app/services/google_slides/{client,mapper,scopes,usecases}.py`와 이 문서. 유즈케이스 2 공유·3·4는 `app/services/google_drive/usecases.py`의 공통 함수를 쓰므로 그 파일도 함께 옮긴다(Docs와 공유). Drive 호출(폴더 지정, 템플릿 복사 `files.copy`, pptx 변환 업로드, 메타데이터, 공유·권한, 내보내기, 변경 감지)은 `app/services/google_drive/`와 `docs/google_drive.md`에 두고 이 문서는 Slides API(`slides.googleapis.com/v1`)만 다룬다.

---

## 1단계 요약: 할 수 있는 일 · 못 하는 일 · 눈에 띄는 제약

2단계에서 유즈케이스를 고를 때 본 한 장이다(1단계 기록으로 남긴다). 확정된 유즈케이스는 1절, 실측 결과는 5·7·10절.

**리소스.** 프레젠테이션(`presentationId`, Drive 파일 ID와 같음) 안에 페이지가 여러 장이고, 페이지 종류는 슬라이드·마스터·레이아웃·노트·노트 마스터 다섯 가지다. 페이지 위에 페이지 요소(도형, 이미지, 비디오, 선, 표, Sheets 차트, 그룹, 워드아트)가 놓이고, 텍스트는 도형이나 표 셀 안에 들어 있다. **페이지와 요소마다 `objectId`**(5~50자, 프레젠테이션 안에서 유일)가 있고 모든 편집은 이 ID로 대상을 지정한다. Docs처럼 문서 전체를 문자 인덱스로 세지 않는다. 도형 안의 텍스트에만 UTF-16 인덱스(0 기반)를 쓴다. 위치·크기 단위는 EMU 또는 PT(1pt = 12,700 EMU).

**할 수 있는 일**

| 분류 | 내용 | 메서드 |
| --- | --- | --- |
| 생성 | 빈 프레젠테이션 생성(제목·페이지 크기·로케일). 폴더 지정은 불가 → Drive로 | `presentations.create` 또는 Drive `files.create`(mimeType 지정) |
| 템플릿 | 기존 프레젠테이션 통째로 복사. pptx·odp를 올리면서 Slides로 변환 | Drive `files.copy` · Drive `files.create`(변환) |
| 슬라이드 | 미리 정의된 레이아웃 11종(제목, 제목+본문, 두 열, 섹션 헤더, 빈 슬라이드 등) 또는 템플릿의 레이아웃 ID로 슬라이드 추가, 복제, 순서 변경, 삭제, 발표에서 건너뛰기 | `batchUpdate`(`createSlide`, `duplicateObject`, `updateSlidesPosition`, `deleteObject`, `updateSlideProperties`) |
| 텍스트 | 도형·표 셀에 텍스트 삽입·삭제, **프레젠테이션 전체에서 문자열 치환**(`{{team_name}}` 같은 태그, 대소문자·정규식 옵션, 특정 슬라이드로 한정 가능), 글자·문단 서식, 글머리 기호 | `batchUpdate`(`insertText`, `deleteText`, `replaceAllText`, `updateTextStyle`, `updateParagraphStyle`, `createParagraphBullets`) |
| 도형·배치 | 도형(텍스트 상자, 사각형 등) 추가, 위치·크기·회전, 채우기·윤곽선, 겹침 순서, 대체 텍스트, 그룹 | `batchUpdate`(`createShape`, `updatePageElementTransform`, `updateShapeProperties`, `updatePageElementsZOrder`, `updatePageElementAltText`, `groupObjects`) |
| 이미지 | 공개 URL의 이미지 삽입, 기존 이미지 교체, **태그 텍스트가 든 도형을 이미지로 일괄 교체**, 슬라이드 배경 이미지 | `batchUpdate`(`createImage`, `replaceImage`, `replaceAllShapesWithImage`, `updatePageProperties`) |
| 표 | 표 생성, 행·열 삽입(요청당 20개까지)·삭제, 셀 병합, 셀·테두리 서식 | `batchUpdate`(`createTable`, `insertTableRows`, `insertTableColumns`, `mergeTableCells`, `updateTableCellProperties` …) |
| 비디오·차트·선 | YouTube·Drive 비디오 삽입, Sheets 차트 삽입(연결/이미지)·새로고침, 선·연결선 | `batchUpdate`(`createVideo`, `createSheetsChart`, `refreshSheetsChart`, `createLine` …) |
| 발표자 노트 | 슬라이드마다 노트 페이지의 `speakerNotesObjectId` 도형에 텍스트 읽기·쓰기 | `presentations.get` + `batchUpdate`(`insertText`) |
| 읽기 | 프레젠테이션 전체 구조(모든 페이지·요소·텍스트) 또는 페이지 하나 | `presentations.get` · `presentations.pages.get` |
| 썸네일 | 페이지 하나를 PNG로 렌더링한 URL(폭 200·800·1600px) | `presentations.pages.getThumbnail` |
| 내보내기 | pptx · odp · pdf · txt (10MB 상한) | Drive `files.export` |
| 댓글 | 댓글 읽기·달기·답글·수정·삭제. 2026-09-30 GA | `presentations.get`(`commentsViewMode`) · `batchUpdate`(`insertComment` …) |
| 동시 편집 보호 | `requiredRevisionId`로 "그사이 아무도 안 고쳤을 때만" 적용 | `batchUpdate` `writeControl` |

**못 하는 일 (또는 다른 API로 해야 하는 일)**

- 생성 시 폴더 지정. Drive `files.create`(`mimeType: application/vnd.google-apps.presentation`, `parents`)로 만들거나 만든 뒤 `files.update(addParents)`. Docs·Sheets와 같다.
- **슬라이드를 이미지 파일로 내보내기.** Drive `files.export`에 Slides용 jpeg·png·svg가 없다(Drawings만 있음). 이미지가 필요하면 슬라이드마다 `getThumbnail`을 부른다. 이건 "비싼 읽기"로 따로 센다(사용자당 분당 60).
- **이미지 바이트 업로드.** `createImage`·`replaceAllShapesWithImage`는 **공개 접근 가능한 URL**만 받는다(URL 2KB 이하, 파일 50MB 이하, 25메가픽셀 이하, PNG·JPEG·GIF). Synsory가 이미지를 넣으려면 공개 URL로 서빙해야 한다. 삽입 시점에 한 번 가져와 복사본을 저장하므로 그 뒤 URL은 없어져도 된다.
- 자동 맞춤(autofit) 켜기. 텍스트 길이에 영향을 주는 요청(`insertText`, `replaceAllText` 등)이 들어가면 그 도형의 autofit이 **`NONE`으로 자동 해제**된다. 긴 치환 텍스트는 도형 밖으로 넘친다. 10절 3항.
- 레이아웃·마스터 신규 생성, 슬라이드 전환·애니메이션, 발표 모드 제어. Request 목록에 없다.
- 노트 페이지는 발표자 노트 텍스트 외에는 읽기 전용. 노트 마스터도 읽기 전용.
- 웹훅 없음. 변경 감지는 Drive `changes.watch`/`changes.list`뿐이고 "어느 슬라이드가 바뀌었는지"는 알 수 없다.
- 교수자가 Drive에 이미 가진 덱을 템플릿으로 쓰는 것은 `drive.file`만으로는 불가 → **Google Picker**로 고르게 하면 된다(민감 scope 불필요, `docs/google_drive.md` 2.1절). `files.copy`는 앱이 접근 가능한 원본(앱이 만든 것 + Picker로 고른 것)만 복사한다.
- Sheets 차트를 **연결 상태**로 넣으려면 `spreadsheets`(또는 `spreadsheets.readonly`, `drive`, `drive.readonly`) scope가 추가로 필요하다. `drive.file`만으로는 안 된다(민감 scope → 재동의·심사 수준 상승).

**눈에 띄는 제약**

| 항목 | 값 | 비고 |
| --- | --- | --- |
| 읽기 쿼터 | 프로젝트당 분당 3,000 · **사용자당 분당 600** | Docs(300)의 2배, Sheets(60)의 10배 |
| 비싼 읽기 쿼터(`getThumbnail`) | 프로젝트당 분당 300 · **사용자당 분당 60** | 덱 전체 썸네일 = 슬라이드 수만큼 호출 |
| 쓰기 쿼터 | 프로젝트당 분당 600 · **사용자당 분당 60** | `batchUpdate` 1회 = 1회(안의 요청 수 무관). Docs·Sheets와 같다 |
| `batchUpdate` 요청 수·페이로드 상한 | 공식 수치 없음 | 표 행·열 삽입만 요청당 20개 상한 |
| 썸네일 URL 수명 | **기본 30분.** 요청자 계정에 묶이고, 공유 설정이 바뀌면 접근이 끊길 수 있다 | Synsory 화면에 쓰려면 서버가 받아서 저장한다 |
| 이미지 삽입 | 공개 URL, 2KB 이하 URL, 50MB·25MP 이하, PNG·JPEG·GIF | 바이트 업로드 불가 |
| 내보내기 | pptx · odp · pdf · txt, **10MB** | 이미지 많은 덱은 pdf가 10MB를 넘을 수 있다(실측 필요) |
| 요금 | 무료. 단 "쿼터 초과분 2026년 중 과금 계획" 문구 있음 | Docs·Drive·Sheets와 같은 문구 |
| scope | `drive.file`로 `create`·`get`·`batchUpdate`·`pages.get`·`getThumbnail` **모두 호출 가능** | `presentations`·`presentations.readonly`는 민감 등급. 앱이 만든 파일만 다루면 불필요. 예외는 Sheets 차트 연결 |
| 동시 편집 | `batchUpdate`는 원자적이고 `writeControl.requiredRevisionId`로 낙관적 잠금 가능 | Docs와 같다(Sheets에는 없음). `revisionId`는 24시간만 유효 |
| 객체 ID 안정성 | 사용자가 UI에서 편집하면 ID가 바뀔 수 있다 | 템플릿 치환은 ID 대신 **텍스트 태그**로 찾는 것이 공식 권장 |

**Synsory 관점에서 유즈케이스 후보 (2단계 참고용, 확정 아님)**

- 그룹별 발표 자료를 템플릿에서 만들고 그룹원에게 편집 권한을 준다. Docs 유즈케이스 2와 같은 구조. 템플릿은 ① Synsory가 보관하는 pptx를 Drive 변환 업로드(1회, 폴더까지 지정) 또는 ② 앱이 만든 원본 Slides 한 벌을 `files.copy`. 둘 다 그다음 `replaceAllText` 1회로 `{{team_name}}` 등을 치환한다.
- 마감 시 편집 권한 낮추기 + pdf/pptx 내보내기. Docs 유즈케이스 3·4를 그대로 재사용한다(Drive 호출뿐이라 Slides 코드가 필요 없다).
- Synsory 화면에 발표 자료 미리보기(첫 슬라이드 또는 전 슬라이드 썸네일). `getThumbnail` → 30분 URL이므로 서버가 내려받아 저장. 덱당 슬라이드 수만큼 비싼 읽기.
- 발표 자료의 텍스트·발표자 노트를 추출해 피드백·표절 검사에 보낸다. `presentations.get` 한 번으로 모든 슬라이드·표 셀·노트 텍스트가 온다(또는 `files.export` txt).
- 교수자가 가진 기존 덱을 템플릿으로 쓰는 것은 Picker 필요. Docs와 동일한 보류 항목.

---

## 1. 이 서비스로 하는 일 (유즈케이스)

2026-10-04 상현 확정: **Docs와 같은 유즈케이스 4개**를 Slides에 적용한다. 전제도 Docs와 같다(OAuth 연결은 교수자, 파일은 교수자 소유, 학생은 Drive 공유로 편집).

| # | 유즈케이스 | 호출 순서 | usecases 함수 |
| --- | --- | --- | --- |
| 1 | 특정 액티비티에 해당하는 폴더를 만든다 | Drive `files.create` (folder) | `google_drive.usecases.create_folder` |
| 2 | 교수자가 템플릿(태그가 든 발표 자료 + 팀명으로 포맷되는 파일명)으로 폴더 안에 그룹마다 발표 자료를 만들고 그룹원에게 편집 권한을 준다 | 액티비티당 1회: Drive `files.create` (pptx 업로드 + Slides 변환, `parents`=액티비티 폴더) → 그룹마다: Drive `files.copy` (`name`, `parents`) → Slides `batchUpdate` (`replaceAllText` × 태그 수, 1회) → 그룹원마다 Drive `permissions.create` (`role=writer`) | `upload_template` → `create_group_presentations` |
| 3 | 마감(due) 시점에 편집을 비활성화한다 | Docs와 동일: 파일마다 Drive `permissions.list` → 학생 writer마다 `permissions.update` `role=commenter` | `close_submissions` (Docs와 같은 함수, `google_drive.usecases`) |
| 4 | 같은 시점에 파일로 내보내 Turnitin 등 다른 API로 보낸다 | Drive `files.export` (pptx · pdf · txt · odp, 10MB 상한) | `export_presentation` |

**유즈케이스별 메모**

- 1·3: Drive 호출뿐이라 Slides 코드가 없다. Docs에 있던 공유·권한 낮추기·되돌리기·내보내기 함수를 `google_drive/usecases.py`로 옮겨 Docs·Slides가 같은 함수를 쓴다(2026-10-04). Docs 쪽 이름(`docs_uc.close_submissions` 등)은 그대로 동작한다.
- 2: 템플릿은 Docs의 "Synsory가 보관하는 Markdown"에 대응해 **Synsory가 보관하는 pptx 파일**로 가정한다. Docs와 달리 그룹마다 변환 업로드하지 않고 **액티비티당 한 번만 Slides로 변환 업로드한 뒤 그룹마다 `files.copy`** 한다. 이유: ① 태그 치환을 Slides `replaceAllText`로 해야 하므로(pptx 바이트 안의 문자열을 직접 바꾸는 건 XML 런 분할 때문에 불안정) 어차피 Slides 파일이 먼저 있어야 한다. ② 업로드 바이트를 그룹 수만큼 보내지 않는다. 변환 업로드된 템플릿은 앱이 만든 파일이라 `drive.file`로 복사할 수 있다.
- 2: 태그는 Docs와 같은 이름(`{{team_name}}`, `{{activity_name}}`, `{{due}}`)이지만 **공백 없이 정확히** 써야 한다(`replaceAllText`는 문자열 일치. Docs의 `render_template`처럼 `{{ team_name }}`을 허용하지 않는다). 파일명은 Docs와 같은 `title_template`을 `render_template`로 만든다. 응답의 `replaced`(태그별 치환 횟수)가 0이면 템플릿에 태그가 없거나 서식이 갈라진 것이다.
- 2: 실측(2026-10-04)으로 확인한 템플릿 동작: pptx 변환 뒤 플레이스홀더(제목·부제·본문) 타입이 보존된다. `replaceAllText` 한 번이 슬라이드 본문·표 셀·**발표자 노트**까지 모두 치환한다. 서식이 갈린 태그도 치환된다. **긴 팀명은 넘친다**(치환된 도형만 autofit이 `NONE`이 됨). 10절 3·4항.
- 2: 복사는 됐는데 치환이 실패하면 결과에 `document`와 `error`가 함께 담기고 공유는 하지 않는다(복사본은 폴더에 남는다). 실측: `uc2-replace-fails-api-disabled.json`.
- 2: **템플릿은 두 방식 모두 지원한다(2026-10-04).** ① Synsory가 보관하는 pptx를 변환 업로드(`upload_template`). ② 교수자가 **Google Picker**로 Drive의 기존 덱을 고르고 그 ID를 `template_presentation_id`로 넘긴다. 둘 다 같은 `create_group_presentations`(실체는 `google_drive.usecases.create_group_files_from_template`, Sheets와 공유)가 `files.copy` → `replaceAllText` → 공유를 한다. **원본은 수정하지 않고 복사본만 치환한다.** Picker 조건·실측은 `docs/google_drive.md` 2.1절, 이 문서 7절·10절 16항. **실측(2026-10-04)**: Picker 전 404 → Picker 후 복사·치환·공유 성공. 태그 넣은 원본의 재복사는 보류.
- 4: Slides는 docx·md·html 대신 **pptx · pdf · txt · odp**. 이미지 형식은 없다.
- scope: 네 유즈케이스 모두 `drive.file` 하나. `services/google_slides/scopes.py`는 빈 dict.
- 1단계 후보 중 썸네일 미리보기, 텍스트·노트 추출 유즈케이스는 채택하지 않았다. 다만 본문 확인용 배관 `read_presentation`(모든 슬라이드·표·발표자 노트 평문)은 Docs의 `read_document`처럼 둔다.

## 2. 인증

Google 4종이 공유하는 OAuth 흐름이다. 콘솔 설정·인가·갱신 절차는 `docs/google_docs.md` 2절, 공통 제약은 `docs/google_drive.md` 2절. Slides에서 추가로 할 일:

- GCP 콘솔 "API 및 서비스 → 라이브러리"에서 **Google Slides API**를 사용 설정한다(2026-10-04 수행). 빠뜨리면 Slides 호출마다 403 `PERMISSION_DENIED`, `details[].reason=SERVICE_DISABLED`, 메시지 "Google Slides API has not been used in project … before or it is disabled"(실측 `uc2-replace-fails-api-disabled.json`). Drive 호출(변환 업로드·복사)은 그 상태에서도 되므로, 유즈케이스 2가 "복사는 됐는데 치환만 실패"로 나타난다. 사용 설정 직후 바로 동작했다.
- scope 추가가 없어 **재동의가 필요 없었다**(기존 토큰 그대로 사용, 2026-10-04 확인). `presentations`·`presentations.readonly`(기존 덱 접근) 또는 `spreadsheets.readonly`(연결된 Sheets 차트)를 추가하게 되면 사용자가 재동의해야 한다(`include_granted_scopes=true`로 증분 인가).
- 사용자 모델은 Docs와 같다: OAuth 연결은 교수자, 학생은 Drive 공유로 접근.
- 테스트 서버의 템플릿 업로드 엔드포인트(`/google/slides/upload-template`)는 multipart 파일 업로드라 `python-multipart` 패키지가 필요하다. 라우터 전용이라 서비스 레포로 옮기는 파일에는 영향 없다.

## 3. scope 표

공식 scope 문서(2026-10-04 확인) 기준. `presentations.create` · `get` · `batchUpdate` · `pages.get` · `pages.getThumbnail` 레퍼런스 모두 `drive.file`을 허용 scope로 나열한다.

| scope | 등급 | 가능한 범위 | 판단 |
| --- | --- | --- | --- |
| `drive.file` | 비민감 (공식 문서가 "권장") | 앱이 만든 파일, 사용자가 Picker로 고른 파일만 | **기본값.** `services/google_slides/scopes.py`는 빈 dict로 시작하고 인가는 `google_drive/scopes.py`의 `drive.file`로 한다(Docs·Sheets와 동일) |
| `presentations.readonly` | 민감 | 사용자의 모든 프레젠테이션 읽기 | 교수자의 기존 덱을 Picker 없이 읽어야 할 때만 |
| `presentations` | 민감 | 사용자의 모든 프레젠테이션 읽기·쓰기 | 기존 덱을 Picker 없이 편집·복사해야 할 때만 |
| `spreadsheets.readonly` / `spreadsheets` | 민감 | Sheets 차트를 **연결 상태**로 삽입(`createSheetsChart` LINKED) | 차트 유즈케이스가 생길 때만. `drive.file`은 이 요청의 허용 목록에 없다 |
| `drive.readonly` / `drive` | 제한 | Drive 전체 | 쓰지 않는다. CASA 보안 평가 대상 |

`drive.file`의 경계(앱이 만든 파일만 읽기, 사용자 폴더 안에 생성은 가능)는 `docs/google_drive.md` 10절 실측과 같을 것으로 보고, Slides에서 다시 확인하지 않는다. 다를 경우만 12절에 적는다. Drive `files.copy`는 `drive.file`에서 **앱이 접근 가능한 원본**만 복사할 수 있으므로, 템플릿 원본은 앱이 만든 파일이어야 한다.

## 4. 엔드포인트 표

Base URL: `https://slides.googleapis.com/v1`. Discovery: `https://slides.googleapis.com/$discovery/rest?version=v1`. 메서드는 다섯 개뿐이다.

| 메서드 | 경로 | 용도 | 쿼터 | 비고 |
| --- | --- | --- | --- | --- |
| `presentations.create` | `POST /presentations` | 빈 프레젠테이션 생성 | 쓰기 | 본문에서 `title`, `pageSize`, `locale`, `presentationId`만 반영. **슬라이드 등 다른 내용은 무시, 폴더 지정 불가** → Drive `files.create`(`mimeType: application/vnd.google-apps.presentation`, `parents`) 또는 생성 후 `files.update`(`addParents`) |
| `presentations.get` | `GET /presentations/{id}` | 전체 구조·내용 읽기 | 읽기 | 마스터·레이아웃·모든 슬라이드·노트·요소·텍스트가 한 응답에 온다. `fields` 마스크로 줄일 수 있다(예: `slides.objectId,slides.pageElements.shape.text`). `commentsViewMode`(기본 `COMMENTS_VIEW_MODE_OMITTED`) |
| `presentations.batchUpdate` | `POST /presentations/{id}:batchUpdate` | **모든 변경** | 쓰기 | 요청 배열을 **원자적으로** 적용. 하나라도 실패면 전체 거부. `replies[]`는 요청과 1:1(대부분 비어 있고 생성·치환 요청만 값이 있다). `writeControl.requiredRevisionId`로 낙관적 잠금 |
| `presentations.pages.get` | `GET /presentations/{id}/pages/{pageObjectId}` | 페이지 하나 읽기 | 읽기 | 슬라이드·레이아웃·마스터·노트 페이지 모두 가능 |
| `presentations.pages.getThumbnail` | `GET /presentations/{id}/pages/{pageObjectId}/thumbnail` | 페이지 렌더링 이미지 URL | **비싼 읽기** | `thumbnailProperties.mimeType=PNG`(유일), `thumbnailProperties.thumbnailSize=LARGE(1600px)·MEDIUM(800px)·SMALL(200px)`(생략 시 서버 기본). 응답 `contentUrl`·`width`·`height`. URL 수명 기본 30분 |

**`batchUpdate` 요청 종류** (Request union 전체, 2026-10-04 기준)

| 분류 | 요청 |
| --- | --- |
| 슬라이드·페이지 | `createSlide`, `duplicateObject`, `updateSlidesPosition`, `deleteObject`, `updateSlideProperties`, `updatePageProperties` |
| 도형·요소 공통 | `createShape`, `updateShapeProperties`, `updatePageElementTransform`, `updatePageElementsZOrder`, `updatePageElementAltText`, `groupObjects`, `ungroupObjects` |
| 텍스트 | `insertText`, `deleteText`, `replaceAllText`, `updateTextStyle`, `updateParagraphStyle`, `createParagraphBullets`, `deleteParagraphBullets` |
| 표 | `createTable`, `insertTableRows`, `insertTableColumns`, `deleteTableRow`, `deleteTableColumn`, `updateTableCellProperties`, `updateTableBorderProperties`, `updateTableColumnProperties`, `updateTableRowProperties`, `mergeTableCells`, `unmergeTableCells` |
| 이미지·비디오·차트 | `createImage`, `updateImageProperties`, `replaceImage`, `replaceAllShapesWithImage`, `createVideo`, `updateVideoProperties`, `createSheetsChart`, `refreshSheetsChart`, `replaceAllShapesWithSheetsChart` |
| 선 | `createLine`, `updateLineProperties`, `updateLineCategory`, `rerouteLine` |
| 댓글 (2026-09-30 GA) | `insertComment`, `addCommentReply`, `updateCommentPost`, `deleteComment`, `deleteCommentReply` |

**템플릿 치환에 쓰는 요청의 핵심 필드**

| 요청 | 필드 | 의미 |
| --- | --- | --- |
| `replaceAllText` | `containsText{text, matchCase}`, `replaceText`, `pageObjectIds[]` | 프레젠테이션 전체(또는 지정 슬라이드)에서 문자열 치환. 응답 `occurrencesChanged`. 노트 페이지 ID를 `pageObjectIds`에 넣으면 400 |
| `replaceAllShapesWithImage` | `containsText`, `imageUrl`, `imageReplaceMethod`(`CENTER_INSIDE` 기본·비율 유지 / `CENTER_CROP` 꽉 채움·잘림), `pageObjectIds[]` | 태그가 든 도형 자리를 이미지로. 응답 `occurrencesChanged` |
| `createSlide` | `objectId`, `insertionIndex`(0 기반, 생략 시 끝), `slideLayoutReference{predefinedLayout \| layoutId}`, `placeholderIdMappings[]` | `predefinedLayout`: `BLANK`, `CAPTION_ONLY`, `TITLE`, `TITLE_AND_BODY`, `TITLE_AND_TWO_COLUMNS`, `TITLE_ONLY`, `SECTION_HEADER`, `SECTION_TITLE_AND_DESCRIPTION`, `ONE_COLUMN_TEXT`, `MAIN_POINT`, `BIG_NUMBER`. 응답 `objectId` |
| `duplicateObject` | `objectId`, `objectIds{원본ID: 새ID}` | 슬라이드 복제는 원본 바로 뒤에 들어간다. 안의 요소 ID를 미리 정해 두면 뒤이어 편집하기 쉽다 |
| `insertText` | `objectId`, `cellLocation`(표일 때), `text`, `insertionIndex` | 줄바꿈은 문단 구분이 된다. 서식은 이웃 텍스트를 따른다 |
| `updateTextStyle` / `updateParagraphStyle` | `objectId`, `textRange{type: ALL \| FIXED_RANGE \| FROM_START_INDEX, startIndex, endIndex}`, `style`, **`fields`** | `fields` 마스크 필수(`"bold,fontSize"`). 없으면 지정 안 한 속성까지 덮어쓴다 |
| `createImage` | `objectId`, `url`, `elementProperties{pageObjectId, size, transform}` | URL 요건은 요약 표 참조 |

**주요 객체**

- `Presentation`: `presentationId`, `title`, `pageSize{width, height}`(Dimension, EMU/PT), `locale`, `slides[]`, `masters[]`, `layouts[]`, `notesMaster`, `revisionId`(출력 전용, 24시간 유효), `comments[]`(출력 전용).
- `Page`: `objectId`, `pageType`(`SLIDE`·`MASTER`·`LAYOUT`·`NOTES`·`NOTES_MASTER`), `pageElements[]`, `slideProperties{layoutObjectId, masterObjectId, notesPage, isSkipped}`, `notesProperties{speakerNotesObjectId}`, `pageProperties{backgroundFill, colorScheme}`.
- `PageElement`: `objectId`, `size`, `transform`(AffineTransform: `scaleX`·`scaleY`·`shearX`·`shearY`·`translateX`·`translateY`·`unit`), `title`·`description`(대체 텍스트) + 종류별 필드 `shape`·`image`·`video`·`line`·`table`·`sheetsChart`·`elementGroup`·`wordArt`·`speakerSpotlight`.
- `Shape`: `shapeType`(`TEXT_BOX`, `RECTANGLE` …), `text`(TextContent), `shapeProperties`(채우기·윤곽선·`autofit`), `placeholder{type: TITLE·BODY·SUBTITLE…, index, parentObjectId}`. 레이아웃에서 온 플레이스홀더는 서식을 부모에게서 상속한다.
- `TextContent`: `textElements[]`(각각 `paragraphMarker` | `textRun` | `autoText`, `startIndex`·`endIndex`는 UTF-16 코드 단위, 0 기반 반열림). `textRun`은 같은 서식의 연속 구간이다. 텍스트 끝에 지울 수 없는 암묵적 줄바꿈이 있다.
- `Autofit`: `autofitType`(`NONE`·`TEXT_AUTOFIT`·`SHAPE_AUTOFIT`·`AUTOFIT_TYPE_UNSPECIFIED`=부모 상속), `fontScale`, `lineSpacingReduction`. 텍스트 맞춤에 영향을 주는 요청이 오면 `NONE`으로 자동 설정된다.

## 5. 요청·응답 샘플

`samples/google_slides/` (요청·응답은 우리 엔드포인트 기준, 소유자 이름·이메일·프로젝트 번호 마스킹). 2026-10-04 기준:

| 유즈케이스 | 파일 |
| --- | --- |
| 1 폴더 생성 | Docs와 같음: `google_drive/uc1-create-activity-folder.json` |
| 2 템플릿 업로드(pptx → Slides 변환) | `uc2-upload-template.json` |
| 2 그룹 발표 자료 생성(복사 + 치환 + 공유, 공유 에러 포함) | `uc2-create-group-presentations.json` |
| 2 긴 팀명 넘침 · autofit 해제 · 서식 갈린 태그 | `uc2-long-team-name-overflow.json` |
| 2 에러: Slides API 미사용 설정 · 템플릿 없음 | `uc2-replace-fails-api-disabled.json`, `uc2-template-not-found.json` |
| 3 마감 처리 · 재실행 · 교수자 편집 · 되돌리기 | `uc3-close-submission.json` |
| 4 내보내기(pptx · pdf · txt · odp, png 불가) | `uc4-export.json` |
| 배관·에러 | `create-empty.json`, `read.json`, `error-not-found.json` |

실측에 쓴 템플릿은 python-pptx로 만든 4장짜리 pptx다(표지: `{{activity_name}}`·`팀: {{team_name}}`·`마감: {{due}}`·노트 `{{team_name}} 발표 시작 인사` / 본문 / `{{team_name}} 역할 분담` + 3×2 표 / 실험용: 서식 갈린 태그, autofit 켠 좁은 상자). 레포에는 넣지 않았다(Synsory가 실제 템플릿을 정하면 그걸로 다시 확인).

## 6. 공통 모델 매핑

`Document`(`kind=slides`) ← Drive `files.get` + (읽기 시) Slides `presentations.get`. 구현: `google_drive/mapper.py::document_from_drive_file`, `google_slides/mapper.py::document_from_slides`. `core/models.py`는 바꾸지 않았다.

| Document 필드 | 출처 | 비고 |
| --- | --- | --- |
| `id` | Drive `id` = `presentationId` | 같은 값 |
| `kind` | Drive `mimeType` `application/vnd.google-apps.presentation` → `slides` | |
| `title` | `presentations.get` `title` 우선, 없으면 Drive `name` | 유즈케이스 2는 `files.copy` 응답만 쓰므로 Drive `name` |
| `url` | Drive `webViewLink` | `…/presentation/d/<id>/edit?usp=drivesdk`. 특정 슬라이드는 `#slide=id.<objectId>` |
| `owner` · `created_at` · `modified_at` · `parent_folder_id` · `trashed` · `locked` | Drive `files.get` | Docs와 동일 |
| `text` | `presentations.get` 평문 | 읽기 시나리오에서만. 슬라이드 순서, 도형·표 셀·그룹 안 도형, 슬라이드 끝에 `[노트] …`, 슬라이드 사이 빈 줄. 마스터·레이아웃 문구는 제외. 같은 슬라이드 안의 순서는 화면 배치가 아니라 요소 배열 순서 |

유즈케이스 2 결과는 `GroupPresentationResult(team_name, document, replaced, shares, error)`(usecases 안 dataclass)다. Docs의 `GroupDocumentResult`에 `replaced`(태그별 치환 횟수)가 추가된 형태다. 썸네일·슬라이드 수는 유즈케이스에 없어 모델에 넣지 않았다.

## 7. 에러와 예외 케이스

**실측 (2026-10-04)**

| 상황 | 실제 응답 | 처리 · 샘플 |
| --- | --- | --- |
| Slides API 미사용 설정 | 403 `PERMISSION_DENIED`, `reason=SERVICE_DISABLED` | 콘솔에서 사용 설정. 유즈케이스 2는 사본에 `error`가 담긴다. `uc2-replace-fails-api-disabled.json` |
| 없는 `presentationId` 읽기 | Slides 404 `NOT_FOUND` "Requested entity was not found." | `error-not-found.json` |
| 없는(또는 앱이 볼 수 없는) 템플릿 ID로 복사 | Drive 404 `notFound` | 그 그룹은 `document=null`, 다음 그룹 계속. `uc2-template-not-found.json` |
| 템플릿에 없는 태그 치환 | **에러 아님**. 200, `occurrencesChanged`가 없거나 0 | `replaced`가 0인지 호출자가 확인. `uc3-close-submission.json` |
| 서식이 갈린 태그(`{{team` 굵게 + `_name}}` 보통) | 치환됨. 치환 텍스트는 첫 run 서식(굵게)을 따른다 | 1단계 커뮤니티 보고와 다름. `uc2-long-team-name-overflow.json` |
| 긴 팀명 치환 | 성공(200)하지만 도형 밖으로 넘친다. 치환된 도형의 autofit이 `NONE` | 10절 3항. `uc2-long-team-name-overflow.json` |
| Google 계정 아닌 이메일 공유 | Drive 400 `invalidSharingRequest` | Docs와 동일. `uc2-create-group-presentations.json` |
| 마감 처리 목록에 없는 파일 | 그 파일만 404 `notFound`, 나머지 계속 | `uc3-close-submission.json` |
| 마감 후 교수자(소유자)가 Slides `batchUpdate` | 200 (편집 가능) | 권한 낮추기 방식이라 교수자는 막히지 않는다 |
| Drive `files.export`에 `image/png` | 400 `badRequest` "The requested conversion is not supported." | 우리 엔드포인트는 그 전에 400으로 거부. `uc4-export.json` |

**공식 문서 기준(미실측)**

| 상황 | 예상 응답 | 출처 |
| --- | --- | --- |
| `batchUpdate` 요청 중 하나라도 잘못됨 | 400, 전체 미적용 | batchUpdate 레퍼런스 |
| `requiredRevisionId`가 최신 revision이 아님 | 400 | batchUpdate 레퍼런스 |
| 쿼터 초과 | 429 → 지수 백오프 | limits 문서 |
| `replaceAllText`의 `pageObjectIds`에 노트 페이지나 없는 페이지 | 400 | Request 레퍼런스 |
| 이미지 URL이 비공개·2KB 초과·50MB 초과·25MP 초과·지원 외 형식 | 요청 실패 | Request 레퍼런스 |
| `createSheetsChart`를 `drive.file`만으로 호출 | 403 예상 | Request 레퍼런스 |
| 휴지통 · 기타 Drive 영역 | Docs와 동일 | `docs/google_docs.md` 7절 |

**Picker 템플릿 (2026-10-04 실측)**

| 상황 | 응답 | 샘플 |
| --- | --- | --- |
| 교수자가 UI에서 만든 덱 ID를 Picker 없이 `template_presentation_id`로 | 그룹마다 Drive `files.copy` **404 `notFound`**, 복사본 없음 | `uc2-template-picker-before.json` |
| 같은 덱을 Picker(내 드라이브 목록)로 고른 뒤 | **`files.copy` 200 → `replaceAllText` 200 → 공유 200**. 코드 변경 없음. 토큰 refresh·서버 재시작 뒤에도 유지 | `uc2-create-group-presentations-picker.json` |
| 태그 없는 덱을 템플릿으로 | 치환은 성공(200)하지만 `replaced`가 전부 0. 호출자가 0을 보고 "태그 없음"을 알려야 한다 | 같은 파일 |

## 8. 쿼터 · rate limit · 플랜 제약

공식 limits 문서(2026-10-04 확인).

| 구분 | 프로젝트당 / 분 | 사용자당(프로젝트별) / 분 |
| --- | --- | --- |
| 읽기 요청 (`get`, `pages.get`) | 3,000 | **600** |
| 비싼 읽기 요청 (`pages.getThumbnail`) | 300 | **60** |
| 쓰기 요청 (`create`, `batchUpdate`) | 600 | **60** |

- 요청 수로 센다. `batchUpdate` 안의 요청 수는 무관하다. 템플릿 치환은 태그가 몇 개든 `replaceAllText` 여러 개를 **`batchUpdate` 한 번**에 담는다.
- 썸네일은 슬라이드 하나당 1회이고 사용자당 분당 60이다. 20장짜리 덱 3개를 한 번에 미리보기하면 한도에 닿는다. 서버가 받아서 저장하고 재사용한다.
- 일일 한도는 없다(분당 한도만 지키면 된다).
- 429 → 지수 백오프 `min(2^n초 + 무작위 ms, 32~64초)`. Docs·Drive·Sheets와 같은 패턴. `DriveApiError.is_rate_limit`과 같은 플래그를 `SlidesApiError`에도 둔다.
- 요금: 무료. "쿼터 초과분에 대해 2026년 중 Cloud 결제 계정에 과금 계획" 문구는 Docs·Drive·Sheets와 동일. 핸드오프 때 한 줄 알린다.
- `batchUpdate` 요청 수·페이로드 상한은 공식 수치가 없다. 표 행·열 삽입만 요청당 20개.
- 개인 Google 계정이므로 Workspace 플랜 제약은 없다.

**유즈케이스별 호출 수 (2026-10-04 구현 기준)**

| 작업 | 호출 수 |
| --- | --- |
| 1 폴더 | Drive 1 |
| 2 템플릿 업로드 | Drive `files.create` 1 (액티비티당 1회) |
| 2 그룹 g개 | g × (Drive `files.copy` 1 + Slides `batchUpdate` 1 + Drive `permissions.create` × 학생 수). Slides 쓰기는 g회 → 사용자당 분당 60이면 60그룹까지 1분 |
| 3 마감 | 파일당 Drive `permissions.list` 1 + 학생 수 (Docs와 동일) |
| 4 내보내기 | 파일당 Drive `files.get` 1 + `files.export` 1 |
| 읽기 배관 | `presentations.get` 1 + Drive `files.get` 1 |

## 9. 웹훅 (해당 시)

Slides API에는 없다. 변경 감지는 Drive `changes.watch`/`changes.list` → `docs/google_drive.md` 9절. Drive 알림은 "파일이 바뀌었다"까지만 알려주므로, 어느 슬라이드가 바뀌었는지 알려면 앱이 직전 `presentations.get` 스냅샷(또는 `revisionId`)과 비교해야 한다.

## 10. 함정과 권장 패턴

공식 문서 기준이고, 실측으로 확인한 항목은 날짜를 붙였다(3·4·10·11·12항).

1. **대상은 인덱스가 아니라 `objectId`.** Docs의 "삽입하면 뒤 인덱스가 밀린다" 문제가 슬라이드 단위에서는 없다. 도형 **안의** 텍스트만 UTF-16 인덱스(0 기반)를 쓰고, 거기서는 Docs와 같은 주의(이모지 2단위, 뒤에서 앞으로)가 필요하다. 가능하면 인덱스 대신 `replaceAllText`나 `textRange.type=ALL`을 쓴다.
2. **템플릿 치환은 ID가 아니라 텍스트 태그로.** 공식 머지 가이드의 패턴: 템플릿에 `{{team_name}}` 같은 태그를 넣고 → Drive `files.copy` → `replaceAllText`. 사용자가 UI에서 편집하면 요소 ID가 바뀔 수 있어 ID 기반은 깨진다. 원본 템플릿은 API로 수정하지 않는다.
3. **autofit은 치환하면 꺼진다 (2026-10-04 실측).** pptx에서 `TEXT_AUTOFIT`이던 도형이 `replaceAllText` 뒤 `NONE`이 됐고, 태그가 없던 도형은 `TEXT_AUTOFIT` 그대로였다. 32자 팀명으로 확인: 큰 부제 상자는 줄바꿈으로 들어갔지만, 제목 상자는 3줄이 되며 **슬라이드 위로 넘쳐 잘렸고**, 좁은 상자는 아래로 넘쳤다(글자 크기 그대로). 대책: ① 템플릿에서 태그가 들어가는 상자를 넉넉하게, 특히 제목에 `{{team_name}}`을 넣지 않거나 한 줄 여유를 둔다. ② Synsory에서 팀명 길이를 제한(예: 20자). ③ 필요하면 치환 뒤 `updateTextStyle`로 `fontSize`를 줄인다(미구현).
4. **태그 서식.** 1단계 때는 태그 일부만 굵게 하면 run이 갈라져 `replaceAllText`가 못 찾는다는 커뮤니티 보고가 있었다. **실측(2026-10-04)에서는 찾았다**(`{{team` 굵게 + `_name}}` 보통 → 치환됨, 결과는 첫 run 서식인 굵게). 그래도 결과 서식이 어긋나므로 태그 전체를 같은 서식으로 둔다. `{{name}}`이 `{{full_name}}` 안에서 부분 일치하지 않도록 태그 이름을 겹치지 않게 짓고 `matchCase=true`. 치환 뒤 `occurrencesChanged`가 기대값과 다르면 템플릿 문제다.
5. **이미지는 공개 URL로만.** 로고·QR 등을 넣으려면 Synsory가 공개 URL로 서빙해야 한다. 삽입 시점에 한 번 복사되므로 짧은 수명의 서명 URL이어도 된다. Drive에 올린 이미지의 `webContentLink`는 공개 공유가 아니면 안 될 것으로 예상(미확인, 12절).
6. **(채택 유즈케이스 밖) 썸네일 URL은 30분 + 요청자 계정 꼬리표.** URL을 그대로 학생에게 주면 교수자 권한으로 보는 셈이고, 30분 뒤 끊긴다. 서버가 즉시 내려받아 Synsory 저장소에 두고 자체 URL로 제공한다. `contentUrl` 다운로드 인증 방식은 미확인(12절).
7. **슬라이드 → 이미지는 `getThumbnail`뿐.** `files.export`에 이미지 형식이 없다. 비싼 읽기(사용자당 분당 60)이므로 전 슬라이드 미리보기는 캐시가 전제다. 보통 첫 슬라이드 1장이면 충분한지 2단계에서 정한다.
8. **`fields` 마스크 두 가지.** ① `updateTextStyle`·`updateShapeProperties` 같은 update 요청의 `fields`는 **필수**이고 안 주면 에러 또는 다른 속성까지 덮어쓴다. ② `presentations.get`의 `fields` 쿼리는 응답 축소용이다. 전체 응답은 마스터·레이아웃까지 포함해 크므로 텍스트 추출은 `fields=slides(objectId,pageElements(shape(text)))` 정도로 줄인다.
9. **단위는 EMU.** 1pt = 12,700 EMU. 위치 지정은 `transform{scaleX, scaleY, translateX, translateY, unit}`이고 `createShape`·`createImage`의 `size`는 `scale=1`일 때의 크기다. `updatePageElementTransform`은 `ABSOLUTE`(교체, 생략 필드는 0)와 `RELATIVE`(현재 행렬에 곱함) 중 고른다. 템플릿 방식이면 위치 계산은 거의 필요 없다.
10. **발표자 노트.** `replaceAllText`(페이지 지정 없이)는 발표자 노트의 태그도 바꾼다(2026-10-04 실측). 직접 쓰려면 노트 페이지의 `notesProperties.speakerNotesObjectId` 도형에 `insertText`. `files.export` txt에는 노트가 라벨 없이 슬라이드 본문 뒤에 붙는다(실측).
11. **템플릿은 "pptx 1회 변환 업로드 → 그룹마다 `files.copy`" (채택, 2026-10-04).** `presentations.create`는 `title`·`pageSize`·`locale` 외 전부 무시하고 폴더도 못 정한다. pptx 변환 업로드는 폴더·내용을 한 번에 해결하고, 결과가 앱 소유라 `drive.file`로 복사 원본이 된다. 실측: 플레이스홀더 타입(CENTERED_TITLE·SUBTITLE·TITLE·BODY)·표·노트·pptx의 페이지 크기(13.33in → 12,191,675 EMU)가 보존됐다. 그룹마다 변환 업로드하지 않는 이유는 1절 메모. `files.copy`에 `parents`를 주면 사본이 바로 액티비티 폴더에 생긴다(폴더 이동 호출 불필요).
12. **마감 처리는 Docs와 같다 (2026-10-04 실측).** 같은 함수 `close_submissions`(writer→commenter, 소유자 유지, 재실행 안전), 되돌리기 `restore_editors`, 제출본은 `files.export` pptx/pdf. 마감 뒤에도 교수자 토큰의 Slides `batchUpdate`는 200. Slides API 호출 없음. `docs/google_docs.md` 10절 11~14항 그대로.
13. **동시 편집.** 학생이 덱을 열어 편집 중일 수 있다. `requiredRevisionId`를 쓰면 그사이 변경이 있을 때 400으로 거부되고, 안 쓰면 API를 또 한 명의 협업자로 보고 병합한다. 태그 치환은 병합이 안전하므로 안 써도 되고, 특정 도형 텍스트를 인덱스로 고칠 때만 `requiredRevisionId` + 재조회를 권장(Docs 10절 5항과 같다).
14. **SDK 없이 REST.** 메서드가 다섯 개뿐이다. httpx로 충분. 예외 근거 없음.
15. **Docs·Sheets와 다른 점 정리.** 대상 지정이 `objectId`. 썸네일 전용 메서드와 "비싼 읽기" 쿼터가 있다. 읽기 쿼터가 가장 넉넉하다(사용자당 600). 이미지 삽입은 URL만. 자동 맞춤이 API 편집으로 꺼진다. 낙관적 잠금은 Docs처럼 있다.

16. **Picker로 고른 교수자 덱을 템플릿으로 (2026-10-04).** 조건은 `docs/google_drive.md` 2.1절(API 키 + `setAppId` + `drive.file` 토큰 + 로그인된 브라우저). 고른 ID는 그대로 `template_presentation_id`가 되고 코드는 ①과 같다. 지킬 것: 원본에는 `batchUpdate`를 하지 않는다(복사본만). 교수자가 나중에 원본을 고치면 다음 복사부터 반영된다(`files.copy`는 현재 내용을 복사한다. 실측은 보류). 태그 규칙(공백 없이, 같은 서식, `matchCase`)은 교수자가 UI에서 만든 덱에도 똑같이 적용되므로 Synsory 화면에 태그 안내를 둔다. 치환 결과 `replaced`가 전부 0이면 태그가 없는 덱이다.

## 11. 샘플 코드 (`usecases.py`의 흐름을 기준으로)

아래는 `app/services/google_slides/usecases.py`·`app/services/google_drive/usecases.py`의 실제 함수 호출 순서다. FastAPI 없이 동작하며 `access_token`만 있으면 된다. 흐름은 Docs와 같이 "학기 초 1·2 → 마감 시각에 3·4"다.

```python
from app.services.google_slides.client import SlidesClient
from app.services.google_slides import usecases as slides_uc
from app.services.google_drive.client import DriveClient
from app.services.google_drive import usecases as drive_uc

drive = DriveClient(access_token)   # 교수자 토큰. 만료됐으면 호출 전에 refresh
slides = SlidesClient(access_token)

# 1. 액티비티 폴더 (Docs와 같음)
folder = await drive_uc.create_folder(drive, "발표 1차", parent_folder_id=course_folder_id)

# 2-1. Synsory가 보관하는 pptx 템플릿을 Slides로 변환 업로드. 액티비티당 1회. 태그는 공백 없이 {{team_name}}
template = await slides_uc.upload_template(drive, "[템플릿] 발표 1차", pptx_bytes, folder_id=folder.id)

# 2-2. 그룹마다 복사 → 태그 치환(batchUpdate 1회) → 그룹원 writer 공유. 그룹·이메일 단위로 부분 실패해도 계속
results = await slides_uc.create_group_presentations(
    slides, drive,
    folder_id=folder.id,
    activity_name="발표 1차",
    title_template="{{activity_name}} - {{team_name}}",
    template_presentation_id=template.id,
    groups=[
        slides_uc.GroupSpec("A조", ["a1@gmail.com", "a2@gmail.com"]),
        slides_uc.GroupSpec("B조", ["b1@gmail.com"]),
    ],
    due="2026-10-10 23:59",
    notify=False,
)
for r in results:
    if r.document is None:          # 복사 실패 (템플릿 ID 오류 등)
        ...
    elif r.error:                   # 복사는 됐는데 치환 실패 → 사본 정리 또는 재시도
        ...
    else:
        save(team=r.team_name, presentation_id=r.document.id, url=r.document.url)   # due 처리에 쓰므로 반드시 저장
        if 0 in r.replaced.values(): warn_template(r.replaced)   # 템플릿에 없는 태그
        for sh in r.shares:
            if not sh.ok: ...        # 예: Google 계정 아닌 이메일 → 400 invalidSharingRequest

# 3. 마감 시각 (스케줄러). Docs와 같은 함수. 학생 writer → commenter. 재실행 안전
closed = await slides_uc.close_submissions(drive, [...], to_role="commenter", keep_emails=["ta@gmail.com"])

# 4. 제출본 확보. 반드시 3 다음에
for presentation_id in [...]:
    exported = await slides_uc.export_presentation(drive, presentation_id, fmt="pptx")   # pptx | pdf | txt | odp
    send_to_turnitin(exported.filename, exported.mime_type, exported.content)

# 보조: 본문 확인 (모든 슬라이드·표·발표자 노트 평문)
doc = await slides_uc.read_presentation(slides, drive, presentation_id)
```

에러는 `DriveApiError`(`status`, `reason`, `message`, `is_rate_limit`)와 `SlidesApiError`(`status`, `status_text`, `message`, `is_rate_limit`)로 올라온다. `is_rate_limit`이면 지수 백오프로 재시도하고, 그 외 4xx는 7절 표로 분기한다. 토큰 만료(401)는 client가 처리하지 않으므로 호출 전에 갱신한다.

## 12. 미확인 · 보류 항목

| 항목 | 확인 방법 · 시점 |
| --- | --- |
| ~~기본 `pageSize`~~ | 확인 완료(2026-10-04): `presentations.create` 기본 9,144,000 × 5,143,500 EMU(16:9), `locale`은 계정 언어(`ko`). pptx 변환은 원본 크기 유지 |
| ~~`replaceAllText`가 서식이 갈린 태그를 못 찾는 것~~ | 확인 완료(2026-10-04): 찾는다. 결과는 첫 run 서식. 10절 4항 |
| ~~pptx 변환 업로드 vs `files.copy`~~ | 결정·확인 완료(2026-10-04): pptx 1회 변환 + 그룹마다 복사. 플레이스홀더·표·노트 보존. 10절 11항 |
| ~~`drive.file` 경계가 Slides에서도 같은지~~ | 부분 확인(2026-10-04): 앱이 만든 폴더 안 변환 업로드·복사·`batchUpdate` 모두 동작. 앱이 만들지 않은 덱을 템플릿 ID로 주면 404, Picker로 고른 뒤 200(2026-10-04 확인, 7절) |
| `files.copy`의 쿼터 단위와 `copyComments` 기본값 | 쿼터 단위는 limits 문서에 분류만 있어 미확인(편집 50으로 추정). 템플릿에 댓글이 없으니 보류 |
| 템플릿 pptx의 실제 디자인(Synsory 테마·글꼴)이 변환 후 유지되는지 | Synsory가 실제 템플릿을 정하면 확인. 실측은 python-pptx 기본 테마로만 했다 |
| 이미지 많은 덱의 pdf 내보내기가 10MB를 넘는 경우 | 보류. 실측 덱은 4장·68KB |
| 치환 뒤 넘침 자동 보정(`updateTextStyle` 글자 크기 축소) | 보류. 팀명 길이 제한 + 템플릿 여유로 먼저 대응(10절 3항) |
| 썸네일 `contentUrl` 다운로드 인증·만료 | 유즈케이스에 없어 보류 |
| `createSheetsChart`를 `drive.file`만으로 호출했을 때 실제 응답 | 차트 유즈케이스가 생길 때만 |
| Drive에 올린 이미지를 `createImage` URL로 쓸 수 있는지 | 이미지 삽입 유즈케이스가 생길 때만 |
| 댓글 API(2026-09-30 GA) | 유즈케이스에 없어 보류 |
| ~~교수자가 Drive에 가진 기존 덱을 템플릿으로 쓰는 경우(Picker 필요)~~ | 확인 완료(2026-10-04): Picker로 고른 ID를 `template_presentation_id`로. 코드 변경 없음, 복사·치환·공유 성공. 7절. 남은 것: 태그 든 원본으로 치환 횟수 확인, 원본 수정 후 재복사(보류) |
| `batchUpdate` 요청 개수·페이로드 상한 | 공식 수치 없음. 태그 3개 실측은 문제없음 |
| 2026년 중 쿼터 초과 과금 계획의 실제 시행 여부 | 핸드오프 직전 재확인(Docs와 공통) |
| MCP 서버(2026-07 Developer Preview) | 이 레포는 REST 직접 호출이라 범위 밖. 기록만 |

## 출처 (2026-10-04 확인)

- Slides API Usage limits — https://developers.google.com/workspace/slides/api/limits
- Slides API scopes — https://developers.google.com/workspace/slides/api/scopes
- REST 리소스 목록 — https://developers.google.com/workspace/slides/api/reference/rest
- presentations.create / get / batchUpdate — https://developers.google.com/workspace/slides/api/reference/rest/v1/presentations
- presentations.pages (Page, get) — https://developers.google.com/workspace/slides/api/reference/rest/v1/presentations.pages
- presentations.pages.getThumbnail — https://developers.google.com/workspace/slides/api/reference/rest/v1/presentations.pages/getThumbnail
- Request 타입(batchUpdate) — https://developers.google.com/workspace/slides/api/reference/rest/v1/presentations/request
- Response 타입 — https://developers.google.com/workspace/slides/api/reference/rest/v1/presentations/response
- Shape · Autofit — https://developers.google.com/workspace/slides/api/reference/rest/v1/presentations.pages/shapes
- TextContent — https://developers.google.com/workspace/slides/api/reference/rest/v1/presentations.pages/text
- 개요(페이지 종류, 객체 ID 규칙) — https://developers.google.com/workspace/slides/api/guides/overview
- 템플릿 머지 가이드 — https://developers.google.com/workspace/slides/api/guides/merge
- 변환(단위·EMU) — https://developers.google.com/workspace/slides/api/guides/transform
- 텍스트 서식 — https://developers.google.com/workspace/slides/api/guides/styling
- 댓글 가이드 — https://developers.google.com/workspace/slides/api/guides/comments
- 슬라이드 작업 샘플 — https://developers.google.com/workspace/slides/api/samples/slides
- 릴리스 노트 — https://developers.google.com/workspace/slides/release-notes
- Drive files.copy — https://developers.google.com/workspace/drive/api/reference/rest/v3/files/copy
- Drive files.export(10MB) — https://developers.google.com/workspace/drive/api/reference/rest/v3/files/export
- Drive 내보내기 형식 — https://developers.google.com/workspace/drive/api/guides/ref-export-formats
- Drive 업로드·변환 — https://developers.google.com/workspace/drive/api/guides/manage-uploads
- (비공식, 10절 4항 근거) replaceAllText와 textRun 경계 — https://bulldo.gs/replace-text-placeholders-across-a-deck-in-google-slides/
