import { z } from 'zod';
import { AppError } from '../../domain/src/index.ts';
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
// + usecases(태그 치환·보호 범위·값 읽기)의 이식본. 함정은 synsory-api docs/google_sheets.md 10절.

const BASE_URL = 'https://sheets.googleapis.com/v4';
// 구조만 받는다. includeGridData는 큰 시트에서 180초 타임아웃 위험.
const SHEETS_FIELDS = 'sheets(properties(sheetId,title,index,hidden))';

// ---------- 좌표 ----------

// 0 기반 열 인덱스 → 열 문자. 0→A, 25→Z, 26→AA.
export function columnLetter(index: number): string {
  let letters = '';
  for (let n = index + 1; n > 0; n = Math.floor((n - 1) / 26))
    letters = String.fromCharCode(65 + ((n - 1) % 26)) + letters;
  return letters;
}

// 열 문자 → 0 기반 인덱스. A→0, Z→25, AA→26.
export function columnIndex(letters: string): number {
  if (!/^[A-Za-z]+$/.test(letters)) throw new RangeError(`열 문자가 아닙니다: ${letters}`);
  return [...letters.toUpperCase()].reduce((n, ch) => n * 26 + ch.charCodeAt(0) - 64, 0) - 1;
}

// '시트 이름'!A1:C3. 이름 안의 작은따옴표는 두 번 쓴다. 항상 감싸도 Sheets는 받아들인다.
export function a1(sheetTitle: string, cellRange?: string): string {
  const quoted = `'${sheetTitle.replaceAll("'", "''")}'`;
  return cellRange ? `${quoted}!${cellRange}` : quoted;
}

// A1 셀 범위(시트 이름 없이: "B6:B9", "A:B", "2:2", "C5") → GridRange(0 기반, end는 반열림).
// 열만·행만 지정하면 그 축은 무한(해당 start/end 생략).
export function gridRange(sheetId: number, cellRange: string): Record<string, number> {
  const parts = cellRange.split(':');
  const [from, to] = parts.length === 1 ? [parts[0], parts[0]] : parts;
  const cell = (c: string | undefined) => /^([A-Za-z]*)(\d*)$/.exec(c ?? '');
  const start = cell(from);
  const end = cell(to);
  if (parts.length > 2 || !from || !start || !end || !(start[1] || start[2]))
    throw new RangeError(`범위가 아닙니다: ${cellRange}`);
  const range: Record<string, number> = { sheetId };
  if (start[1] && end[1]) {
    range['startColumnIndex'] = columnIndex(start[1]);
    range['endColumnIndex'] = columnIndex(end[1]) + 1;
  }
  if (start[2] && end[2]) {
    range['startRowIndex'] = Number(start[2]) - 1;
    range['endRowIndex'] = Number(end[2]);
  }
  return range;
}

// addProtectedRange 요청. editors를 항상 명시한다(users: [] = 소유자만).
export function protectRangeRequests(
  sheetId: number,
  cellRanges: string[],
  description: string,
  editorEmails: string[] = [],
) {
  return cellRanges.map((r) => ({
    addProtectedRange: {
      protectedRange: {
        description,
        warningOnly: false,
        editors: { users: editorEmails },
        range: gridRange(sheetId, r),
      },
    },
  }));
}

const sheetList = z.object({
  sheets: z
    .array(
      z.object({
        properties: z.object({
          sheetId: z.number().default(0),
          title: z.string(),
          index: z.number().default(0),
          hidden: z.boolean().default(false),
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
        hidden: p.hidden,
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
    async create(title, sheetTitles) {
      const response = await call({
        method: 'POST',
        url: `${BASE_URL}/spreadsheets`,
        json: {
          properties: { title, locale: 'ko_KR', timeZone: 'Asia/Seoul' },
          ...(sheetTitles?.length && {
            sheets: sheetTitles.map((t, index) => ({ properties: { title: t, index } })),
          }),
        },
      });
      return (await readJson(response, z.object({ spreadsheetId: z.string() }))).spreadsheetId;
    },

    listSheets,

    // sheetId로 고르면 spreadsheets.get + values.get(2회), 안 고르면 첫 시트(같은 2회).
    async readValues(spreadsheetId, { sheetId, cellRange } = {}) {
      const sheets = await listSheets(spreadsheetId);
      const sheet = sheetId === undefined ? sheets[0] : sheets.find((s) => s.sheet_id === sheetId);
      if (!sheet) throw new AppError('SHEET_NOT_FOUND', 404, '시트를 찾을 수 없습니다.');
      const response = await call({
        method: 'GET',
        url: valuesUrl(spreadsheetId, a1(sheet.title, cellRange)),
        query: {
          valueRenderOption: 'UNFORMATTED_VALUE',
          dateTimeRenderOption: 'SERIAL_NUMBER',
          majorDimension: 'ROWS',
        },
      });
      const data = await readJson(
        response,
        z.object({
          range: z.string().default(''),
          values: z.array(z.array(z.unknown())).default([]),
        }),
      );
      return { sheet_id: sheet.sheet_id, sheet_title: sheet.title, ...data };
    },

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

    async lockRanges(
      spreadsheetId,
      sheetId,
      cellRanges,
      { description = '마감', editorEmails } = {},
    ) {
      const replies = await batchUpdate(
        spreadsheetId,
        protectRangeRequests(sheetId, cellRanges, description, editorEmails),
      );
      return replies.map(
        (r) =>
          (r['addProtectedRange'] as { protectedRange: { protectedRangeId: number } })
            .protectedRange.protectedRangeId,
      );
    },

    async unlockRanges(spreadsheetId, protectedRangeIds) {
      await batchUpdate(
        spreadsheetId,
        protectedRangeIds.map((protectedRangeId) => ({
          deleteProtectedRange: { protectedRangeId },
        })),
      );
    },
  };
}
