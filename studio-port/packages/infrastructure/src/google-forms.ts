import { z } from 'zod';
import type {
  AnswerGrade,
  FormSubmission,
  QuestionKind,
  QuestionSpec,
} from '../../domain/src/index.ts';
import type {
  EmailCollection,
  FormItem,
  FormStructure,
  GoogleFormsPort,
} from '../../application/src/index.ts';
import {
  externalRequest,
  readJson,
  type AccessToken,
  type ExternalRequest,
  type HttpOptions,
} from './external-http.ts';

// Google Forms v1 어댑터. synsory-api app/services/google_forms/client.py + mapper.py
// + usecases.build_setup_requests의 이식본. 함정은 synsory-api docs/google_forms.md 10절.

const BASE_URL = 'https://forms.googleapis.com/v1';

const option = z.object({ value: z.string().optional(), isOther: z.boolean().optional() });
const question = z.object({
  questionId: z.string().optional(),
  grading: z.object({ pointValue: z.number().optional() }).optional(),
  choiceQuestion: z
    .object({ type: z.string().optional(), options: z.array(option).optional() })
    .optional(),
  textQuestion: z.object({ paragraph: z.boolean().optional() }).optional(),
  scaleQuestion: z.object({ low: z.number().optional(), high: z.number().optional() }).optional(),
  ratingQuestion: z.object({ ratingScaleLevel: z.number().optional() }).optional(),
  dateQuestion: z.object({}).optional(),
  timeQuestion: z.object({}).optional(),
  fileUploadQuestion: z.object({}).optional(),
  rowQuestion: z.object({ title: z.string().optional() }).optional(),
});
const item = z.object({
  title: z.string().optional(),
  questionItem: z.object({ question: question.optional() }).optional(),
  questionGroupItem: z
    .object({
      grid: z
        .object({ columns: z.object({ options: z.array(option).optional() }).optional() })
        .optional(),
      questions: z.array(question).optional(),
    })
    .optional(),
});
export const form = z.object({
  formId: z.string(),
  info: z.object({ title: z.string().optional() }).optional(),
  settings: z
    .object({
      emailCollectionType: z.enum(['DO_NOT_COLLECT', 'VERIFIED', 'RESPONDER_INPUT']).optional(),
      quizSettings: z.object({ isQuiz: z.boolean().optional() }).optional(),
    })
    .optional(),
  publishSettings: z
    .object({
      publishState: z
        .object({
          isPublished: z.boolean().optional(),
          isAcceptingResponses: z.boolean().optional(),
        })
        .optional(),
    })
    .optional(),
  responderUri: z.string().optional(),
  linkedSheetId: z.string().optional(),
  revisionId: z.string().optional(),
  items: z.array(item).optional(),
});
export type Form = z.infer<typeof form>;

const answerList = <T extends z.ZodType>(entry: T) =>
  z.object({ answers: z.array(entry).optional() }).optional();
export const formResponse = z.object({
  responseId: z.string(),
  respondentEmail: z.string().optional(),
  createTime: z.string().optional(),
  lastSubmittedTime: z.string().optional(),
  totalScore: z.number().optional(),
  answers: z
    .record(
      z.string(),
      z.object({
        textAnswers: answerList(z.object({ value: z.string().optional() })),
        fileUploadAnswers: answerList(z.object({ fileId: z.string().optional() })),
        grade: z
          .object({ score: z.number().optional(), correct: z.boolean().optional() })
          .optional(),
      }),
    )
    .optional(),
});
export type FormResponse = z.infer<typeof formResponse>;

const range = (from: number, to: number) =>
  Array.from({ length: Math.max(0, to - from + 1) }, (_, i) => String(from + i));

function questionKind(q: z.infer<typeof question>): [QuestionKind, string[]] {
  if (q.choiceQuestion) {
    const kind = `choice_${(q.choiceQuestion.type ?? 'RADIO').toLowerCase()}` as QuestionKind;
    return [
      kind,
      (q.choiceQuestion.options ?? []).map((o) => (o.isOther ? '(기타)' : (o.value ?? ''))),
    ];
  }
  if (q.textQuestion) return [q.textQuestion.paragraph ? 'paragraph' : 'text', []];
  // low가 0이면 Forms가 필드를 빼고 보낸다(proto3 기본값 생략, 2026-10-09 실측). 그래서 기본은 0이다.
  if (q.scaleQuestion) return ['scale', range(q.scaleQuestion.low ?? 0, q.scaleQuestion.high ?? 5)];
  if (q.ratingQuestion) return ['rating', range(1, q.ratingQuestion.ratingScaleLevel ?? 5)];
  if (q.dateQuestion) return ['date', []];
  if (q.timeQuestion) return ['time', []];
  if (q.fileUploadQuestion) return ['file_upload', []];
  return ['unknown', []];
}

// items[] → 질문 목록(폼 순서). 격자 질문은 행마다 하나. 섹션·이미지 등 질문 아닌 항목은 뺀다.
export function questionSpecs(f: Form): QuestionSpec[] {
  const specs: QuestionSpec[] = [];
  for (const it of f.items ?? []) {
    const title = it.title ?? '';
    const q = it.questionItem?.question;
    if (q?.questionId) {
      const [kind, options] = questionKind(q);
      specs.push({
        id: q.questionId,
        title,
        kind,
        options,
        point_value: q.grading?.pointValue ?? null,
      });
    } else if (it.questionGroupItem) {
      const columns = (it.questionGroupItem.grid?.columns?.options ?? []).map((o) => o.value ?? '');
      for (const row of it.questionGroupItem.questions ?? []) {
        if (!row.questionId) continue;
        const rowTitle = row.rowQuestion?.title ?? '';
        specs.push({
          id: row.questionId,
          title: rowTitle ? `${title} [${rowTitle}]` : title,
          kind: 'grid_row',
          options: columns,
          point_value: null,
          group_title: title,
          row_title: rowTitle,
        });
      }
    }
  }
  return specs;
}

// unpublished=true로 만든 폼은 publishState가 빈 객체로 온다(→ false). 레거시 폼은 publishSettings가 없다(→ null).
export function formStructure(f: Form): FormStructure {
  const state = f.publishSettings?.publishState;
  return {
    form_id: f.formId,
    title: f.info?.title ?? null,
    responder_url: f.responderUri ?? null,
    published: state ? (state.isPublished ?? false) : null,
    accepting_responses: state ? (state.isAcceptingResponses ?? false) : null,
    email_collection: f.settings?.emailCollectionType ?? null,
    is_quiz: f.settings?.quizSettings?.isQuiz ?? false,
    linked_sheet_id: f.linkedSheetId ?? null,
    revision_id: f.revisionId ?? null,
    questions: questionSpecs(f),
  };
}

// 퀴즈 폼은 모든 답에 grade가 붙는데, 채점 대상이 아닌 문항과 틀린 문항이 똑같이 빈 객체 {}로 온다
// (2026-10-06 실측). 그래서 graded를 받아 그 질문만 grades에 넣고, 빈 grade는 0점·오답으로 본다.
// graded가 없으면 score가 있는 문항만 넣는다(틀린 문항은 빠진다).
export function submissionFromResponse(
  r: FormResponse,
  formId: string,
  graded: Record<string, number> | null = null,
): FormSubmission {
  const answers: Record<string, string[]> = {};
  const fileIds: Record<string, string[]> = {};
  const grades: Record<string, AnswerGrade> = {};
  for (const [qid, a] of Object.entries(r.answers ?? {})) {
    if (a.textAnswers) answers[qid] = (a.textAnswers.answers ?? []).map((t) => t.value ?? '');
    if (a.fileUploadAnswers)
      fileIds[qid] = (a.fileUploadAnswers.answers ?? []).map((f) => f.fileId ?? '');
    const g = a.grade;
    if (graded) {
      const max = graded[qid];
      if (max !== undefined)
        grades[qid] = { score: g?.score ?? 0, correct: g?.correct ?? false, max_score: max };
    } else if (g?.score !== undefined) {
      grades[qid] = { score: g.score, correct: g.correct ?? false, max_score: null };
    }
  }
  // 답하지 않은(선택) 채점 문항도 0점으로 남긴다.
  for (const [qid, max] of Object.entries(graded ?? {}))
    grades[qid] ??= { score: 0, correct: false, max_score: max };
  return {
    id: r.responseId,
    form_id: formId,
    respondent_email: r.respondentEmail ?? null,
    created_at: r.createTime ?? null,
    submitted_at: r.lastSubmittedTime ?? null,
    answers,
    file_ids: fileIds,
    total_score: r.totalScore ?? null,
    grades,
  };
}

// update()가 보내는 batchUpdate 요청 배열. 순서: 설정(퀴즈가 grading보다 먼저) → 제목·설명 → 질문.
export function updateRequests(changes: {
  title?: string;
  description?: string;
  emailCollection?: EmailCollection;
  quiz?: boolean;
  items?: FormItem[];
}): Record<string, unknown>[] {
  const requests: Record<string, unknown>[] = [];
  const settings: Record<string, unknown> = {};
  const settingMasks: string[] = [];
  if (changes.quiz !== undefined) {
    settings['quizSettings'] = { isQuiz: changes.quiz };
    settingMasks.push('quizSettings.isQuiz');
  }
  if (changes.emailCollection) {
    settings['emailCollectionType'] = changes.emailCollection;
    settingMasks.push('emailCollectionType');
  }
  if (settingMasks.length)
    requests.push({ updateSettings: { settings, updateMask: settingMasks.join(',') } });
  const info: Record<string, string> = {};
  if (changes.title) info['title'] = changes.title;
  if (changes.description) info['description'] = changes.description;
  if (Object.keys(info).length)
    requests.push({ updateFormInfo: { info, updateMask: Object.keys(info).join(',') } });
  (changes.items ?? []).forEach((it, index) =>
    requests.push({ createItem: { item: it, location: { index } } }),
  );
  return requests;
}

export function createGoogleForms(
  accessToken: AccessToken,
  options: HttpOptions = {},
): GoogleFormsPort {
  const call = async (request: ExternalRequest) =>
    externalRequest('google', await accessToken(), request, options);
  async function allResponses(formId: string, query: Record<string, string | undefined>) {
    const out: FormResponse[] = [];
    let pageToken: string | undefined;
    do {
      const page = await readJson(
        await call({
          method: 'GET',
          url: `${BASE_URL}/forms/${formId}/responses`,
          query: { ...query, pageToken },
        }),
        z.object({
          responses: z.array(formResponse).default([]),
          nextPageToken: z.string().optional(),
        }),
      );
      out.push(...page.responses);
      pageToken = page.nextPageToken;
    } while (pageToken);
    return out;
  }
  return {
    // forms.create. 본문은 info.title·documentTitle만 받는다. 질문·설정은 update로.
    async create(title) {
      const response = await call({
        method: 'POST',
        url: `${BASE_URL}/forms`,
        query: { unpublished: true },
        json: { info: { title, documentTitle: title } },
      });
      return (await readJson(response, z.object({ formId: z.string() }))).formId;
    },

    // forms.batchUpdate (쓰기 쿼터 1회, 안의 요청 수 무관)
    async update(formId, changes) {
      const requests = updateRequests(changes);
      if (!requests.length) return;
      await call({
        method: 'POST',
        url: `${BASE_URL}/forms/${formId}:batchUpdate`,
        json: { requests, includeFormInResponse: false },
      });
    },

    // published=false면 Forms가 acceptingResponses를 false로 강제한다.
    async setPublishState(formId, published, acceptingResponses) {
      await call({
        method: 'POST',
        url: `${BASE_URL}/forms/${formId}:setPublishSettings`,
        json: {
          publishSettings: {
            publishState: { isPublished: published, isAcceptingResponses: acceptingResponses },
          },
          updateMask: 'publishState',
        },
      });
    },

    async get(formId) {
      const response = await call({ method: 'GET', url: `${BASE_URL}/forms/${formId}` });
      return formStructure(await readJson(response, form));
    },

    // filter는 timestamp >= RFC3339만 쓴다. pageSize는 기본·최대 5000.
    async listResponses(formId, { since, graded } = {}) {
      const raw = await allResponses(formId, {
        filter: since ? `timestamp >= ${since}` : undefined,
      });
      return raw.map((r) => submissionFromResponse(r, formId, graded ?? null));
    },

    async listRespondentEmails(formId) {
      const raw = await allResponses(formId, {
        fields: 'responses(responseId,respondentEmail,lastSubmittedTime),nextPageToken',
      });
      return raw.map((r) => r.respondentEmail ?? null);
    },
  };
}
