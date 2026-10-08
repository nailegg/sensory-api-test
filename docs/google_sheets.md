# Google Sheets 연동 스펙

상태: 6단계(스펙 문서화) 1차 마감 · 7단계(핸드오프) 대기
최종 수정: 2026-10-04 · 작성: 상현
확인 기준: 공식 문서 2026-10-04, 실측 2026-10-04 (개인 Gmail 계정, 테스트 상태 OAuth 앱, 3단계는 Docs 인증 재사용)

이식 대상(studio에 TS로 이식, 위치는 11절 "studio 이식"): `app/services/google_sheets/{client,mapper,scopes,usecases}.py`와 이 문서(+ `app/services/google_drive/{client,mapper,scopes,usecases}.py`, `docs/google_drive.md`). `router.py`는 테스트 서버용이라 이식하지 않는다. Drive 호출(폴더 지정, 메타데이터, 공유·권한, 내보내기, 변경 감지)은 `app/services/google_drive/`와 `docs/google_drive.md`에 두고 이 문서는 Sheets API(`sheets.googleapis.com/v4`)만 다룬다.

---

## 1단계 요약: 할 수 있는 일 · 못 하는 일 · 눈에 띄는 제약

2단계에서 유즈케이스를 고를 때 보는 한 장이다. 아래 3~12절은 이 요약의 근거다.

**리소스.** 스프레드시트(`spreadsheetId`, Drive 파일 ID와 같음) 하나 안에 시트(`sheetId`, 숫자, 이름이 바뀌어도 불변)가 여러 개, 시트는 셀 격자. 범위는 A1 표기(`'시트 이름'!A1:D5`)로 지정한다. Docs처럼 문자 인덱스를 세지 않는다.

**할 수 있는 일**

| 분류 | 내용 | 메서드 |
| --- | --- | --- |
| 생성 | 빈 스프레드시트 생성(제목·시트 구성·고정 행·열 수까지 한 번에). 폴더 지정은 불가 → Drive로 | `spreadsheets.create` 또는 Drive `files.create`(mimeType 지정) |
| 템플릿 | CSV·TSV·xlsx·ods를 올리면서 Sheets로 변환. 기존 스프레드시트 통째로 복사. 시트 한 장만 다른 스프레드시트로 복사 | Drive `files.create`(변환) · Drive `files.copy` · `sheets.copyTo` |
| 값 읽기 | 범위 하나·여러 범위를 2차원 배열로. 표시값/원시값/수식 선택 | `values.get` · `values.batchGet` |
| 값 쓰기 | 범위에 덮어쓰기, 여러 범위 한 번에, 표 끝에 행 추가, 지우기 | `values.update` · `values.batchUpdate` · `values.append` · `values.clear` |
| 구조 | 시트 추가·삭제·복제·이름 변경·숨김, 행·열 삽입·삭제·이동·너비, 틀 고정 | `spreadsheets.batchUpdate` |
| 서식 | 글꼴·배경·테두리·숫자 형식·정렬, 조건부 서식, 셀 병합 | `batchUpdate`(`repeatCell`, `updateCells`, `addConditionalFormatRule`…) |
| 데이터 규칙 | 드롭다운·체크박스 등 데이터 검증, 필터·정렬, 중복 제거, 찾아 바꾸기 | `batchUpdate`(`setDataValidation`, `setBasicFilter`, `sortRange`, `findReplace`…) |
| 보호 | 시트·범위 보호, 편집 가능한 사용자 목록 지정, 경고만 띄우기 | `batchUpdate`(`addProtectedRange`, `updateProtectedRange`) |
| 표(Table) | 열 타입(숫자·날짜·드롭다운·체크박스·칩)이 있는 구조화 표 생성·수정, 표 끝에 행 추가 | `batchUpdate`(`addTable`, `appendCells`+`tableId`). 2025-04 GA |
| 차트 | 차트 추가·수정 | `batchUpdate`(`addChart`, `updateChartSpec`) |
| 메타데이터 | 행·열·시트에 앱 전용 key-value를 붙이고, 그 메타데이터로 값을 찾기 | `developerMetadata.*` · `values.*ByDataFilter` |
| 댓글 | 셀 댓글 읽기·작성·답글·삭제 | `batchUpdate`(`insertComment`…). **2026-09-30 GA** (Docs는 아직 Preview) |
| 스마트 칩 | 사람·Drive 파일 칩 넣기·읽기 | `batchUpdate`. 2025-06 GA |
| 내보내기 | xlsx · ods · pdf · csv · tsv · zip(HTML) | Drive `files.export` (10MB 상한) |
| 조회 | 파일 메타데이터(소유자·수정 시각·URL), 공유·권한, 휴지통, 변경 감지 | Drive API (`docs/google_drive.md`) |

**못 하는 일 · 다른 API로 해야 하는 일**

- 폴더 지정 생성, 공유, 삭제, 목록, 파일 복사, 내보내기, 변경 감지는 Sheets API에 없다. 전부 Drive API.
- 웹훅 없음. 셀 변경 알림은 Drive `changes.watch`/`changes.list`뿐이고 "어느 셀이 바뀌었는지"는 알 수 없다. 알려면 전후 값을 앱이 비교해야 한다.
- 수식 계산 결과를 서버에서 "다시 계산해 달라"고 요청하는 API는 없다. `USER_ENTERED`로 쓰면 Sheets가 계산하고 `values.get`이 결과를 돌려준다.
- 시트 보호의 `editors`는 이메일 목록이지만, 그 사용자가 파일 편집 권한(Drive 공유)이 없으면 의미가 없다. 보호는 Drive 공유 위에 얹는 2차 제한이다.
- 응답 제출(설문)은 Forms 영역. Sheets는 Forms 응답의 저장소가 될 수 있을 뿐이다.
- 페이지네이션이 없다. 큰 시트는 `ranges`·`fields`로 잘라 읽어야 하고, 180초 넘는 요청은 타임아웃.

**눈에 띄는 제약**

| 항목 | 값 | 비고 |
| --- | --- | --- |
| 읽기 쿼터 | 프로젝트당 분당 300 · **사용자당 분당 60** | Docs(읽기 300/사용자)보다 5배 낮다 |
| 쓰기 쿼터 | 프로젝트당 분당 300 · **사용자당 분당 60** | 요청 1건 = 1회. 셀 수·배치 안의 요청 수는 무관 → 모아서 보낸다 |
| 페이로드 | 하드 한도 없음. **2MB 이하 권장** | 큰 시트 전체 쓰기는 나눈다 |
| 처리 시간 | **180초** 초과 시 타임아웃 | `spreadsheets.get`에 `includeGridData=true`를 큰 시트에 쓰면 위험 |
| 스프레드시트 크기 | **셀 2,000만 개 또는 100MB** | Sheets 제품 한도(Drive 도움말). 열 수·셀당 문자 수 한도는 12절 |
| 요금 | 무료. 단 "쿼터 초과분 2026년 중 과금 계획" 문구 있음 | Docs·Drive와 같은 문구 |
| scope | `drive.file`로 **모든 Sheets 메서드** 호출 가능 | `spreadsheets`·`spreadsheets.readonly`는 민감 등급. 앱이 만든 파일만 다루면 불필요 |
| 동시 편집 | `batchUpdate`는 원자적이지만 Docs의 `requiredRevisionId` 같은 낙관적 잠금이 **없다** | 사용자가 행을 끼워 넣으면 A1 범위가 어긋난다. 10절 |
| 날짜 | `UNFORMATTED_VALUE`로 읽으면 날짜가 1899-12-30 기준 일련번호(숫자) | 로케일에 따라 표시값이 달라진다 |

**유즈케이스는 1절(2026-10-04 확정).** Docs·Slides와 같은 4개 + 마감 후 값 읽기. 성적표 동기화는 검토 후 보류했고 그 근거는 1.2~1.3에 있다. 핵심: 성적표 자체는 API로 전부 되지만 "학생이 자기 성적만, 입력 완료된 것만 본다"는 요구는 **Sheets에 행·셀 단위 권한이 없어** 서버가 걸러야 하므로, 성적 원본은 DB로 한다.

---

## 1. 이 서비스로 하는 일 (유즈케이스)

2026-10-04 상현 확정: **Docs·Slides와 같은 유즈케이스 4개 + 마감 후 값 읽기 1개.** 전제도 같다(OAuth 연결은 교수자, 파일은 교수자 소유, 학생은 Drive 공유로 편집). **성적표 동기화는 검토 후 보류**(1.3). 성적의 원본은 Synsory DB이고 교수자 성적 입력은 Synsory 화면에서 한다.

| # | 유즈케이스 | 호출 순서 | usecases 함수 |
| --- | --- | --- | --- |
| 1 | 특정 액티비티에 해당하는 폴더를 만든다 | Drive `files.create` (folder) | `google_drive.usecases.create_folder` |
| 2 | 교수자가 템플릿(태그가 든 시트 + 팀명으로 포맷되는 파일명)으로 폴더 안에 그룹마다 스프레드시트를 만들고 그룹원에게 편집 권한을 준다 | 액티비티당 1회: Drive `files.create` (xlsx 업로드 + Sheets 변환, `parents`=액티비티 폴더) → 그룹마다: Drive `files.copy` (`name`, `parents`) → Sheets `batchUpdate` (`findReplace` × 태그 수, `allSheets=true`, 1회) → 그룹원마다 Drive `permissions.create` (`role=writer`) | `upload_template` → `create_group_sheets` |
| 3 | 마감(due) 시점에 편집을 비활성화한다 | Docs와 동일: 파일마다 Drive `permissions.list` → 학생 writer마다 `permissions.update` `role=commenter` | `close_submissions` (`google_drive.usecases`, Docs·Slides와 같은 함수) |
| 4 | 같은 시점에 파일로 내보내 다른 API로 보낸다 | Drive `files.export` (xlsx · pdf · csv · ods · tsv · zip, 10MB 상한) | `export_spreadsheet` |
| 5 | 마감 후 그룹 시트의 값을 읽어 Synsory DB에 반영한다 (동료 평가 점수, 체크리스트 등) | Sheets `spreadsheets.get`(`fields=sheets.properties`, 시트 이름 확인) → `values.get` 또는 `values.batchGet` (`valueRenderOption=UNFORMATTED_VALUE`) → 2차원 배열을 호출자에게 반환 | `read_sheet_values` |

**유즈케이스별 메모**

- 1·3: Drive 호출뿐이라 Sheets 코드가 없다. Docs·Slides가 쓰는 `google_drive/usecases.py`의 함수를 그대로 쓴다.
- 2: 템플릿은 **Synsory가 보관하는 xlsx 파일**로 가정한다(Docs의 Markdown, Slides의 pptx에 대응). Slides와 같은 패턴을 기본으로 한다: 액티비티당 한 번만 변환 업로드하고 그룹마다 `files.copy`한 뒤 Sheets `findReplace`로 태그를 치환한다. 이유: ① xlsx에 넣어 둔 데이터 검증·수식·서식·시트 구성이 그대로 복사된다. ② `findReplace`는 Slides `replaceAllText`에 해당하는 요청이라 코드 구조가 같다. **비교용 (A)**: 템플릿이 평문 표뿐이면 CSV 텍스트를 치환해 그룹마다 변환 업로드(1회, Docs의 Markdown 방식)하는 편이 더 단순하다. 실측(2026-10-04): (B)는 검증·수식·서식·틀 고정·시트 2장이 보존되고 수식 안 태그까지 치환됐다. (A)는 시트 1장·검증 없음이고 `0123456`이 숫자로 바뀐다. **(B) 채택**, (A)는 값만 있는 표에만. 10절 11·12항.
- 2: 태그 이름은 Docs·Slides와 같다(`{{team_name}}`, `{{activity_name}}`, `{{due}}`). `findReplace`는 문자열 일치이므로 Slides처럼 공백 없이 정확히 쓴다. 수식 안의 태그는 `includeFormulas=true`로 치환된다(2026-10-04 실측). 응답 `occurrencesChanged`가 0이면 템플릿에 태그가 없는 것이다.
- 2: 복사는 됐는데 치환이 실패하면 결과에 `document`와 `error`를 함께 담고 공유는 하지 않는다(Slides와 같은 규칙).
- 2: 교수자가 Drive에 이미 가진 시트를 템플릿으로 쓰는 것은 **Google Picker**로 가능하다(`docs/google_drive.md` 2.1절, 2026-10-04 탐색 완료. scope 추가 없음). Picker로 고른 시트 ID를 `template_spreadsheet_id`로 넘기면 copy 방식 코드가 그대로 동작해야 한다(원본은 수정하지 않고 복사본만 `findReplace`). 실측(2026-10-04): Picker 전 404는 확인(`samples/google_sheets/uc2-template-picker-before.json`), Picker 후 성공은 Slides로만 확인했고 Sheets는 보류. 복사→치환→공유 흐름의 공통 함수 `google_drive.usecases.create_group_files_from_template`(Slides가 사용)가 있으니 `create_group_sheets`의 copy 방식도 이것으로 바꿀 수 있다(치환 요청은 `replace_tags`로 전달, `replace_errors=(SheetsApiError,)`).
- 3: 기본은 권한 낮추기. Sheets에는 추가로 `addProtectedRange`로 **학생 입력 열만 잠그고 파일은 열어 두는** 선택지가 있다(교수자가 같은 시트에 채점 열을 쓰는 경우). 실측(2026-10-04): 보호 중에도 소유자 API 쓰기는 200(막지 않음). `editors`를 생략하면 학생 writer까지 편집 가능으로 들어가므로 `lock_ranges`는 항상 `editors`를 명시한다(10절 10항). 채택 여부는 그 요구가 생길 때 정한다.
- 4: 형식은 Docs의 docx·md·html 대신 **xlsx · pdf · csv · ods · tsv · zip**. CSV·TSV는 첫 시트만 나온다. 전체 보존은 xlsx.
- 5: 이 유즈케이스가 Sheets 고유의 읽기다. 시트 이름이 바뀔 수 있으므로 `sheetId`로 시트를 찾아 A1 범위를 만든다(10절 9항). 값은 `UNFORMATTED_VALUE`로 읽어 숫자는 숫자로, 날짜는 일련번호로 받고 변환은 호출자가 한다. 유효성(숫자 범위, 빈 칸)은 Synsory 쪽 검증이다. 학생이 다른 그룹 시트를 볼 수 없는 것은 Drive 권한으로 보장된다(Docs 10절 12항 실측). 같은 그룹 안에서는 서로의 입력이 보이므로 **익명 동료 평가는 시트가 아니라 Forms 또는 Synsory 화면**으로 한다.
- scope: 다섯 유즈케이스 모두 `drive.file` 하나. `services/google_sheets/scopes.py`는 빈 dict.
- 보조 배관: `read_spreadsheet`(구조 + Document, `include_values`로 전체 값 평문)와 `list_sheets`(sheetId·이름·보호 범위). 서비스는 생성 직후 `list_sheets`로 `sheet_id`를 저장한다(복사본의 sheetId는 0이 아니다, 10절 9항).

### 1.2 배경: 왜 성적 관리를 Sheets로 하지 않는가

Synsory는 교수자용 워크플로우 커스터마이제이션·자동 관리 시스템이고 학생 관리 중 성적 관리가 필수다. 처음 Sheets를 고려한 이유는 "시트를 DB처럼 써서 성적 관리를 쉽게"였다. 상현이 제시한 요구는 두 가지였다.

- A. 전체 학생(행) × 평가항목(열: 출석·과제·프로젝트·기타). 항목별 만점 설정, 값 입력·수정, 집계.
- B. 학생 ID로 자기 성적만 조회. 다른 학생 성적을 볼 수 없어야 하고, 입력 완료 전 성적도 볼 수 없어야 한다.

1단계 결과를 대어 본 결론(2026-10-04):

- A는 API로 전부 된다. `drive.file`만으로, 작업당 Sheets 호출 1~2회(생성 3회, 입력 `values.batchUpdate` 1회, 집계는 수식 또는 값 쓰기, 만점 범위는 `setDataValidation`, 고정 열은 `addProtectedRange`).
- B는 **API로 보장할 수 없다.** Sheets의 권한 단위는 파일이고 행·셀 단위 보기 권한이 없다. `ProtectedRange`는 편집만 막고 보기는 못 막는다. "입력 완료" 상태도 없다. 따라서 학생에게 성적표 파일을 공유하는 순간 B가 깨지고, 어떤 방식이든 **Synsory 서버 코드**가 한 학생의 행만, 공개된 항목만 걸러서 돌려줘야 한다.
- 시트를 원본으로 두고 Synsory가 교수자 토큰으로 읽어 거르는 방식은 조회마다 읽기 1회라 **교수자 토큰 기준 사용자당 분당 60회**에 걸린다(성적 발표 직후 동시 조회 → 429). 캐시나 DB 미러가 필수이고, 교수자 refresh token이 죽으면 학생 조회가 멈춘다. 스키마 보장(열 이름 변경, 행 삽입, 숫자 칸에 문자)도 없다. 학생별 파일 방식은 공개할 때마다 학생 수만큼 쓰기가 들어(100명 = 2분) 운영 부담이 크다.
- 결국 성적 원본은 DB가 되어야 하고, 그러면 시트는 DB의 사본이다. 사본을 유지하는 비용(동기화·충돌 규칙·검증)이 생기는데 얻는 것은 "교수자가 Sheets UI에서 입력한다"뿐이고, 이는 Synsory에 성적 입력 화면을 두면 없어진다. 엑셀 파일 다운로드는 Google 없이 서버에서 만들면 된다.

**결정(2026-10-04 상현):** 성적 원본은 Synsory DB, 교수자 입력은 Synsory 화면. Sheets 성적표 동기화는 우선 구현에서 제외한다. Sheets가 중복이 아닌 곳은 **시트 자체가 학생 산출물**인 경우(유즈케이스 2~5)이고, 그 값을 마감 후 한 번 DB로 가져오는 흐름(유즈케이스 5)은 한 방향·한 번이라 동기화 부담이 없다.

### 1.3 검토 후 보류: 성적표 동기화

교수자들이 "시트에서 성적을 고치고 싶다"고 실제로 요구하면 아래 순서로 붙인다. 모두 1단계 분석으로 구현 가능성이 확인되었고 `drive.file`로 된다.

| 단계 | 함수 (후보) | 하는 일 | 비용 |
| --- | --- | --- | --- |
| 내보내기 | `create_gradebook(drive, sheets, folder_id, title, students, items)` | 성적표 생성: 1행 항목명, 2행 만점, A열 학번(`RAW`로 문자 유지), B열 이름, 틀 고정, `setDataValidation`(0~만점), 학번·이름·만점·집계 열 `addProtectedRange` | Drive 1 + `batchUpdate` 1 + `values.update` 1 |
| 내보내기 | `write_scores(sheets, spreadsheet_id, scores)` | DB 점수를 시트에 씀. A열 학번으로 행을 찾아 `values.batchUpdate` 1회 | 읽기 1 + 쓰기 1 |
| 가져오기 | `read_gradebook(sheets, spreadsheet_id)` | 전체를 읽어 학번별 dict + 검증 결과(숫자 아님·만점 초과·누락·미등록 학번) | 읽기 1 |
| 가져오기 | 충돌 규칙 | 시트와 DB가 다를 때 무엇이 이기는지. "가져오기" 버튼이 곧 입력 완료 게이트 | 서비스 레포 설계 |

내보내기까지는 싸고(유즈케이스 2의 배관 재사용), 복잡도는 가져오기의 검증·충돌 규칙에서 생긴다. 집계를 시트 수식(`USER_ENTERED`)으로 넣으면 교수자가 지울 수 있으므로 DB가 계산해 값으로 쓰는 쪽을 전제한다. 학생 조회는 어떤 경우에도 DB에서 한다.

## 2. 인증

Google 4종이 공유하는 OAuth 흐름이다. 콘솔 설정·인가·갱신 절차는 `docs/google_docs.md` 2절, 공통 제약은 `docs/google_drive.md` 2절. Sheets에서 추가로 할 일:

- GCP 콘솔 "API 및 서비스 → 라이브러리"에서 **Google Sheets API**를 사용 설정한다(2026-10-04 완료). 빠뜨리면 호출마다 403 `SERVICE_DISABLED`(Slides 실측과 같은 증상).
- 앱이 만든 파일만 다루는 동안은 scope 추가가 없으므로 **재동의가 필요 없다**. `spreadsheets`·`spreadsheets.readonly`를 추가하게 되면 사용자가 재동의해야 한다(`include_granted_scopes=true`로 증분 인가).
- 사용자 모델은 Docs와 같다: OAuth 연결은 교수자, 학생은 Drive 공유로 접근.

## 3. scope 표

공식 scope 문서(2026-10-04 확인) 기준. `spreadsheets.create` · `get` · `batchUpdate` · `values.*` · `sheets.copyTo` 레퍼런스 모두 `drive.file`을 허용 scope로 나열한다.

| scope | 등급 | 가능한 범위 | 판단 |
| --- | --- | --- | --- |
| `drive.file` | 비민감 (공식 문서가 "권장") | 앱이 만든 파일, 사용자가 Picker로 고른 파일만 | **기본값.** `services/google_sheets/scopes.py`는 빈 dict로 시작하고 인가는 `google_drive/scopes.py`의 `drive.file`로 한다(Docs와 동일) |
| `spreadsheets.readonly` | 민감 | 사용자의 모든 스프레드시트 읽기 | 교수자의 기존 시트(명단·성적표)를 Picker 없이 읽어야 할 때만 |
| `spreadsheets` | 민감 | 사용자의 모든 스프레드시트 읽기·쓰기 | 기존 시트를 Picker 없이 편집해야 할 때만 |
| `drive.readonly` / `drive` | 제한 | Drive 전체 | 쓰지 않는다. CASA 보안 평가 대상 |

`drive.file`의 경계(앱이 만든 파일만 읽기, 사용자 폴더 안에 생성은 가능)는 `docs/google_drive.md` 10절 실측과 같을 것으로 보고, Sheets에서 다시 확인하지 않는다. 다를 경우만 12절에 적는다.

## 4. 엔드포인트 표

Base URL: `https://sheets.googleapis.com/v4`. Discovery: `https://sheets.googleapis.com/$discovery/rest?version=v4`.

**스프레드시트 단위**

| 메서드 | 경로 | 용도 | 쿼터 | 비고 |
| --- | --- | --- | --- | --- |
| `spreadsheets.create` | `POST /spreadsheets` | 생성 | 쓰기 | 본문에 `properties.title`, `sheets[]`(이름·행열 수·고정 행), `namedRanges[]`까지 넣을 수 있다. **폴더 지정 불가** → Drive `files.create`(`mimeType: application/vnd.google-apps.spreadsheet`, `parents`) 또는 생성 후 `files.update`(`addParents`) |
| `spreadsheets.get` | `GET /spreadsheets/{id}` | 구조·속성·(선택)셀 데이터 | 읽기 | 기본은 **구조만**(시트 목록·속성·보호 범위·이름 범위). 값까지 보려면 `includeGridData=true` 또는 `fields` 마스크 + `ranges[]`. 큰 시트에 `includeGridData=true`는 180초 타임아웃 위험 |
| `spreadsheets.getByDataFilter` | `POST /spreadsheets/{id}:getByDataFilter` | 메타데이터·범위 필터로 조회 | 읽기 | developer metadata를 쓰는 경우만 |
| `spreadsheets.batchUpdate` | `POST /spreadsheets/{id}:batchUpdate` | 값 외 **모든 변경**(구조·서식·보호·표·차트·댓글) | 쓰기 | 요청 배열을 **원자적으로** 적용. 하나라도 검증 실패면 전체 거부. `replies[]`는 요청과 1:1. `includeSpreadsheetInResponse`로 결과 구조를 같이 받을 수 있다 |
| `sheets.copyTo` | `POST /spreadsheets/{id}/sheets/{sheetId}:copyTo` | 시트 한 장을 다른 스프레드시트로 복사 | 쓰기 | 본문 `destinationSpreadsheetId`. 응답은 새 시트의 `SheetProperties`(이름은 "Copy of …"가 되므로 `updateSheetProperties`로 바꾼다) |
| `developerMetadata.get` / `search` | `GET …/developerMetadata/{metadataId}` / `POST …/developerMetadata:search` | 앱 전용 메타데이터 조회 | 읽기 | 행에 Synsory ID를 붙여 두고 행 위치가 바뀌어도 찾는 용도. 10절 |

**값 단위 (`spreadsheets.values`)** — 서식 없이 값만. A1 표기.

| 메서드 | 경로 | 용도 | 쿼터 | 비고 |
| --- | --- | --- | --- | --- |
| `values.get` | `GET /spreadsheets/{id}/values/{range}` | 범위 하나 읽기 | 읽기 | `majorDimension`(ROWS/COLUMNS), `valueRenderOption`, `dateTimeRenderOption` |
| `values.batchGet` | `GET /spreadsheets/{id}/values:batchGet?ranges=…` | 여러 범위 읽기 | 읽기 1회 | 불연속 범위를 한 번에 |
| `values.update` | `PUT /spreadsheets/{id}/values/{range}` | 범위 덮어쓰기 | 쓰기 | `valueInputOption` **필수**. 응답 `updatedRange`·`updatedRows`·`updatedColumns`·`updatedCells` |
| `values.batchUpdate` | `POST /spreadsheets/{id}/values:batchUpdate` | 여러 범위 덮어쓰기 | 쓰기 1회 | 본문 `data[]`(ValueRange 목록) + `valueInputOption`. 보류된 성적표 동기화(1.3)에서 쓸 기본 메서드 |
| `values.append` | `POST /spreadsheets/{id}/values/{range}:append` | 표 끝에 행 추가 | 쓰기 | `range`는 "표를 찾을 범위"이고 실제 쓰는 위치는 그 표의 다음 행. `insertDataOption=INSERT_ROWS`면 아래 데이터를 밀어낸다(기본 OVERWRITE). 응답 `tableRange`(추가 전 표 범위) |
| `values.clear` / `batchClear` | `POST …/values/{range}:clear` / `…/values:batchClear` | 값만 지우기(서식 유지) | 쓰기 | |
| `values.*ByDataFilter` | `POST …/values:batchGetByDataFilter` 등 | 메타데이터로 범위를 찾아 읽기·쓰기·지우기 | 각 1회 | developer metadata와 세트 |

**`values` 공통 파라미터**

| 파라미터 | 값 | 의미 |
| --- | --- | --- |
| `valueInputOption` (쓰기, 필수) | `RAW` | 문자열 그대로. `=SUM(A1)`도 문자로 들어감, `2026-10-04`도 문자 |
| | `USER_ENTERED` | UI에 입력한 것처럼 파싱. 수식 계산, 숫자·날짜 자동 인식(로케일 의존) |
| `valueRenderOption` (읽기) | `FORMATTED_VALUE`(기본) | 화면 표시 문자열("1,234", "2026. 10. 4") |
| | `UNFORMATTED_VALUE` | 계산된 원시값(1234, 날짜는 일련번호 46299.0) |
| | `FORMULA` | 수식이 있으면 수식 문자열 |
| `dateTimeRenderOption` (읽기) | `SERIAL_NUMBER`(기본) / `FORMATTED_STRING` | `FORMATTED_VALUE`일 때는 무시된다 |
| `majorDimension` | `ROWS`(기본) / `COLUMNS` | 2차원 배열의 바깥 축 |
| `insertDataOption` (append) | `OVERWRITE`(기본) / `INSERT_ROWS` | 아래 데이터 덮어쓰기 vs 행 삽입 |

**`batchUpdate` 요청 종류** (Request union 전체, 74종. 2026-10-04 기준)

| 분류 | 요청 |
| --- | --- |
| 스프레드시트·시트 속성 | `updateSpreadsheetProperties`, `updateSheetProperties`, `addSheet`, `deleteSheet`, `duplicateSheet` |
| 행·열 | `insertDimension`, `deleteDimension`, `appendDimension`, `moveDimension`, `updateDimensionProperties`, `autoResizeDimensions`, `addDimensionGroup`, `updateDimensionGroup`, `deleteDimensionGroup` |
| 셀 값·서식 | `updateCells`, `repeatCell`, `appendCells`, `insertRange`, `deleteRange`, `updateBorders`, `mergeCells`, `unmergeCells`, `pasteData`, `cutPaste`, `copyPaste`, `autoFill`, `textToColumns`, `trimWhitespace`, `deleteDuplicates`, `randomizeRange`, `findReplace`, `sortRange` |
| 이름 범위·보호 | `addNamedRange`, `updateNamedRange`, `deleteNamedRange`, `addProtectedRange`, `updateProtectedRange`, `deleteProtectedRange` |
| 조건부 서식·검증·필터 | `addConditionalFormatRule`, `updateConditionalFormatRule`, `deleteConditionalFormatRule`, `setDataValidation`, `setBasicFilter`, `clearBasicFilter`, `addFilterView`, `updateFilterView`, `duplicateFilterView`, `deleteFilterView`, `addSlicer`, `updateSlicerSpec` |
| 표·밴딩 | `addTable`, `updateTable`, `deleteTable`, `addBanding`, `updateBanding`, `deleteBanding` |
| 차트·개체 | `addChart`, `updateChartSpec`, `updateEmbeddedObjectPosition`, `updateEmbeddedObjectBorder`, `deleteEmbeddedObject` |
| 메타데이터 | `createDeveloperMetadata`, `updateDeveloperMetadata`, `deleteDeveloperMetadata` |
| 외부 데이터 (Connected Sheets, Workspace 전용) | `addDataSource`, `updateDataSource`, `deleteDataSource`, `refreshDataSource`, `cancelDataSourceRefresh` — 개인 계정 불가, 미사용 |
| 댓글 (2026-09-30 GA) | `insertComment`, `addCommentReply`, `updateCommentPost`, `deleteComment`, `deleteCommentReply` |

**주요 객체**

- `SheetProperties`: `sheetId`(불변 숫자), `title`, `index`(생략하면 맨 끝), `sheetType`(GRID/OBJECT/DATA_SOURCE), `gridProperties{rowCount, columnCount, frozenRowCount, frozenColumnCount}`, `hidden`, `tabColorStyle`.
- `ProtectedRange`: `range`(GridRange, 비워 두면 시트 전체), `editors{users[], groups[], domainUsersCanEdit}`, `warningOnly`(true면 `editors` 무시, 경고만), `unprotectedRanges[]`(시트 보호 중 예외 구역), `requestingUserCanEdit`(읽기 전용). `domainUsersCanEdit`는 Workspace 도메인 문서에서만.
- `GridRange`: `sheetId` + 0 기반 반열림 `startRowIndex/endRowIndex/startColumnIndex/endColumnIndex`. `batchUpdate`는 A1이 아니라 이걸 쓴다. A1 ↔ GridRange 변환 함수가 `client.py` 또는 `mapper.py`에 필요하다.

## 5. 요청·응답 샘플

`samples/google_sheets/` (요청·응답은 우리 엔드포인트 기준, 소유자 이름·이메일 마스킹). 2026-10-04 기준:

| 유즈케이스 | 파일 |
| --- | --- |
| 1 폴더 생성 | Docs와 같음: `google_drive/uc1-create-activity-folder.json` |
| 2 템플릿 업로드(xlsx → Sheets 변환) + 검증·수식·서식 보존 확인 | `uc2-upload-template.json` |
| 2 그룹 시트 생성(복사 + `findReplace` + 공유, 긴 팀명, 공유 에러) | `uc2-create-group-sheets.json` |
| 2 비교: CSV 변환 업로드 vs xlsx 복사 (수식·학번·시트 수) | `uc2-create-group-sheets-csv-compare.json` |
| 3 마감 처리 · 없는 ID · 재실행 · 마감 뒤 교수자 쓰기 · 되돌리기 | `uc3-close-submission.json` |
| 3 선택지: 보호 범위 → 소유자 API 쓰기 → editors 지정 → 해제 | `uc3-lock-ranges-owner-write.json` |
| 4 내보내기(xlsx · csv · pdf · tsv, docx는 400) | `uc4-export.json` |
| 5 값 읽기(UNFORMATTED vs FORMATTED, 날짜 일련번호, 시트 이름 변경 뒤 `sheet_id`로 읽기) | `uc5-read-values.json` |
| 5 실험: `RAW` vs `USER_ENTERED` (학번 앞자리 0, 수식 문자열) | `uc5-raw-vs-user-entered.json` |
| 5 실험: `values.append` 표 탐지 | `uc5-append.json` |
| 에러 모음 | `error-cases.json` |
| 배관 | `create-empty.json` |

실측에 쓴 템플릿은 openpyxl로 만든 2시트 xlsx다(평가: `{{activity_name}}`·`팀: {{team_name}}`·`마감: {{due}}`, 항목 4행에 데이터 검증 0~10, `=SUM(B6:B9)`, 수식 안 태그 `="{{team_name}} 평균: "&…`, 텍스트 서식 학번 `0123456`, 5행 틀 고정 / 역할 분담: `{{team_name}} 역할 분담` + 헤더). CSV 템플릿은 같은 내용의 평문 표. 레포에는 넣지 않았다(Synsory가 실제 템플릿을 정하면 그걸로 다시 확인).

## 6. 공통 모델 매핑

`Document`(`kind=sheet`) ← Drive `files.get` + (읽기 시) `spreadsheets.get`. 구현: `google_drive/mapper.py::document_from_drive_file`, `google_sheets/mapper.py::document_from_spreadsheet`. `core/models.py`는 바꾸지 않았다.

| Document 필드 | 출처 | 비고 |
| --- | --- | --- |
| `id` | Drive `id` = `spreadsheetId` | 같은 값 |
| `kind` | Drive `mimeType` `application/vnd.google-apps.spreadsheet` → `sheet` | |
| `title` | `spreadsheets.get` `properties.title` 우선, 없으면 Drive `name` | 유즈케이스 2는 `files.copy` 응답만 쓰므로 Drive `name` |
| `url` | Drive `webViewLink` | `…/spreadsheets/d/<id>/edit?usp=drivesdk`. 특정 시트는 `#gid=<sheetId>` |
| `owner` · `created_at` · `modified_at` · `parent_folder_id` · `trashed` · `locked` | Drive `files.get` | Docs와 동일 |
| `text` | `values.batchGet` 평문 | `read_spreadsheet(include_values=True)`에서만. 시트마다 `[시트 이름]` 줄 뒤 탭 구분 행, 시트 사이 빈 줄. 숫자는 `UNFORMATTED_VALUE`(정수는 소수점 없이), 날짜는 일련번호 그대로 |

시트 단위 정보는 `Document`가 아니라 usecases 안 dataclass로 돌려준다.

| dataclass | 필드 | 쓰는 곳 |
| --- | --- | --- |
| `SheetInfo` | `sheet_id`(불변, URL의 gid), `title`, `index`, `hidden`, `row_count`, `column_count`, `frozen_row_count`, `protected_ranges[]` | `list_sheets`. 서비스는 생성 직후 `sheet_id`를 저장한다 |
| `SheetValues` | `spreadsheet_id`, `sheet_id`, `sheet_title`, `range`(실제 응답 범위), `values`(2차원) | `read_sheet_values`(유즈케이스 5) |
| `GroupSheetResult` | `team_name`, `document`, `replaced{태그: 횟수}`, `shares[]`, `error` | `create_group_sheets`. Slides의 `GroupPresentationResult`와 같은 형태 |

## 7. 에러와 예외 케이스

**실측 (2026-10-04)**

| 상황 | 실제 응답 | 처리 · 샘플 |
| --- | --- | --- |
| 없는 `spreadsheetId` 읽기 | Sheets 404 `NOT_FOUND` "Requested entity was not found." | `error-cases.json` |
| 없는(또는 이름이 바뀐) 시트 이름으로 `values.get` | **400 `INVALID_ARGUMENT` "Unable to parse range: '…'"** | 시트 이름이 아니라 `sheet_id`로 찾는다(10절 9항). `uc5-read-values.json` |
| 격자 밖 범위(`ZZZ999999`) | 400 "Range (…) exceeds grid limits. Max rows: 1000, max columns: 26" | 기본 격자는 1000행 × 26열. 그 밖은 행·열 추가 뒤 써야 한다 |
| `values.update`에 범위보다 큰 배열 | 400 "Requested writing within range [A1:B1], but tried writing to column [C]" | 범위를 배열 크기에 맞춰 만든다 |
| `addProtectedRange`에 없는 `sheetId`(0) | 400 "No grid with id: 0" | 변환 업로드·복사 파일의 sheetId는 0이 아니다. `list_sheets`로 확인. `uc3-lock-ranges-owner-write.json` |
| 없는 템플릿 ID로 복사 | Drive 404 `notFound` | 그 그룹은 `document=null`, 다음 그룹 계속. `error-cases.json` |
| 템플릿에 없는 태그 치환 | **에러 아님.** 200, `occurrencesChanged` 없음 → 0 | `replaced`가 0인지 호출자가 확인 |
| 복사·CSV 방식 둘 다 지정 또는 둘 다 누락 | 우리 쪽 400 `ValueError` | `error-cases.json` |
| Google 계정 아닌 이메일 공유 | Drive 400 `invalidSharingRequest` | Docs와 동일. `uc2-create-group-sheets.json` |
| 마감 처리 목록에 없는 파일 | 그 파일만 404 `notFound`, 나머지 계속 | `uc3-close-submission.json` |
| 마감 후 교수자(소유자)가 `values.update` | 200 | 권한 낮추기 방식이라 교수자는 막히지 않는다 |
| 보호 범위 안에 소유자 토큰으로 `values.update` | **200** | 보호는 소유자 API 쓰기를 막지 않는다. `uc3-lock-ranges-owner-write.json` |
| `files.export`에 docx | 우리 쪽 400 (지원 목록 안내) | `uc4-export.json` |
| 수식이 아직 계산 불가(`AVERAGE` 빈 범위) | 에러 아님. `UNFORMATTED_VALUE`로 읽으면 셀 값이 `"#DIV/0! (…)"` 문자열 | 읽는 쪽이 `#`로 시작하는 문자열을 에러 값으로 처리 |

**공식 문서 기준(미실측)**

| 상황 | 예상 응답 | 출처 |
| --- | --- | --- |
| `batchUpdate` 요청 중 하나라도 검증 실패 | 400, 전체 미적용 | batchUpdate 레퍼런스 |
| 쿼터 초과(사용자당 분당 60) | 429 `RESOURCE_EXHAUSTED` → 지수 백오프 | limits 문서 |
| 처리 180초 초과 | 타임아웃 에러 | limits 문서 |
| 보호 범위 안을 학생(UI)이 편집 | 거부 (UI 안내) | ProtectedRange 레퍼런스. 학생 계정 실측은 미실시 |
| 휴지통 · 기타 Drive 영역 | Docs와 동일 | `docs/google_docs.md` 7절 |

## 8. 쿼터 · rate limit · 플랜 제약

공식 limits 문서(2026-10-04 확인).

| 구분 | 프로젝트당 / 분 | 사용자당(프로젝트별) / 분 |
| --- | --- | --- |
| 읽기 요청 (`get`, `values.get`, `batchGet`…) | 300 | **60** |
| 쓰기 요청 (`create`, `batchUpdate`, `values.update`, `append`…) | 300 | **60** |

- 요청 수로 센다. 셀 수, 배치 안의 요청·범위 수는 무관하다. 그래서 **행 하나씩 `append`하지 않고 `values.batchUpdate`(또는 `append`에 여러 행) 한 번으로 보낸다.** 사용자당 분당 60은 Docs 읽기(300)보다 낮고 쓰기(60)와 같다.
- 페이로드: 하드 한도 없음, 2MB 이하 권장. 처리 시간 180초 초과 시 타임아웃.
- 429 → 지수 백오프 `min(2^n초 + 무작위 ms, 32~64초)`. Docs·Drive와 같은 패턴. `SheetsApiError.is_rate_limit`으로 분기한다.
- 요금: 무료. "쿼터 초과분에 대해 2026년 중 Cloud 결제 계정에 과금 계획" 문구는 Docs·Drive와 동일. 핸드오프 때 한 줄 알린다.
- Sheets 제품 한도(Drive 도움말): 스프레드시트당 **셀 2,000만 개 또는 100MB**. xlsx 변환 시 50,000자 넘는 셀은 삭제된다. 새 시트의 기본 격자는 1000행 × 26열(실측 에러 메시지)이고, 그 밖에 쓰려면 `appendDimension`/`insertDimension`이 먼저다. 열 수 한도(18,278열)와 셀당 문자 수(50,000)는 기억값 → 12절.
- Connected Sheets(BigQuery 등 `DataSource`)는 Workspace Enterprise 전용. 개인 계정 불가, 유즈케이스에 넣지 않는다.
- 개인 Google 계정이므로 그 외 Workspace 플랜 제약은 없다.

**유즈케이스별 호출 수 (그룹 g개, 그룹당 학생 m명, 2026-10-04 구현 기준)**

| 유즈케이스 | Sheets API | Drive API | 비고 |
| --- | --- | --- | --- |
| 1 폴더 생성 | 0 | 1 | |
| 2 템플릿 업로드 | 0 | 1 (`files.create` 변환) | 액티비티당 1회 |
| 2 그룹 시트 생성 + 치환 + 공유 (copy) | g × 1 (`batchUpdate`) | g × (1 `files.copy` + m `permissions.create`) | 30그룹 = Sheets 쓰기 30회 → 사용자당 분당 60 안. 60그룹을 넘기면 분산 |
| 2 (csv 방식) | 0 | g × (1 변환 업로드 + m) | Sheets 호출 없음 |
| 3 마감 처리 | 0 | g × (1 `permissions.list` + m `permissions.update`) | Docs와 동일 |
| 3 열 보호 (선택) | g × 1 | 0 | `list_sheets`로 sheetId를 모르면 +1 읽기 |
| 4 내보내기 | 0 | g × (1 `files.get` + 1 `files.export`) | |
| 5 값 읽기 | g × 1~2 (`get` + `values.get`) | 0 | `sheet_title`을 알면 1회. 30그룹 = 읽기 30~60회 → **분당 60 한도에 닿는다.** 마감 후 일괄 읽기는 그룹 사이에 1초 간격 또는 `sheet_id`→이름을 미리 저장해 `get`을 생략 |

## 9. 웹훅 (해당 시)

Sheets API에는 없다. 변경 감지는 Drive `changes.watch`/`changes.list` → `docs/google_drive.md` 9절. Drive 알림은 "파일이 바뀌었다"까지만 알려주므로, 어느 셀이 바뀌었는지 알려면 앱이 직전 스냅샷과 `values.get` 결과를 비교해야 한다. 확정 유즈케이스에 변경 감지는 없다.

## 10. 함정과 권장 패턴

공식 문서 기준이고, 실측으로 확인한 항목은 날짜를 붙였다.

1. **값과 서식은 다른 API.** 값만 다룰 때는 `values.*`(A1 표기, 2차원 배열). 서식·구조·보호·치환은 `spreadsheets.batchUpdate`(GridRange, 0 기반 반열림 인덱스). 두 좌표계 변환은 `mapper.py`의 `a1()`·`grid_range()`·`column_index()` 한 곳에 두었다.
2. **쓰기는 모아서.** 사용자당 분당 60회. `values.batchUpdate`로 여러 범위를 한 번에, 구조·서식 변경은 `batchUpdate` 하나에 요청 배열로. 값을 쓰는 유즈케이스가 생기면 "시트 전체를 한 번에 덮어쓰기"가 가장 단순하고 안전하다.
3. **`USER_ENTERED` vs `RAW` (2026-10-04 실측).** `RAW`는 `"0123456"`도 `"=SUM(B6:B9)"`도 문자열 그대로(수식 계산 안 됨). `USER_ENTERED`는 `0123456`→숫자 `123456`(앞자리 0 소실), 수식은 계산됨. 학번·전화번호 열은 `RAW`, 점수·수식은 `USER_ENTERED`. 템플릿에서는 해당 셀을 텍스트 서식(`numberFormat.type=TEXT`)으로 두면 변환 뒤에도 문자열이 유지된다(xlsx `@` 서식 → 보존 확인).
4. **날짜는 일련번호 (2026-10-04 실측).** `USER_ENTERED`로 넣은 `"2026-10-03"`을 `UNFORMATTED_VALUE`로 읽으면 `46298`. 1899-12-30 기준 일수이고 소수부는 시각. `FORMATTED_VALUE`면 로케일 문자열. 변환은 호출자가 하고, 생성 시 `locale: ko_KR`, `timeZone: Asia/Seoul`을 명시한다(`SheetsClient.create` 기본값).
5. **`append`의 "표" 탐지 (2026-10-04 실측).** 시트 이름만 주고 append하면, 1행 제목·2행 빈 줄·3행 헤더인 시트에서 **3행부터의 블록을 표로 찾아**(`tableRange` A3:C5) 그 다음 행(6행)에 썼다. 제목 줄이 있어도 빈 줄로 떨어져 있으면 표 탐지가 된다. 응답 `tableRange`·`updatedRange`로 실제 위치를 확인한다.
6. **A1 범위는 사용자가 행을 끼우면 어긋난다.** Docs의 `requiredRevisionId` 같은 낙관적 잠금이 없다. 행을 Synsory 레코드와 묶어야 하면 ① 첫 열에 ID를 넣고 쓰기 전에 `values.get`으로 위치를 다시 찾거나 ② developer metadata로 행에 ID를 붙이고 `*ByDataFilter`로 찾는다. 확정 유즈케이스(마감 후 읽기)는 전체를 읽으므로 해당 없음.
7. **`spreadsheets.get`은 기본이 구조만.** 값은 `values.get`으로 따로 읽는다. `SheetsClient.get`은 `STRUCTURE_FIELDS` 마스크로 시트 속성·보호 범위만 받는다. `includeGridData=true`는 작은 시트에서만.
8. **시트 이름에 공백·특수문자가 있으면 작은따옴표.** `a1()`이 항상 감싼다(`'팀 A'!A1:C3`, 이름 안의 `'`는 `''`). 실측에서 `'역할 분담 (학생이 이름 바꿈)'` 같은 이름도 통과.
9. **`sheetId`는 불변, 이름은 가변 (2026-10-04 실측).** 학생이 시트 이름을 바꾼 뒤 옛 이름으로 읽으면 400 "Unable to parse range", `sheet_id`로 읽으면 성공. 서비스는 생성 직후 `list_sheets`로 `sheet_id`를 저장하고 `read_sheet_values(sheet_id=…)`로 읽는다. **변환 업로드·복사된 파일의 sheetId는 0이 아니다**(실측: 484197496, 705952363). `sheetId=0`을 가정한 코드는 "No grid with id: 0"으로 실패한다.
10. **보호 범위 (2026-10-04 실측).** ① `editors`를 생략하면 Sheets가 **현재 문서 편집자 전원**(학생 writer 포함)을 편집 가능으로 넣어 보호가 아무도 막지 못한다. `editors.users=[]`로 보내야 소유자만 남는다. `protect_range_requests`는 항상 `editors`를 명시한다. ② 보호 중에도 소유자 토큰의 `values.update`는 200. 보호는 UI 편집 제한이고 API 쓰기 제한이 아니다(교수자가 Synsory로 채점 값을 쓰는 데 지장 없음). ③ 보기는 못 막는다. ④ `requestingUserCanEdit`는 소유자에게 항상 true. ⑤ 마감 처리의 기본은 Docs처럼 `permissions.update`이고, 보호 범위는 "일부 열만 잠그고 파일은 열어 둘" 때만 쓴다. 학생 계정에서 UI가 실제로 막히는지는 미실측(12절).
11. **템플릿은 "xlsx 1회 변환 업로드 → 그룹마다 `files.copy` → `findReplace`" (채택, 2026-10-04 실측).** 변환 뒤 굵게·데이터 검증(`NUMBER_BETWEEN 0~10`)·`SUM` 수식·텍스트 서식·틀 고정(5행)·시트 2장이 모두 보존됐다. `findReplace`(`allSheets=true`, `matchCase=true`, `includeFormulas=true`)는 모든 시트의 셀 텍스트와 **수식 안 태그**(`="{{team_name}} 평균: "&…` → `="A조 평균: "&…`)까지 바꿨다. 응답 `occurrencesChanged`가 태그별 치환 횟수(team_name 3 = 평가!A2 + 평가!A11 수식 + 역할 분담!A1). `files.copy`에 `parents`를 주면 사본이 바로 액티비티 폴더에 생긴다.
12. **CSV 변환 업로드 비교 (2026-10-04 실측).** 그룹당 Drive 1회로 가장 싸고 수식(`=SUM`)도 들어가지만, 시트 1장·검증 없음·서식 없음·틀 고정 없음이고 **`0123456`이 숫자 `123456`으로** 바뀐다. 값만 있는 단순 표에만 쓴다. 기본은 xlsx 방식.
13. **`UNFORMATTED_VALUE` 응답은 뒤쪽 빈 셀을 잘라낸다 (2026-10-04 실측).** `["소통", 8]`처럼 행 길이가 들쭉날쭉하고, 빈 행은 `[]`. 열 인덱스로 접근하기 전에 행을 열 수에 맞춰 채운다. 수식 에러는 `"#DIV/0! (…)"` 문자열로 온다.
14. **CSV 내보내기는 첫 시트만 (2026-10-04 실측).** csv·tsv 출력(268바이트)에 두 번째 시트가 없었다. 여러 시트가 필요하면 xlsx(13KB)나 시트마다 `values.get`.
15. **마감 처리는 Docs·Slides와 같다 (2026-10-04 실측).** 같은 함수 `close_submissions`(writer→commenter, 소유자 유지, 없는 ID는 그 파일만 404, 재실행은 0건), 되돌리기 `restore_editors`, 마감 뒤 교수자 `values.update` 200. Sheets API 호출 없음.
16. **SDK 없이 REST.** 쓰는 메서드는 `create`·`get`·`batchUpdate`·`values.{get,batchGet,update,batchUpdate,append,clear}`. httpx로 충분. 예외 근거 없음.
17. **Docs·Slides와 다른 점 정리.** 인덱스 밀림 없음(A1·GridRange 절대 좌표). 탭·objectId 대신 `sheetId`. 낙관적 잠금 없음. 읽기 쿼터가 가장 낮다(사용자당 60). 복사본의 `sheetId`가 0이 아니다. 보호 범위라는 중간 단계 잠금이 있다(단 기본 editors 함정).

## 11. 샘플 코드 (`usecases.py`의 흐름을 기준으로)

아래는 `app/services/google_sheets/usecases.py`·`app/services/google_drive/usecases.py`의 실제 함수 호출 순서다. FastAPI 없이 동작하며 `access_token`만 있으면 된다. 흐름은 "학기 초 1·2 → 마감 시각에 3·4·5"다.

```python
from app.services.google_sheets.client import SheetsClient
from app.services.google_sheets import usecases as sheets_uc
from app.services.google_drive.client import DriveClient
from app.services.google_drive import usecases as drive_uc

drive = DriveClient(access_token)   # 교수자 토큰. 만료됐으면 호출 전에 refresh
sheets = SheetsClient(access_token)

# 1. 액티비티 폴더 (Docs와 같음)
folder = await drive_uc.create_folder(drive, "동료 평가 1차", parent_folder_id=course_folder_id)

# 2-1. Synsory가 보관하는 xlsx 템플릿을 Sheets로 변환 업로드. 액티비티당 1회. 태그는 공백 없이 {{team_name}}
template = await sheets_uc.upload_template(drive, "[템플릿] 동료 평가 1차", xlsx_bytes, folder_id=folder.id)

# 2-2. 그룹마다 복사 → 태그 치환(batchUpdate 1회) → 그룹원 writer 공유. 그룹·이메일 단위로 부분 실패해도 계속
results = await sheets_uc.create_group_sheets(
    sheets, drive,
    folder_id=folder.id,
    activity_name="동료 평가 1차",
    title_template="{{activity_name}} - {{team_name}}",
    groups=[
        sheets_uc.GroupSpec("A조", ["a1@gmail.com", "a2@gmail.com"]),
        sheets_uc.GroupSpec("B조", ["b1@gmail.com"]),
    ],
    template_spreadsheet_id=template.id,     # 또는 csv_template="팀,{{team_name}}\n..." (값만 있는 표일 때)
    due="2026-10-10 23:59",
    notify=False,
)
for r in results:
    if r.document is None:          # 복사 실패 (템플릿 ID 오류 등)
        ...
    elif r.error:                   # 복사는 됐는데 치환 실패 → 사본 정리 또는 재시도
        ...
    else:
        infos = await sheets_uc.list_sheets(sheets, r.document.id)       # sheetId는 0이 아니다. 이름 대신 이걸 저장
        save(team=r.team_name, spreadsheet_id=r.document.id, url=r.document.url,
             sheet_ids={i.title: i.sheet_id for i in infos})
        if 0 in r.replaced.values(): warn_template(r.replaced)           # 템플릿에 없는 태그
        for sh in r.shares:
            if not sh.ok: ...        # 예: Google 계정 아닌 이메일 → 400 invalidSharingRequest

# 3. 마감 시각 (스케줄러). Docs와 같은 함수. 학생 writer → commenter. 재실행 안전
closed = await sheets_uc.close_submissions(drive, [...], to_role="commenter", keep_emails=["ta@gmail.com"])

# 3'. 선택지: 파일은 열어 두고 학생 입력 열만 보호 (editors는 항상 명시된다 → 소유자 + editor_emails만 편집)
protected_ids = await sheets_uc.lock_ranges(sheets, spreadsheet_id, sheet_id=eval_sheet_id, cell_ranges=["B6:C9"], description="마감")
# 해제(마감 연장): await sheets_uc.unlock_ranges(sheets, spreadsheet_id, protected_ids)

# 4. 제출본 확보. 반드시 3 다음에
exported = await sheets_uc.export_spreadsheet(drive, spreadsheet_id, fmt="xlsx")   # xlsx | pdf | csv(첫 시트만) | ods | tsv | zip

# 5. 값 읽기 → DB 반영. sheet_id로 읽어 이름 변경에 영향받지 않게. UNFORMATTED: 숫자는 숫자, 날짜는 일련번호, 빈 셀은 잘림
sv = await sheets_uc.read_sheet_values(sheets, spreadsheet_id, sheet_id=eval_sheet_id, cell_range="A6:C9")
for row in sv.values:
    row += [""] * (3 - len(row))                 # 뒤쪽 빈 셀 채우기
    item, score, note = row
    if isinstance(score, str) and score.startswith("#"): ...   # 수식 에러 값
    save_score(team, item, score, note)

# 보조: 구조 + 전체 값 평문 (Document.text). 트러블슈팅용
doc = await sheets_uc.read_spreadsheet(sheets, drive, spreadsheet_id, include_values=True)
```

에러는 `DriveApiError`(`status`, `reason`, `message`, `is_rate_limit`)와 `SheetsApiError`(`status`, `status_text`, `message`, `is_rate_limit`)로 올라온다. `is_rate_limit`이면 지수 백오프로 재시도하고, 그 외 4xx는 7절 표로 분기한다. 토큰 만료(401)는 client가 처리하지 않으므로 호출 전에 갱신한다.

## 12. 미확인 · 보류 항목

| 항목 | 확인 방법 · 시점 |
| --- | --- |
| 열 수 한도 18,278, 셀당 문자 50,000 | 기억값. Drive 도움말에는 "2,000만 셀 또는 100MB"와 변환 시 50,000자 삭제만 명시. 유즈케이스가 큰 시트를 다루지 않으면 보류 |
| 보호 범위가 **학생 계정 UI**에서 실제로 편집을 막는지(소유자 API는 안 막힘 확인) | 테스트 Google 계정으로 로그인해 보호 셀 편집 시도. 열 보호 방식을 채택할 때만 |
| 보호 범위 `editors.users`에 파일 편집권이 없는 이메일을 넣으면 에러인지 무시인지 | 열 보호 방식을 채택할 때만 |
| `findReplace`가 데이터 검증 목록(`ONE_OF_LIST`) 값·시트 이름·이름 범위 안의 태그도 바꾸는지 | 템플릿에 그런 태그가 생기면 |
| xlsx 변환 시 조건부 서식·드롭다운(`ONE_OF_LIST`)·열 너비·병합 셀 보존 | 굵게·`NUMBER_BETWEEN` 검증·수식·텍스트 서식·틀 고정은 확인. 템플릿에 들어가면 확인 |
| `due`에 날짜 문자열 대신 Sheets 날짜 셀을 만들고 싶을 때 `USER_ENTERED` + `locale=ko_KR` 파싱 | 변환 업로드 파일의 locale이 ko_KR인지도 함께. 현재는 `마감: 2026-10-10 23:59` 문자열 |
| 댓글 API(2026-09-30 GA)가 `drive.file`로 되는지, 응답에 이메일이 포함되는지 | 유즈케이스에 댓글이 들어갈 때만 |
| `batchUpdate` 요청 개수 상한 | 공식 문서에 수치 없음. 2MB 권장 페이로드만. 보류 |
| 5번 유즈케이스를 그룹 수십 개에 일괄 실행할 때 분당 60 읽기 한도 | 30그룹 × 2회 = 60. 실측은 그룹 3개. `sheet_title`을 저장해 `get`을 생략하거나 간격을 두는 쪽으로 설계 |
| 2026년 중 쿼터 초과 과금 계획의 실제 시행 여부 | 핸드오프 직전 재확인(Docs와 공통) |
| ~~보호 범위가 소유자 토큰의 API 쓰기를 막는지~~ | 확인 완료(2026-10-04): 막지 않는다(200). 10절 10항 |
| ~~`findReplace`가 수식 안 태그도 치환하는지~~ | 확인 완료(2026-10-04): `includeFormulas=true`로 치환됨 |
| ~~xlsx 변환 업로드 뒤 데이터 검증·수식·틀 고정 보존~~ | 확인 완료(2026-10-04): 보존됨. 10절 11항 |
| ~~`drive.file` 경계가 Sheets에서도 같은지~~ | 확인 완료(2026-10-04): 사용자 폴더(`manual-test`) ID만으로 그 안에 액티비티 폴더·시트 생성 가능. Drive 실측과 동일 |
| ~~잘못된 A1 범위 에러의 실제 상태 코드·메시지~~ | 확인 완료(2026-10-04): 400 `INVALID_ARGUMENT` "Unable to parse range". 7절 |
| 성적표 동기화(`create_gradebook` 등) | **보류**(1.3절). 교수자 요구가 확인되면 내보내기부터 |

## 출처 (2026-10-04 확인)

- Sheets API Usage limits — https://developers.google.com/workspace/sheets/api/limits
- Sheets API scopes — https://developers.google.com/workspace/sheets/api/scopes
- REST 리소스 목록 — https://developers.google.com/workspace/sheets/api/reference/rest
- spreadsheets.create / get / batchUpdate — https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets
- spreadsheets.values (get, update, append…) — https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets.values
- spreadsheets.sheets.copyTo — https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets.sheets/copyTo
- Request 타입(batchUpdate) — https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets/request
- Sheets 리소스(SheetProperties, ProtectedRange) — https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets/sheets
- 개념(ID, A1 표기) — https://developers.google.com/workspace/sheets/api/guides/concepts
- 값 읽기·쓰기 가이드 — https://developers.google.com/workspace/sheets/api/guides/values
- batchUpdate 가이드 — https://developers.google.com/workspace/sheets/api/guides/batchupdate
- 표(Tables) 가이드 — https://developers.google.com/workspace/sheets/api/guides/tables
- 날짜·숫자 형식 — https://developers.google.com/workspace/sheets/api/guides/formats
- Developer metadata — https://developers.google.com/workspace/sheets/api/guides/metadata
- 릴리스 노트 — https://developers.google.com/workspace/sheets/release-notes
- Drive 내보내기 형식 — https://developers.google.com/workspace/drive/api/guides/ref-export-formats
- Drive 업로드·변환 — https://developers.google.com/workspace/drive/api/guides/manage-uploads
- Sheets 제품 한도(Drive 도움말) — https://support.google.com/drive/answer/37603
