"""Google Forms scope 목록. docs/google_forms.md 3절.

forms.create · get · batchUpdate · setPublishSettings · responses.* · watches.* 모두 `drive.file`(google_drive/scopes.py)로
동작하므로 앱이 직접 만든 폼만 다루는 동안 이 목록은 비어 있다.
교수자가 Forms UI에서 만든 폼을 Picker 없이 다뤄야 하면 `forms.body` / `forms.body.readonly` / `forms.responses.readonly`
(민감 등급)를 여기에 추가한다. 추가하면 사용자가 재동의해야 한다.
"""

PROVIDER = "google"

SCOPES: dict[str, str] = {}
