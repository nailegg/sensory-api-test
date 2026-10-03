"""Google Sheets REST 호출만 (spreadsheets.* / spreadsheets.values.*). Drive 호출은 google_drive/client.py에.

함정 (docs/google_sheets.md 10절):
- 값(`values.*`, A1 표기)과 구조·서식·보호(`batchUpdate`, GridRange 0 기반 반열림 인덱스)는 다른 API다.
- 읽기·쓰기 모두 사용자당 분당 60회이고 요청 수로 센다. 셀 수·배치 안의 요청 수는 무관 → 모아서 보낸다.
- `spreadsheets.create`는 폴더를 못 정한다. 폴더 지정은 Drive로.
- `spreadsheets.get`은 기본이 구조만이다. 값은 `values.get`으로 따로 읽는다.
"""

import httpx

BASE_URL = "https://sheets.googleapis.com/v4"

# spreadsheets.get에서 구조만 받을 때의 마스크. includeGridData=true는 큰 시트에서 180초 타임아웃 위험.
STRUCTURE_FIELDS = "spreadsheetId,spreadsheetUrl,properties(title,locale,timeZone),sheets(properties(sheetId,title,index,sheetType,hidden,gridProperties(rowCount,columnCount,frozenRowCount,frozenColumnCount)),protectedRanges(protectedRangeId,range,description,warningOnly,editors,requestingUserCanEdit))"


class SheetsApiError(Exception):
    def __init__(self, status: int, body: dict):
        self.status = status
        self.body = body
        err = body.get("error", {}) if isinstance(body, dict) else {}
        self.message: str = err.get("message", str(body))
        self.status_text: str | None = err.get("status")  # 예: INVALID_ARGUMENT, NOT_FOUND, RESOURCE_EXHAUSTED
        super().__init__(f"Sheets {status} {self.status_text}: {self.message}")

    @property
    def is_rate_limit(self) -> bool:
        return self.status == 429 or self.status_text == "RESOURCE_EXHAUSTED"


class SheetsClient:
    def __init__(self, access_token: str, http: httpx.AsyncClient | None = None):
        self._headers = {"Authorization": f"Bearer {access_token}"}
        self._http = http or httpx.AsyncClient(timeout=30)

    async def _request(self, method: str, url: str, **kwargs) -> dict:
        resp = await self._http.request(method, url, headers=self._headers, **kwargs)
        if resp.status_code >= 400:
            try:
                body = resp.json()
            except ValueError:
                body = {"error": {"message": resp.text}}
            raise SheetsApiError(resp.status_code, body)
        return resp.json()

    # --- spreadsheets ---

    async def create(
        self,
        title: str,
        sheet_titles: list[str] | None = None,
        locale: str = "ko_KR",
        time_zone: str = "Asia/Seoul",
    ) -> dict:
        """spreadsheets.create (쓰기 쿼터). 제목·로케일·시간대·시트 이름까지 한 번에. 폴더는 못 정한다(Drive로 이동).
        locale·timeZone은 날짜 표시값과 USER_ENTERED 파싱에 영향을 주므로 생성 시 명시한다."""
        body: dict = {"properties": {"title": title, "locale": locale, "timeZone": time_zone}}
        if sheet_titles:
            body["sheets"] = [{"properties": {"title": t, "index": i}} for i, t in enumerate(sheet_titles)]
        return await self._request("POST", f"{BASE_URL}/spreadsheets", json=body)

    async def get(self, spreadsheet_id: str, fields: str | None = STRUCTURE_FIELDS, ranges: list[str] | None = None) -> dict:
        """spreadsheets.get (읽기 쿼터). 기본은 구조만(STRUCTURE_FIELDS). fields=None이면 전체(gridData 제외)."""
        params: dict = {}
        if fields:
            params["fields"] = fields
        if ranges:
            params["ranges"] = ranges
        return await self._request("GET", f"{BASE_URL}/spreadsheets/{spreadsheet_id}", params=params or None)

    async def batch_update(self, spreadsheet_id: str, requests: list[dict], include_spreadsheet_in_response: bool = False) -> dict:
        """spreadsheets.batchUpdate (쓰기 쿼터 1회, 안의 요청 수 무관). 값 외 모든 변경(구조·서식·보호·치환).
        requests 전체가 원자적으로 적용되고 하나라도 검증 실패면 전체 거부. replies[]는 requests와 1:1."""
        body: dict = {"requests": requests}
        if include_spreadsheet_in_response:
            body["includeSpreadsheetInResponse"] = True
        return await self._request("POST", f"{BASE_URL}/spreadsheets/{spreadsheet_id}:batchUpdate", json=body)

    # --- spreadsheets.values ---

    async def get_values(
        self,
        spreadsheet_id: str,
        a1_range: str,
        value_render_option: str = "UNFORMATTED_VALUE",
        date_time_render_option: str = "SERIAL_NUMBER",
        major_dimension: str = "ROWS",
    ) -> dict:
        """values.get (읽기 쿼터). 기본 UNFORMATTED_VALUE: 숫자는 숫자, 날짜는 1899-12-30 기준 일련번호.
        FORMATTED_VALUE면 화면 문자열("1,234"), FORMULA면 수식 문자열. 뒤쪽 빈 행·빈 셀은 잘려서 온다."""
        params = {
            "valueRenderOption": value_render_option,
            "dateTimeRenderOption": date_time_render_option,
            "majorDimension": major_dimension,
        }
        return await self._request("GET", f"{BASE_URL}/spreadsheets/{spreadsheet_id}/values/{a1_range}", params=params)

    async def batch_get_values(
        self, spreadsheet_id: str, a1_ranges: list[str], value_render_option: str = "UNFORMATTED_VALUE"
    ) -> dict:
        """values.batchGet (읽기 쿼터 1회, 범위 수 무관). 응답 valueRanges[]는 요청 순서."""
        params = {"ranges": a1_ranges, "valueRenderOption": value_render_option}
        return await self._request("GET", f"{BASE_URL}/spreadsheets/{spreadsheet_id}/values:batchGet", params=params)

    async def update_values(
        self, spreadsheet_id: str, a1_range: str, values: list[list], value_input_option: str = "RAW"
    ) -> dict:
        """values.update (쓰기 쿼터). 범위 덮어쓰기. RAW: 문자열 그대로(학번 "0123" 유지, 수식도 문자).
        USER_ENTERED: UI 입력처럼 파싱(수식 계산, 숫자·날짜 자동 인식 → 앞자리 0 소실)."""
        params = {"valueInputOption": value_input_option}
        body = {"range": a1_range, "majorDimension": "ROWS", "values": values}
        return await self._request("PUT", f"{BASE_URL}/spreadsheets/{spreadsheet_id}/values/{a1_range}", params=params, json=body)

    async def batch_update_values(
        self, spreadsheet_id: str, data: list[tuple[str, list[list]]], value_input_option: str = "RAW"
    ) -> dict:
        """values.batchUpdate (쓰기 쿼터 1회, 범위 수 무관). 여러 범위를 한 번에 → 쿼터(사용자당 분당 60)의 기본 대응."""
        body = {
            "valueInputOption": value_input_option,
            "data": [{"range": a1, "majorDimension": "ROWS", "values": values} for a1, values in data],
        }
        return await self._request("POST", f"{BASE_URL}/spreadsheets/{spreadsheet_id}/values:batchUpdate", json=body)

    async def append_values(
        self,
        spreadsheet_id: str,
        a1_range: str,
        values: list[list],
        value_input_option: str = "RAW",
        insert_data_option: str = "INSERT_ROWS",
    ) -> dict:
        """values.append (쓰기 쿼터). a1_range 안에서 "표"를 찾아 그 다음 행에 쓴다. 응답 tableRange가 찾은 표.
        한 번에 여러 행을 넘긴다(행마다 호출하지 않는다)."""
        params = {"valueInputOption": value_input_option, "insertDataOption": insert_data_option}
        body = {"range": a1_range, "majorDimension": "ROWS", "values": values}
        return await self._request(
            "POST", f"{BASE_URL}/spreadsheets/{spreadsheet_id}/values/{a1_range}:append", params=params, json=body
        )

    async def clear_values(self, spreadsheet_id: str, a1_range: str) -> dict:
        """values.clear (쓰기 쿼터). 값만 지우고 서식·검증은 남긴다."""
        return await self._request("POST", f"{BASE_URL}/spreadsheets/{spreadsheet_id}/values/{a1_range}:clear", json={})
