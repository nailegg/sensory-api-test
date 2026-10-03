"""Google Slides scope 목록. docs/google_slides.md 3절.

`presentations.create` · `get` · `batchUpdate` · `pages.get` · `pages.getThumbnail`은 모두 `drive.file`(google_drive/scopes.py)로
동작하므로 앱이 직접 만든(또는 앱이 변환 업로드·복사한) 프레젠테이션만 다루는 동안 이 목록은 비어 있다.
교수자의 기존 덱을 Picker 없이 다루려면 `presentations.readonly` / `presentations`(민감),
Sheets 차트를 연결 상태로 넣으려면 `spreadsheets.readonly`(민감)를 여기에 추가한다. 추가하면 사용자가 재동의해야 한다.
"""

PROVIDER = "google"

SCOPES: dict[str, str] = {}
