import { describe, expect, it } from 'vitest';
import {
  collectQuizScores,
  collectResponses,
  createForm,
  createFormFromTemplate,
  createGroupForms,
  exportResponsesCsv,
  getSubmissionStatus,
  readForm,
  restrictResponders,
  ANYONE_WITH_LINK_PERMISSION_ID,
  type GoogleDrivePort,
  type GoogleFormsPort,
} from '../../packages/application/src/index.ts';
import {
  AppError,
  gradedQuestions,
  memberLabels,
  peerReviewItems,
  responseTable,
  summarize,
  summarizePeerReviews,
  type FormSubmission,
  type QuestionSpec,
} from '../../packages/domain/src/index.ts';
import {
  createGoogleForms,
  documentFromDriveFile,
  form,
  formStructure,
  questionSpecs,
  submissionFromResponse,
  updateRequests,
  type Fetch,
} from '../../packages/infrastructure/src/index.ts';
import { fakePort, notFound } from '../fixtures/fake-port.ts';
import { token } from '../fixtures/http.ts';

// ---------- 응답 해석 (synsory-api tests/google_forms/test_mapper.py) ----------

const QUIZ_FORM = form.parse({
  formId: 'f1',
  items: [
    { title: '학번', questionItem: { question: { questionId: 'sid', textQuestion: {} } } },
    {
      title: '404?',
      questionItem: {
        question: {
          questionId: 'q404',
          grading: { pointValue: 2 },
          choiceQuestion: {
            type: 'RADIO',
            options: [{ value: '권한 없음' }, { value: '찾을 수 없음' }, { isOther: true }],
          },
        },
      },
    },
    {
      title: 'REST의 R',
      questionItem: {
        question: { questionId: 'qr', grading: { pointValue: 1 }, textQuestion: {} },
      },
    },
    {
      title: '만족도',
      questionItem: { question: { questionId: 'sc', scaleQuestion: { low: 1, high: 3 } } },
    },
  ],
});

describe('Forms response mapping', () => {
  it('uses info.title for the document and keeps the edit url (readForm)', async () => {
    const forms = fakePort<GoogleFormsPort>({
      get: async () =>
        formStructure(form.parse({ formId: 'f1', info: { title: '응답자에게 보이는 제목' } })),
    });
    const drive = fakePort<GoogleDrivePort>({
      getFile: async () =>
        documentFromDriveFile({
          id: 'f1',
          name: 'Drive 파일명',
          mimeType: 'application/vnd.google-apps.form',
          webViewLink: 'https://docs.google.com/forms/d/f1/edit',
          parents: ['folder1'],
        }),
    });
    const info = await readForm(forms, drive, 'f1');
    expect(info.document).toMatchObject({
      kind: 'form',
      title: '응답자에게 보이는 제목',
      parent_folder_id: 'folder1',
    });
    expect(info.document.url?.endsWith('/edit')).toBe(true);
  });

  it('reads publish state: published, unpublished (empty object), legacy (missing)', () => {
    const state = (raw: unknown) => {
      const s = formStructure(form.parse({ formId: 'f', ...(raw as object) }));
      return [s.published, s.accepting_responses];
    };
    expect(
      state({
        publishSettings: { publishState: { isPublished: true, isAcceptingResponses: true } },
      }),
    ).toEqual([true, true]);
    // unpublished=true로 만든 폼: publishState가 빈 객체로 온다(2026-10-06 실측)
    expect(state({ publishSettings: { publishState: {} } })).toEqual([false, false]);
    // 레거시 폼: publishSettings 자체가 없다
    expect(state({})).toEqual([null, null]);
  });

  it('flattens grid rows into "question [row]" and skips non-question items', () => {
    const specs = questionSpecs(
      form.parse({
        formId: 'f',
        items: [
          { title: '학번', questionItem: { question: { questionId: 'q1' } } },
          { title: '섹션', pageBreakItem: {} },
          {
            title: '동료 평가',
            questionGroupItem: {
              questions: [
                { questionId: 'r1', rowQuestion: { title: '학생 A' } },
                { questionId: 'r2', rowQuestion: { title: '학생 B' } },
              ],
            },
          },
        ],
      }),
    );
    expect(Object.fromEntries(specs.map((s) => [s.id, s.title]))).toEqual({
      q1: '학번',
      r1: '동료 평가 [학생 A]',
      r2: '동료 평가 [학생 B]',
    });
  });

  it('derives kinds, options and graded questions', () => {
    const specs = Object.fromEntries(questionSpecs(QUIZ_FORM).map((s) => [s.id, s]));
    expect(specs['q404']?.kind).toBe('choice_radio');
    expect(specs['q404']?.options).toEqual(['권한 없음', '찾을 수 없음', '(기타)']);
    expect(specs['sc']?.options).toEqual(['1', '2', '3']);
    expect(gradedQuestions(questionSpecs(QUIZ_FORM))).toEqual({ q404: 2, qr: 1 });
  });

  it('reads a scale without low as starting at 0 (Forms omits low=0)', () => {
    // 2026-10-09 실측: low 0으로 만든 척도를 forms.get하면 {"high":3}만 온다.
    const [spec] = questionSpecs(
      form.parse({
        formId: 'f',
        items: [
          {
            title: '난이도',
            questionItem: { question: { questionId: 's', scaleQuestion: { high: 3 } } },
          },
        ],
      }),
    );
    expect(spec?.options).toEqual(['0', '1', '2', '3']);
  });

  it('treats an empty grade as wrong only for graded questions', () => {
    // 2026-10-06 실측 형태: 틀린 문항과 채점 대상 아닌 문항이 똑같이 grade {}
    const response = {
      responseId: 'r1',
      respondentEmail: 'a@example.com',
      lastSubmittedTime: '2026-10-05T17:38:44.478332Z',
      totalScore: 2,
      answers: {
        sid: { grade: {}, textAnswers: { answers: [{ value: '0123' }] } },
        q404: {
          grade: { score: 2, correct: true },
          textAnswers: { answers: [{ value: '찾을 수 없음' }] },
        },
        qr: { grade: {}, textAnswers: { answers: [{ value: 'resources' }] } },
      },
    };
    const sub = submissionFromResponse(response, 'f1', gradedQuestions(questionSpecs(QUIZ_FORM)));
    expect(sub.answers['sid']).toEqual(['0123']); // 문자열 그대로(앞자리 0 유지)
    expect(Object.keys(sub.grades).sort()).toEqual(['q404', 'qr']);
    expect(sub.grades['q404']).toMatchObject({ correct: true, score: 2 });
    expect(sub.grades['qr']).toEqual({ score: 0, correct: false, max_score: 1 });
    // graded 없이 변환하면 점수가 있는 문항만
    expect(Object.keys(submissionFromResponse(response, 'f1').grades)).toEqual(['q404']);
  });
});

// ---------- 흐름 (synsory-api tests/google_forms/test_usecases.py) ----------

it('orders update requests: settings (quiz first) → info → items', () => {
  const reqs = updateRequests({
    description: '설명',
    items: [{ title: 'a' }, { title: 'b' }],
    emailCollection: 'VERIFIED',
    quiz: true,
  });
  expect(reqs[0]).toEqual({
    updateSettings: {
      settings: { quizSettings: { isQuiz: true }, emailCollectionType: 'VERIFIED' },
      updateMask: 'quizSettings.isQuiz,emailCollectionType',
    },
  });
  expect(reqs[1]).toEqual({
    updateFormInfo: { info: { description: '설명' }, updateMask: 'description' },
  });
  expect(
    reqs.slice(2).map((r) => (r['createItem'] as { location: { index: number } }).location.index),
  ).toEqual([0, 1]);
});

function formsAndDrive(
  opts: {
    failUpdate?: boolean;
    failEmails?: string[];
    deleteError?: AppError;
    items?: unknown[];
  } = {},
) {
  const calls: unknown[][] = [];
  const forms = fakePort<GoogleFormsPort>({
    async create(title) {
      calls.push(['create', title]);
      return 'f1';
    },
    async update(formId, changes) {
      calls.push(['update', formId, changes]);
      if (opts.failUpdate) throw new AppError('EXTERNAL_FAILED', 502, 'Invalid grading');
    },
    async setPublishState(formId, published, accepting) {
      calls.push(['publish', formId, published, accepting]);
    },
    async get(formId) {
      return formStructure(
        form.parse({
          formId,
          info: { title: '설문' },
          publishSettings: { publishState: { isPublished: true, isAcceptingResponses: true } },
          items: opts.items,
        }),
      );
    },
  });
  const drive = fakePort<GoogleDrivePort>({
    getFile: async (id) =>
      documentFromDriveFile({ id, name: '설문', mimeType: 'application/vnd.google-apps.form' }),
    async moveFile(id, to) {
      calls.push(['move', id, to]);
      return documentFromDriveFile({ id });
    },
    async trashFile(id) {
      calls.push(['trash', id]);
    },
    async copyFile(id, name, parent) {
      calls.push(['copy', id, name, parent]);
      return documentFromDriveFile({ id: 'c1' });
    },
    async shareAsResponder(id, email) {
      if (email && opts.failEmails?.includes(email))
        throw new AppError('EXTERNAL_FAILED', 502, 'invalidSharingRequest');
      calls.push(['share', id, email]);
      return {
        id: `perm-${email}`,
        type: 'user',
        role: 'reader',
        email,
        display_name: null,
        view: 'published',
      };
    },
    async deletePermission(id, permissionId) {
      if (opts.deleteError) throw opts.deleteError;
      calls.push(['delete_permission', id, permissionId]);
    },
  });
  return { forms, drive, calls, kinds: () => calls.map((c) => c[0]) };
}

describe('createForm', () => {
  it('starts unpublished, publishes after items, then moves into the folder', async () => {
    const t = formsAndDrive();
    const info = await createForm(t.forms, t.drive, {
      title: '설문',
      folderId: 'folder1',
      items: [{ title: 'q' }],
    });
    expect(t.kinds()).toEqual(['create', 'update', 'publish', 'move']);
    expect(t.calls).toContainEqual(['move', 'f1', 'folder1']);
    expect(info.published).toBe(true);
  });

  it('stays unpublished for a scheduled open', async () => {
    const t = formsAndDrive();
    await createForm(t.forms, t.drive, {
      title: '수업 퀴즈',
      items: [{ title: 'q' }],
      publish: false,
    });
    expect(t.kinds()).not.toContain('publish');
  });

  it('trashes the empty form when adding items fails', async () => {
    const t = formsAndDrive({ failUpdate: true });
    await expect(
      createForm(t.forms, t.drive, { title: '설문', folderId: 'folder1', items: [{ title: 'q' }] }),
    ).rejects.toBeInstanceOf(AppError);
    expect(t.calls).toContainEqual(['trash', 'f1']);
    expect(t.kinds()).not.toContain('publish');
  });
});

describe('restrictResponders', () => {
  it('removes link access after adding at least one responder', async () => {
    const t = formsAndDrive({ failEmails: ['bad@example.com'] });
    const results = await restrictResponders(t.drive, 'f1', ['a@example.com', 'bad@example.com']);
    expect(results.map((r) => [r.email, r.error === null])).toEqual([
      ['a@example.com', true],
      ['bad@example.com', false],
      [null, true],
    ]);
    expect(t.calls.at(-1)).toEqual(['delete_permission', 'f1', ANYONE_WITH_LINK_PERMISSION_ID]);
  });

  it('keeps link access when nobody was added', async () => {
    const t = formsAndDrive({ failEmails: ['bad@example.com'] });
    const results = await restrictResponders(t.drive, 'f1', ['bad@example.com']);
    expect(t.kinds()).not.toContain('delete_permission');
    expect(results.map((r) => r.email)).toEqual(['bad@example.com']);
  });

  it('is safe to rerun when link access is already gone (404)', async () => {
    const t = formsAndDrive({ deleteError: notFound() });
    const results = await restrictResponders(t.drive, 'f1', ['a@example.com']);
    expect(results.at(-1)).toEqual({ email: null, permission_id: null, error: null });
  });
});

// ---------- 3·6·9~12 ----------

const GRID_QUESTIONS: QuestionSpec[] = [
  {
    id: 'c1a',
    title: '기여도 [가]',
    kind: 'grid_row',
    options: ['1', '2', '3'],
    point_value: null,
    group_title: '기여도',
    row_title: '가',
  },
  {
    id: 'c1b',
    title: '기여도 [나]',
    kind: 'grid_row',
    options: ['1', '2', '3'],
    point_value: null,
    group_title: '기여도',
    row_title: '나',
  },
];

const sub = (
  id: string,
  email: string | null,
  answers: Record<string, string[]>,
  when: string | null = '2026-10-05T10:00:00Z',
  score: number | null = null,
): FormSubmission => ({
  id,
  form_id: 'f1',
  respondent_email: email,
  created_at: null,
  submitted_at: when,
  answers,
  file_ids: {},
  total_score: score,
  grades: {},
});

it('summarize counts options in order, other answers and averages', () => {
  const questions: QuestionSpec[] = [
    {
      id: 'ch',
      title: '역할',
      kind: 'choice_checkbox',
      options: ['기획', '개발', '(기타)'],
      point_value: null,
    },
    { id: 'sc', title: '만족도', kind: 'scale', options: ['1', '2', '3'], point_value: null },
    { id: 'tx', title: '의견', kind: 'paragraph', options: [], point_value: null },
  ];
  const by = Object.fromEntries(
    summarize(questions, [
      sub('r1', 'a@x.com', { ch: ['기획', '개발'], sc: ['3'], tx: ['좋음'] }),
      sub('r2', 'b@x.com', { ch: ['디자인'], sc: ['1'] }),
    ]).map((s) => [s.id, s]),
  );
  expect(by['ch']?.counts).toEqual([
    { option: '기획', count: 1 },
    { option: '개발', count: 1 },
    { option: '(기타)', count: 1 },
  ]);
  expect(by['ch']?.other_answers).toEqual(['디자인']);
  expect(by['sc']?.counts.map((c) => c.count)).toEqual([1, 0, 1]);
  expect(by['sc']?.average).toBe(2);
  expect([by['tx']?.text_answers, by['tx']?.response_count]).toEqual([['좋음'], 1]);
});

it('peer reviews exclude self-reviews case-insensitively when reviewees are known', () => {
  const reviewees = { c1a: 'ga@x.com', c1b: 'na@x.com' };
  const subs = [
    sub('r1', 'ga@x.com', { c1a: ['3'], c1b: ['2'] }),
    sub('r2', 'NA@x.com', { c1a: ['1'], c1b: ['3'] }),
  ];
  const scores = Object.fromEntries(
    summarizePeerReviews(GRID_QUESTIONS, subs, reviewees).map((p) => [
      `${p.reviewee}|${p.criterion}`,
      p,
    ]),
  );
  expect(scores['ga@x.com|기여도']).toMatchObject({ average: 1, self_excluded: 1 });
  expect(scores['na@x.com|기여도']?.average).toBe(2); // 대소문자 무시로 자기 평가 3점 제외
  expect(scores['ga@x.com|(전체)']).toMatchObject({ average: 1, count: 1, self_excluded: 1 });
  const noMap = Object.fromEntries(
    summarizePeerReviews(GRID_QUESTIONS, subs).map((p) => [`${p.reviewee}|${p.criterion}`, p]),
  );
  expect(noMap['가|기여도']?.average).toBe(2); // reviewees 없으면 행 제목 기준, 자기 평가 판별 불가
});

it('member labels disambiguate the same name; peer review items are one grid per criterion', () => {
  expect(
    memberLabels([
      { name: '김', email: 'kim1@x.com' },
      { name: '김', email: 'kim2@x.com' },
      { name: '이', email: 'lee@x.com' },
    ]),
  ).toEqual(['김 (kim1)', '김 (kim2)', '이']);
  const items = peerReviewItems([{ name: '가', email: 'a@x.com' }], ['기여도', '협업'], ['1', '2']);
  expect(items.map((i) => i['title'])).toEqual(['기여도', '협업']);
  expect((items[0]?.['questionGroupItem'] as { questions: unknown[] }).questions[0]).toEqual({
    required: true,
    rowQuestion: { title: '가' },
  });
});

it('response table adds a score column for quizzes and converts to the time zone', () => {
  const questions: QuestionSpec[] = [
    { id: 'sid', title: '학번', kind: 'text', options: [], point_value: null },
    { id: 'q', title: '404?', kind: 'choice_checkbox', options: [], point_value: 2 },
  ];
  const rows = responseTable(questions, [
    sub('r1', 'a@x.com', { sid: ['0123'], q: ['가', '나'] }, '2026-10-05T17:38:44Z', 2),
  ]);
  expect(rows[0]).toEqual(['제출 시각', '이메일', '점수', '학번', '404?']);
  expect(rows[1]).toEqual(['2026-10-06 02:38:44', 'a@x.com', '2', '0123', '가, 나']);
});

// 실제 어댑터 + URL별로 응답하는 fetch. forms.get과 responses.list가 동시에 불릴 수 있어 순서에 기대지 않는다.
const RESP_FORM = {
  formId: 'f1',
  info: { title: '퀴즈' },
  items: [
    { title: '학번', questionItem: { question: { questionId: 'sid', textQuestion: {} } } },
    {
      title: '404?',
      questionItem: {
        question: {
          questionId: 'q',
          grading: { pointValue: 2 },
          choiceQuestion: { type: 'RADIO', options: [{ value: 'a' }] },
        },
      },
    },
  ],
};
const PAGES = [
  {
    responses: [
      {
        responseId: 'r1',
        respondentEmail: 'A@x.com',
        lastSubmittedTime: '2026-10-05T10:00:00.5Z',
        answers: {
          sid: { textAnswers: { answers: [{ value: '0123' }] } },
          q: { grade: {}, textAnswers: { answers: [{ value: 'b' }] } },
        },
      },
    ],
    nextPageToken: '1',
  },
  {
    responses: [
      {
        responseId: 'r2',
        respondentEmail: 'a@x.com',
        lastSubmittedTime: '2026-10-05T11:00:00Z',
        totalScore: 2,
        answers: {
          q: { grade: { score: 2, correct: true }, textAnswers: { answers: [{ value: 'a' }] } },
        },
      },
    ],
  },
];
function formsApi() {
  const listCalls: URLSearchParams[] = [];
  const fetchImpl: Fetch = async (input) => {
    const url = new URL(String(input));
    if (url.pathname === '/v1/forms/f1') return Response.json(RESP_FORM);
    listCalls.push(url.searchParams);
    return Response.json(PAGES[Number(url.searchParams.get('pageToken') ?? 0)]);
  };
  return { forms: createGoogleForms(token, { fetch: fetchImpl }), listCalls };
}

it('collects all pages incrementally and returns the latest submission time as the cursor', async () => {
  const api = formsApi();
  const result = await collectResponses(api.forms, 'f1', { since: '2026-10-05T00:00:00Z' });
  expect(result.submissions.map((s) => s.id)).toEqual(['r1', 'r2']);
  expect(result.cursor).toBe('2026-10-05T11:00:00Z');
  expect(api.listCalls[0]?.get('filter')).toBe('timestamp >= 2026-10-05T00:00:00Z');
  expect(api.listCalls[1]?.get('pageToken')).toBe('1');
});

it('sorts by time even when fractional seconds differ', async () => {
  const forms = fakePort<GoogleFormsPort>({
    listResponses: async () => [
      sub('late', null, {}, '2026-10-05T10:00:00.5Z'),
      sub('none', null, {}, null),
      sub('early', null, {}, '2026-10-05T10:00:00Z'),
    ],
  });
  const result = await collectResponses(forms, 'f1');
  expect(result.submissions.map((s) => s.id)).toEqual(['early', 'late', 'none']);
  expect(result.cursor).toBe('2026-10-05T10:00:00.5Z');
});

it('submission status is case-insensitive and reports resubmissions', async () => {
  const status = await getSubmissionStatus(formsApi().forms, 'f1', ['a@x.com', 'b@x.com']);
  expect([status.submitted, status.missing]).toEqual([['a@x.com'], ['b@x.com']]);
  expect([status.resubmitted, status.not_in_roster]).toEqual([{ 'a@x.com': 2 }, []]);
});

it('quiz scores fill wrong answers with zero', async () => {
  const scores = await collectQuizScores(formsApi().forms, 'f1');
  expect(scores.map((s) => [s.total_score, s.max_score])).toEqual([
    [0, 2],
    [2, 2],
  ]);
  expect(scores[0]?.grades['q']).toMatchObject({ score: 0, correct: false });
});

it('exports CSV with a UTF-8 BOM and keeps leading zeros', async () => {
  const exported = await exportResponsesCsv(formsApi().forms, 'f1');
  expect([...exported.content.slice(0, 3)]).toEqual([0xef, 0xbb, 0xbf]);
  expect(exported.filename).toBe('퀴즈 응답.csv');
  const lines = new TextDecoder().decode(exported.content).split('\r\n');
  expect(lines[1]?.split(',')[3]).toBe('0123');
});

it('createGroupForms maps grid rows to emails and isolates responder failures', async () => {
  const t = formsAndDrive({
    failEmails: ['bad@example.com'],
    items: [
      {
        title: '기여도',
        questionGroupItem: {
          grid: { columns: { options: [{ value: '1' }] } },
          questions: [
            { questionId: 'x1', rowQuestion: { title: '가' } },
            { questionId: 'x2', rowQuestion: { title: '나' } },
          ],
        },
      },
    ],
  });
  const [r] = await createGroupForms(t.forms, t.drive, {
    folderId: 'folder1',
    activityName: '1차',
    groups: [
      {
        team_name: 'A조',
        members: [
          { name: '가', email: 'ga@x.com' },
          { name: '나', email: 'bad@example.com' },
        ],
      },
    ],
    criteria: ['기여도'],
  });
  expect(r?.error).toBeNull();
  expect(r?.reviewees).toEqual({ x1: 'ga@x.com', x2: 'bad@example.com' });
  expect(r?.responders.map((x) => [x.email, x.error === null])).toEqual([
    ['ga@x.com', true],
    ['bad@example.com', false],
    [null, true],
  ]);
});

it('createFormFromTemplate copies, retitles, publishes and restricts without touching the original', async () => {
  const t = formsAndDrive();
  const result = await createFormFromTemplate(t.forms, t.drive, {
    templateFormId: 'orig',
    name: '1차 퀴즈 사본',
    folderId: 'folder1',
    title: '1차 퀴즈',
    responderEmails: ['a@x.com'],
  });
  expect(t.calls[0]).toEqual(['copy', 'orig', '1차 퀴즈 사본', 'folder1']);
  expect(t.calls.filter((c) => c[0] === 'update' || c[0] === 'publish')).toEqual([
    ['update', 'c1', { title: '1차 퀴즈' }],
    ['publish', 'c1', true, true],
  ]);
  expect(result.responders.map((r) => [r.email, r.error === null])).toEqual([
    ['a@x.com', true],
    [null, true],
  ]);
});
