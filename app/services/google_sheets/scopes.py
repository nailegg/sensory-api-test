"""Google Sheets scope 목록. docs/google_sheets.md 3절.

`spreadsheets.create` · `get` · `batchUpdate` · `values.*` · `sheets.copyTo`는 모두 `drive.file`(google_drive/scopes.py)로
동작하므로 앱이 직접 만든(또는 앱이 변환 업로드·복사한) 스프레드시트만 다루는 동안 이 목록은 비어 있다.
교수자가 이미 가진 시트(명단·성적표)를 Picker 없이 읽거나 편집해야 하면 `spreadsheets.readonly` / `spreadsheets`(민감 등급)를
여기에 추가한다. 추가하면 사용자가 재동의해야 한다.
"""

PROVIDER = "google"

SCOPES: dict[str, str] = {}
