"""Google Drive scope 목록과 사용 이유. core/oauth.py가 모아서 인가 요청을 만든다.

scope 등급과 선택 근거는 docs/google_drive.md 3절.
"""

PROVIDER = "google"

SCOPES: dict[str, str] = {
    "https://www.googleapis.com/auth/drive.file": (
        "앱이 만든 파일과 사용자가 선택기로 공유한 파일에만 접근. "
        "Docs·Sheets·Slides·Forms 생성·편집, 폴더 지정, 메타데이터 조회, 내보내기, 변경 감지에 쓴다. "
        "비민감 등급이라 CASA 평가 대상이 아니다."
    ),
}
