import { describe, expect, it } from 'vitest';
import {
  createGroupFilesFromContent,
  createGroupFilesFromTemplate,
  exportResponsesToSheet,
  type GoogleDrivePort,
  type GoogleFormsPort,
  type GoogleSheetsPort,
} from '../../packages/application/src/index.ts';
import { AppError, type FormSubmission } from '../../packages/domain/src/index.ts';
import {
  a1,
  columnLetter,
  createGoogleDocs,
  createGoogleSheets,
  createGoogleSlides,
  documentFromDriveFile,
  form,
  formStructure,
} from '../../packages/infrastructure/src/index.ts';
import { fakePort } from '../fixtures/fake-port.ts';
import { recordingFetch, token } from '../fixtures/http.ts';

const VARS = { team_name: 'A조', activity_name: '과제1', due: '2026-10-10' };

// ---------- Docs·Slides 태그 치환 ----------

describe('Docs and Slides replaceTags (replaceAllText)', () => {
  it('Docs: one batchUpdate, exact tag with matchCase, counts per tag (missing reply → 0)', async () => {
    const http = recordingFetch({
      json: {
        replies: [
          { replaceAllText: { occurrencesChanged: 1 } },
          { replaceAllText: {} }, // 0이면 필드가 빠진다
        ],
      },
    });
    const counts = await createGoogleDocs(token, http).replaceTags('copy-1', VARS);
    expect(http.requests[0]?.url.pathname).toBe('/v1/documents/copy-1:batchUpdate');
    expect((http.requests[0]?.json as { requests: unknown[] }).requests[0]).toEqual({
      replaceAllText: {
        containsText: { text: '{{team_name}}', matchCase: true },
        replaceText: 'A조',
      },
    });
    expect(counts).toEqual({ team_name: 1, activity_name: 0, due: 0 });
  });

  it('Slides: same request shape on presentations', async () => {
    const http = recordingFetch({
      json: { replies: [{ replaceAllText: { occurrencesChanged: 2 } }] },
    });
    const counts = await createGoogleSlides(token, http).replaceTags('p1', { team_name: 'A조' });
    expect(http.requests[0]?.url.pathname).toBe('/v1/presentations/p1:batchUpdate');
    expect(http.requests[0]?.json).toEqual({
      requests: [
        {
          replaceAllText: {
            containsText: { text: '{{team_name}}', matchCase: true },
            replaceText: 'A조',
          },
        },
      ],
    });
    expect(counts).toEqual({ team_name: 2 });
  });

  it('plugs into the common copy → replace → share flow', async () => {
    const http = recordingFetch({
      json: { replies: [{ replaceAllText: { occurrencesChanged: 1 } }] },
    });
    const shared: string[] = [];
    const drive = fakePort<GoogleDrivePort>({
      copyFile: async (_id, name, parent) =>
        documentFromDriveFile({ id: 'copy-1', name, parents: parent ? [parent] : [] }),
      shareWithUsers: async (fileId, emails) =>
        emails.map((email) => {
          shared.push(`${fileId} ${email}`);
          return { email, permission_id: 'p', error: null };
        }),
    });
    const [result] = await createGroupFilesFromTemplate(drive, {
      folderId: 'folder-1',
      activityName: '과제1',
      titleTemplate: '{{activity_name}} - {{team_name}}',
      templateFileId: 'picked-doc',
      groups: [{ team_name: 'A조', member_emails: ['a1@example.com'] }],
      replaceTags: createGoogleDocs(token, http).replaceTags,
    });
    expect(result?.document?.title).toBe('과제1 - A조');
    expect(result?.replaced).toEqual({ team_name: 1, activity_name: 0, due: 0 });
    expect(shared).toEqual(['copy-1 a1@example.com']);
  });
});

// ---------- Sheets ----------

describe('Sheets coordinates (synsory-api tests/google_sheets/test_mapper.py)', () => {
  it('column letters round-trip', () => {
    expect([0, 25, 26, 27, 701, 702].map(columnLetter)).toEqual([
      'A',
      'Z',
      'AA',
      'AB',
      'ZZ',
      'AAA',
    ]);
  });

  it('a1 always quotes the sheet title and doubles inner quotes', () => {
    expect(a1('평가')).toBe("'평가'");
    expect(a1("A조's 시트")).toBe("'A조''s 시트'");
    expect(a1('팀 A', 'B6:B9')).toBe("'팀 A'!B6:B9");
  });
});

const SPREADSHEET = {
  sheets: [
    { properties: { sheetId: 77, title: '역할 분담', index: 1 } },
    { properties: { sheetId: 0, title: '평가', index: 0 } },
  ],
};

describe('GoogleSheetsPort (synsory-api tests/google_sheets/test_usecases.py)', () => {
  it('replaceTags uses findReplace on all sheets, matchCase, inside formulas', async () => {
    const http = recordingFetch({
      json: { replies: [{ findReplace: { occurrencesChanged: 3 } }, { findReplace: {} }] },
    });
    const counts = await createGoogleSheets(token, http).replaceTags('s-1', {
      team_name: 'A조',
      due: '',
    });
    expect((http.requests[0]?.json as { requests: unknown[] }).requests[0]).toEqual({
      findReplace: {
        find: '{{team_name}}',
        replacement: 'A조',
        matchCase: true,
        allSheets: true,
        includeFormulas: true,
      },
    });
    expect(counts).toEqual({ team_name: 3, due: 0 });
  });

  it('listSheets sorts by index', async () => {
    const sheets = await createGoogleSheets(
      token,
      recordingFetch({ json: SPREADSHEET }),
    ).listSheets('s-1');
    expect(sheets.map((s) => [s.sheet_id, s.title, s.index])).toEqual([
      [0, '평가', 0],
      [77, '역할 분담', 1],
    ]);
  });
});

// ---------- 텍스트 템플릿 변환 업로드 (Docs Markdown · Sheets CSV) ----------

it('createGroupFilesFromContent renders title and body, uploads into the folder, shares, isolates failures', async () => {
  const uploads: {
    name: string;
    content: string;
    source: string;
    target: string;
    parent: string | undefined;
  }[] = [];
  const shared: string[] = [];
  const drive = fakePort<GoogleDrivePort>({
    async createFromContent({ name, content, source, target, parentFolderId }) {
      if (name === '과제1 - B조') throw new AppError('EXTERNAL_FAILED', 502, 'upload failed');
      uploads.push({ name, content: String(content), source, target, parent: parentFolderId });
      return documentFromDriveFile({ id: `id-${uploads.length}`, name });
    },
    async shareWithUsers(fileId, emails) {
      return emails.map((email) => {
        shared.push(`${fileId} ${email}`);
        return { email, permission_id: 'p', error: null };
      });
    },
  });
  const results = await createGroupFilesFromContent(drive, {
    folderId: 'folder-1',
    activityName: '과제1',
    titleTemplate: '{{activity_name}} - {{team_name}}',
    bodyTemplate: '# {{activity_name}}\n\n팀: {{team_name}}\n마감: {{due}}',
    source: 'markdown',
    target: 'doc',
    groups: [
      { team_name: 'A조', member_emails: ['a1@example.com'] },
      { team_name: 'B조', member_emails: ['b1@example.com'] },
    ],
    due: '2026-10-10',
  });
  expect(uploads).toEqual([
    {
      name: '과제1 - A조',
      content: '# 과제1\n\n팀: A조\n마감: 2026-10-10',
      source: 'markdown',
      target: 'doc',
      parent: 'folder-1',
    },
  ]);
  expect(results.map((r) => [r.team_name, r.document?.id ?? null, r.error?.code ?? null])).toEqual([
    ['A조', 'id-1', null],
    ['B조', null, 'EXTERNAL_FAILED'],
  ]);
  expect(shared).toEqual(['id-1 a1@example.com']);
});

// ---------- Forms 유즈케이스 13: 시트로 내보내기 ----------

it('exportResponsesToSheet creates once, then clears only the columns Synsory wrote', async () => {
  const sub: FormSubmission = {
    id: 'r1',
    form_id: 'f1',
    respondent_email: 'a@x.com',
    submitted_at: '2026-10-05T10:00:00Z',
    answers: { sid: ['0123'] },
    file_ids: {},
    total_score: null,
    grades: {},
  };
  const forms = fakePort<GoogleFormsPort>({
    get: async () =>
      formStructure(
        form.parse({
          formId: 'f1',
          info: { title: '퀴즈' },
          items: [
            { title: '학번', questionItem: { question: { questionId: 'sid', textQuestion: {} } } },
          ],
        }),
      ),
    listResponses: async () => [sub, { ...sub, id: 'r2' }],
  });
  const calls: unknown[][] = [];
  const drive = fakePort<GoogleDrivePort>({
    moveFile: async (id, to) => {
      calls.push(['move', id, to]);
      return documentFromDriveFile({ id });
    },
  });
  const sheets = fakePort<GoogleSheetsPort>({
    create: async (title, sheetTitle) => {
      calls.push(['create', title, sheetTitle]);
      return 's1';
    },
    listSheets: async () => [{ sheet_id: 7, title: '응답(수정됨)', index: 0 }],
    clearColumns: async (_id, sheet, columns) => {
      calls.push(['clear', sheet, columns]);
    },
    writeValues: async (_id, sheet, cell, values) => {
      calls.push(['write', sheet, cell, values.length, values[1]?.[2]]);
    },
  });

  const first = await exportResponsesToSheet(forms, drive, sheets, 'f1', { folderId: 'folder1' });
  expect(first).toMatchObject({ created: true, spreadsheet_id: 's1', columns: 3, rows_written: 2 });
  expect(calls).toEqual([
    ['create', '퀴즈 응답', '응답'],
    ['move', 's1', 'folder1'],
    ['write', '응답', 'A1', 3, '0123'],
  ]);

  calls.length = 0;
  const again = await exportResponsesToSheet(forms, drive, sheets, 'f1', {
    spreadsheetId: 's1',
    previousColumns: 7,
  });
  expect(again.created).toBe(false);
  // 지난번 7열까지만 지운다. 그 오른쪽 교수자 메모는 남는다. 시트 이름이 바뀌었어도 첫 시트에 쓴다.
  expect(calls[0]).toEqual(['clear', '응답(수정됨)', 7]);
});

it('clearColumns clears A through the given column on the quoted sheet', async () => {
  const http = recordingFetch({ json: {} });
  await createGoogleSheets(token, http).clearColumns('s1', '응답(수정됨)', 7);
  expect(decodeURIComponent(http.requests[0]?.url.pathname ?? '')).toBe(
    "/v4/spreadsheets/s1/values/'응답(수정됨)'!A:G:clear",
  );
});
