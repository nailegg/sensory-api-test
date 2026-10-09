import { z } from 'zod';
import type { GoogleSheetsPort, SheetInfo } from '../../application/src/index.ts';
import {
  externalRequest,
  readJson,
  type AccessToken,
  type ExternalRequest,
  type HttpOptions,
} from './external-http.ts';
import { batchUpdateReplies, tag, tagCounts } from './google-tags.ts';

// Google Sheets v4 어댑터. synsory-api app/services/google_sheets/client.py + mapper.py(좌표)
// + usecases(태그 치환)의 이식본. 값 읽기(유즈케이스 5)는 2026-10-09 유즈케이스 삭제로 뺐다. 함정은 synsory-api docs/google_sheets.md 10절.
// 보호 범위(lock_ranges)는 보류 기능이라 옮기지 않았다(docs/google_sheets.md 1절 메모 3).

const BASE_URL = 'https://sheets.googleapis.com/v4';
// 구조만 받는다. includeGridData는 큰 시트에서 180초 타임아웃 위험.
const SHEETS_FIELDS = 'sheets(properties(sheetId,title,index))';

// ---------- 좌표 ----------

// 0 기반 열 인덱스 → 열 문자. 0→A, 25→Z, 26→AA.
export function columnLetter(index: number): string {
  let letters = '';
  for (let n = index + 1; n > 0; n = Math.floor((n - 1) / 26))
    letters = String.fromCharCode(65 + ((n - 1) % 26)) + letters;
  return letters;
}

// '시트 이름'!A1:C3. 이름 안의 작은따옴표는 두 번 쓴다. 항상 감싸도 Sheets는 받아들인다.
export function a1(sheetTitle: string, cellRange?: string): string {
  const quoted = `'${sheetTitle.replaceAll("'", "''")}'`;
  return cellRange ? `${quoted}!${cellRange}` : quoted;
}

const sheetList = z.object({
  sheets: z
    .array(
      z.object({
        properties: z.object({
          sheetId: z.number().default(0),
          title: z.string(),
          index: z.number().default(0),
        }),
      }),
    )
    .default([]),
});

export function createGoogleSheets(
  accessToken: AccessToken,
  options: HttpOptions = {},
): GoogleSheetsPort {
  const call = async (request: ExternalRequest) =>
    externalRequest('google', await accessToken(), request, options);
  const batchUpdate = async (spreadsheetId: string, requests: unknown[]) =>
    (
      await readJson(
        await call({
          method: 'POST',
          url: `${BASE_URL}/spreadsheets/${spreadsheetId}:batchUpdate`,
          json: { requests },
        }),
        batchUpdateReplies,
      )
    ).replies;
  async function listSheets(spreadsheetId: string): Promise<SheetInfo[]> {
    const data = await readJson(
      await call({
        method: 'GET',
        url: `${BASE_URL}/spreadsheets/${spreadsheetId}`,
        query: { fields: SHEETS_FIELDS },
      }),
      sheetList,
    );
    return data.sheets
      .map(({ properties: p }) => ({
        sheet_id: p.sheetId,
        title: p.title,
        index: p.index,
      }))
      .sort((a, b) => a.index - b.index);
  }
  const valuesUrl = (spreadsheetId: string, range: string) =>
    `${BASE_URL}/spreadsheets/${spreadsheetId}/values/${encodeURIComponent(range)}`;

  return {
    async replaceTags(spreadsheetId, variables) {
      const requests = Object.entries(variables).map(([key, value]) => ({
        findReplace: {
          find: tag(key),
          replacement: value,
          matchCase: true,
          allSheets: true,
          // ="{{team_name}} 합계" 같은 수식 안 태그도 바꾼다.
          includeFormulas: true,
        },
      }));
      return tagCounts(variables, await batchUpdate(spreadsheetId, requests), 'findReplace');
    },

    // spreadsheets.create. locale·timeZone은 날짜 표시와 USER_ENTERED 파싱에 영향을 주므로 명시한다.
    async create(title, firstSheetTitle) {
      const response = await call({
        method: 'POST',
        url: `${BASE_URL}/spreadsheets`,
        json: {
          properties: { title, locale: 'ko_KR', timeZone: 'Asia/Seoul' },
          sheets: [{ properties: { title: firstSheetTitle, index: 0 } }],
        },
      });
      return (await readJson(response, z.object({ spreadsheetId: z.string() }))).spreadsheetId;
    },

    listSheets,

    async writeValues(spreadsheetId, sheetTitle, cellRange, values) {
      const range = a1(sheetTitle, cellRange);
      await call({
        method: 'PUT',
        url: valuesUrl(spreadsheetId, range),
        query: { valueInputOption: 'RAW' },
        json: { range, majorDimension: 'ROWS', values },
      });
    },

    async clearColumns(spreadsheetId, sheetTitle, columns) {
      const range = a1(sheetTitle, `A:${columnLetter(columns - 1)}`);
      await call({ method: 'POST', url: `${valuesUrl(spreadsheetId, range)}:clear`, json: {} });
    },

  };
}
