"""Sheets 응답 dict (+ Drive 메타데이터) → core/models 순수 변환, 그리고 A1 ↔ GridRange 좌표 헬퍼.

네트워크 호출도 client import도 없다. 좌표 헬퍼를 여기 두는 이유: values.*(A1)와 batchUpdate(GridRange)를
오가는 변환이 usecases 여러 곳에서 필요하고, 순수 함수라 테스트하기 쉽다.
"""

import re

from app.core.models import Document, DocumentKind
from app.services.google_drive.mapper import document_from_drive_file

# ---------- 좌표 ----------


def column_letter(index: int) -> str:
    """0 기반 열 인덱스 → 열 문자. 0→A, 25→Z, 26→AA."""
    if index < 0:
        raise ValueError("column index must be >= 0")
    letters = ""
    n = index + 1
    while n:
        n, rem = divmod(n - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def column_index(letters: str) -> int:
    """열 문자 → 0 기반 인덱스. A→0, Z→25, AA→26."""
    if not letters or not letters.isalpha():
        raise ValueError(f"invalid column letters: {letters!r}")
    n = 0
    for ch in letters.upper():
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def quote_sheet_title(title: str) -> str:
    """A1 표기에 넣을 시트 이름. 공백·특수문자가 있으면 작은따옴표로 감싸고, 이름 안의 작은따옴표는 두 번 쓴다.
    항상 감싸도 Sheets는 받아들이므로 단순화를 위해 항상 감싼다."""
    return "'" + title.replace("'", "''") + "'"


def a1(sheet_title: str, cell_range: str | None = None) -> str:
    """`'시트 이름'!A1:C3`. cell_range가 없으면 시트 전체(`'시트 이름'`)."""
    quoted = quote_sheet_title(sheet_title)
    return f"{quoted}!{cell_range}" if cell_range else quoted


_CELL = re.compile(r"^([A-Za-z]*)(\d*)$")


def grid_range(sheet_id: int, cell_range: str) -> dict:
    """A1 셀 범위(시트 이름 없이, 예 "B6:B9", "A:B", "2:2", "C5") → GridRange(0 기반, end는 반열림).
    열만("A:B")·행만("2:2") 지정하면 그 축은 무한(해당 start/end 생략). batchUpdate(보호 범위·서식 등)에 쓴다."""
    parts = cell_range.split(":")
    if len(parts) == 1:
        parts = [parts[0], parts[0]]
    if len(parts) != 2:
        raise ValueError(f"invalid range: {cell_range!r}")
    (c1, r1), (c2, r2) = (_cell_parts(parts[0]), _cell_parts(parts[1]))
    gr: dict = {"sheetId": sheet_id}
    if c1 and c2:
        gr["startColumnIndex"] = column_index(c1)
        gr["endColumnIndex"] = column_index(c2) + 1
    if r1 and r2:
        gr["startRowIndex"] = int(r1) - 1
        gr["endRowIndex"] = int(r2)
    if not (c1 or r1):
        raise ValueError(f"invalid range: {cell_range!r}")
    return gr


def _cell_parts(cell: str) -> tuple[str, str]:
    m = _CELL.match(cell)
    if not m or not cell:
        raise ValueError(f"invalid cell: {cell!r}")
    return m.group(1), m.group(2)


# ---------- 구조 ----------


def sheet_titles(spreadsheet: dict) -> dict[int, str]:
    """`spreadsheets.get` 응답 → {sheetId: title}. sheetId는 불변, 이름은 사용자가 바꿀 수 있어 저장 식별자는 sheetId다."""
    return {s["properties"]["sheetId"]: s["properties"]["title"] for s in spreadsheet.get("sheets", []) if "properties" in s}


def first_sheet_title(spreadsheet: dict) -> str | None:
    sheets = sorted(spreadsheet.get("sheets", []), key=lambda s: s.get("properties", {}).get("index", 0))
    return sheets[0]["properties"]["title"] if sheets else None


# ---------- 값 → 평문 ----------


def _cell_text(v) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def plain_text(value_ranges: list[dict], titles: dict[str, str] | None = None) -> str:
    """values.batchGet의 valueRanges[] → 시트마다 `[시트 이름]` 줄 뒤에 탭 구분 행. 시트 사이는 빈 줄.
    titles는 {응답 range의 시트 부분: 표시 이름}이 필요할 때만(기본은 range 문자열의 시트 이름을 그대로)."""
    chunks: list[str] = []
    for vr in value_ranges:
        rng = vr.get("range", "")
        sheet = rng.split("!")[0].strip("'").replace("''", "'")
        name = (titles or {}).get(sheet, sheet)
        rows = ["\t".join(_cell_text(c) for c in row) for row in vr.get("values", [])]
        chunks.append(f"[{name}]\n" + "\n".join(rows))
    return "\n\n".join(chunks)


# ---------- Document ----------


def document_from_spreadsheet(spreadsheet: dict, drive_file: dict | None = None, text: str | None = None) -> Document:
    """Sheets `spreadsheets.get`/`create` 응답 + Drive `files.get` 응답 → Document.

    owner·created_at·modified_at·parent_folder_id·trashed·locked는 Drive에서만 온다. drive_file이 없으면 비어 있고
    url은 Sheets의 spreadsheetUrl로 채운다.
    """
    title = (spreadsheet.get("properties") or {}).get("title")
    if drive_file:
        document = document_from_drive_file(drive_file, text=text)
        return document.model_copy(update={"title": title or document.title, "kind": DocumentKind.SHEET})
    return Document(
        id=spreadsheet["spreadsheetId"],
        kind=DocumentKind.SHEET,
        title=title or "",
        url=spreadsheet.get("spreadsheetUrl"),
        text=text,
    )
