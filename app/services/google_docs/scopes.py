"""Google Docs scope 목록. docs/google_docs.md 3절.

`documents.create` · `get` · `batchUpdate`는 모두 `drive.file`(google_drive/scopes.py)로 동작하므로
앱이 직접 만든 문서만 다루는 동안 이 목록은 비어 있다.
사용자가 이미 가진 문서를 Picker 없이 읽거나 편집해야 하면 `documents.readonly` / `documents`(민감 등급)를
여기에 추가한다. 추가하면 사용자가 재동의해야 한다.
"""

PROVIDER = "google"

SCOPES: dict[str, str] = {}
