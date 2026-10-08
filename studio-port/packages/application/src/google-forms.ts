import {
  AppError,
  gradedQuestions,
  memberLabels,
  peerReviewItems,
  renderTemplate,
  responseTable,
  submissionStatus,
  summarize,
  summarizePeerReviews,
  toCsv,
  type ExternalDocument,
  type FormSubmission,
  type PeerMember,
  type PeerScore,
  type QuestionSummary,
  type SubmissionStatus,
} from '../../domain/src/index.ts';
import type {
  EmailCollection,
  ExportedFile,
  FormItem,
  FormStructure,
  GoogleDrivePort,
  GoogleFormsPort,
} from './integration-ports.ts';

// Google Forms 흐름(유즈케이스 1~12). synsory-api app/services/google_forms/usecases.py의 이식본.
// 결과의 원본은 Synsory DB다. 수집·집계는 Synsory로 가져오는 데까지다.
// 외부 호출 실패(AppError)를 결과에 담는 흐름은 그렇게 하고, 그 밖의 예외는 그대로 올라간다.

export type FormInfo = Omit<FormStructure, 'title'> & {
  // 제목은 응답자에게 보이는 info.title, url은 Drive 편집 화면이다(응답 링크는 responder_url).
  document: ExternalDocument;
};

export async function readForm(
  forms: GoogleFormsPort,
  drive: GoogleDrivePort,
  formId: string,
): Promise<FormInfo> {
  const [{ title, ...structure }, document] = await Promise.all([
    forms.get(formId),
    drive.getFile(formId),
  ]);
  return { ...structure, document: { ...document, title: title || document.title } };
}

// 유즈케이스 1·2·8. 미게시로 만들기 → 설정·설명·질문(batchUpdate 1회) → (publish면) 게시 → 폴더 이동.
// 질문을 다 넣은 뒤 게시해야 학생이 미완성 폼을 보지 않는다. publish=false는 수업 시각에 열 폼용(openForm).
// 질문 추가가 실패하면 빈 폼을 휴지통으로 보내고 오류를 올린다(batchUpdate는 원자적이라 빈 폼이 남는다).
// 응답자 제한(restrictResponders)은 하지 않는다. 새 폼에는 "링크가 있는 모든 사용자" 응답자 권한이 붙어 있다.
export async function createForm(
  forms: GoogleFormsPort,
  drive: GoogleDrivePort,
  input: {
    title: string;
    folderId?: string;
    description?: string;
    items?: FormItem[];
    emailCollection?: EmailCollection;
    quiz?: boolean;
    publish?: boolean;
  },
): Promise<FormInfo> {
  const formId = await forms.create(input.title);
  try {
    await forms.update(formId, {
      ...(input.quiz && { quiz: true }),
      ...(input.emailCollection && { emailCollection: input.emailCollection }),
      ...(input.description && { description: input.description }),
      ...(input.items && { items: input.items }),
    });
  } catch (e) {
    if (e instanceof AppError) await drive.trashFile(formId);
    throw e;
  }
  if (input.publish ?? true) await forms.setPublishState(formId, true, true);
  if (input.folderId) await drive.moveFile(formId, input.folderId);
  return readForm(forms, drive, formId);
}

// 유즈케이스 8. 미리 만든(publish=false) 폼을 수업 시각에 연다. 마감 연장(7)도 같다. 폼 단위라 학생별 연장은 안 된다.
export async function openForm(forms: GoogleFormsPort, drive: GoogleDrivePort, formId: string) {
  await forms.setPublishState(formId, true, true);
  return readForm(forms, drive, formId);
}

// 유즈케이스 7·8. 마감. 게시는 유지하고 응답 받기만 끈다. 다시 실행해도 안전하다.
export async function closeForm(forms: GoogleFormsPort, drive: GoogleDrivePort, formId: string) {
  await forms.setPublishState(formId, true, false);
  return readForm(forms, drive, formId);
}

// 폼을 만들 때 자동으로 붙는 "링크가 있는 모든 사용자" 응답자 권한의 고정 id.
export const ANYONE_WITH_LINK_PERMISSION_ID = 'anyoneWithLink';

export interface ResponderResult {
  // null = "링크가 있는 모든 사용자" 권한 삭제 결과
  email: string | null;
  // 링크 권한 삭제 결과에서는 지운 id, 이미 지워져 있었으면 null
  permission_id: string | null;
  error: AppError | null;
}

// 유즈케이스 5. 학생마다 응답자 권한(view=published) → "링크가 있는 모든 사용자" 권한 삭제.
// 링크 권한이 남아 있으면 학생을 추가해도 누구나 응답할 수 있다(2026-10-06 실측).
// 한 명도 추가하지 못했으면 지우지 않는다(아무도 응답 못 하는 폼 방지). 이메일 단위로 실패해도 계속한다.
export async function restrictResponders(
  drive: GoogleDrivePort,
  formId: string,
  emails: string[],
  removeLinkAccess = true,
): Promise<ResponderResult[]> {
  const results: ResponderResult[] = [];
  for (const email of emails) {
    try {
      const p = await drive.shareAsResponder(formId, email);
      results.push({ email, permission_id: p.id, error: null });
    } catch (e) {
      if (!(e instanceof AppError)) throw e;
      results.push({ email, permission_id: null, error: e });
    }
  }
  if (removeLinkAccess && results.some((r) => r.error === null)) {
    try {
      await drive.deletePermission(formId, ANYONE_WITH_LINK_PERMISSION_ID);
      results.push({ email: null, permission_id: ANYONE_WITH_LINK_PERMISSION_ID, error: null });
    } catch (e) {
      if (!(e instanceof AppError)) throw e;
      // 이미 지워진 경우(404)는 성공이다. 다시 실행해도 안전하다.
      const gone = e.code === 'EXTERNAL_NOT_FOUND';
      results.push({ email: null, permission_id: null, error: gone ? null : e });
    }
  }
  return results;
}

// ---------- 유즈케이스 3: 조별 동료평가 폼 ----------

export interface PeerGroup {
  team_name: string;
  members: PeerMember[];
}

export interface GroupFormResult {
  team_name: string;
  form: FormInfo | null;
  responders: ResponderResult[];
  // 격자 행 질문 ID → 피평가자 이메일. 동료평가 집계(11)에 쓰므로 저장한다.
  reviewees: Record<string, string>;
  error: AppError | null;
}

// 조마다 동료평가 폼: createForm(VERIFIED, 게시) → restrictResponders(조원만). 그룹 단위로 실패해도 계속한다.
// 게시와 제한 사이 몇 초 동안 링크가 열려 있으므로 링크는 이 함수가 끝난 뒤에 학생에게 보낸다.
export async function createGroupForms(
  forms: GoogleFormsPort,
  drive: GoogleDrivePort,
  input: {
    folderId: string;
    activityName: string;
    groups: PeerGroup[];
    criteria: string[];
    scale?: string[];
    titleTemplate?: string;
    description?: string;
    extraItems?: FormItem[];
  },
): Promise<GroupFormResult[]> {
  const scale = input.scale ?? ['1', '2', '3', '4', '5'];
  const titleTemplate = input.titleTemplate ?? '{{activity_name}} 동료평가 - {{team_name}}';
  const results: GroupFormResult[] = [];
  for (const g of input.groups) {
    const variables = { activity_name: input.activityName, team_name: g.team_name };
    const result: GroupFormResult = {
      team_name: g.team_name,
      form: null,
      responders: [],
      reviewees: {},
      error: null,
    };
    try {
      const info = await createForm(forms, drive, {
        title: renderTemplate(titleTemplate, variables),
        folderId: input.folderId,
        ...(input.description && { description: renderTemplate(input.description, variables) }),
        items: [...peerReviewItems(g.members, input.criteria, scale), ...(input.extraItems ?? [])],
        emailCollection: 'VERIFIED',
      });
      result.form = info;
      const labels = memberLabels(g.members);
      const rows = new Map(labels.map((label, i) => [label, g.members[i]?.email ?? '']));
      for (const q of info.questions)
        if (
          q.kind === 'grid_row' &&
          input.criteria.includes(q.group_title ?? '') &&
          rows.has(q.row_title ?? '')
        )
          result.reviewees[q.id] = rows.get(q.row_title ?? '') ?? '';
      result.responders = await restrictResponders(
        drive,
        info.document.id,
        g.members.map((m) => m.email),
      );
    } catch (e) {
      if (!(e instanceof AppError)) throw e;
      result.error = e;
    }
    results.push(result);
  }
  return results;
}

// ---------- 유즈케이스 9~12: 수집·집계·내보내기 ----------

export interface CollectResult {
  form_id: string;
  // 제출 시각 순. 제출 시각이 없는 응답은 끝에.
  submissions: FormSubmission[];
  // 다음 증분 조회에 넘길 값(가장 늦은 lastSubmittedTime 원문). 응답이 없으면 since 그대로.
  cursor: string | null;
}

// 유즈케이스 9. since를 주면 그 시각 이후(>=) 응답만. 경계 응답이 다시 올 수 있어 저장할 때 id로 멱등 처리한다.
export async function collectResponses(
  forms: GoogleFormsPort,
  formId: string,
  options: { since?: string; graded?: Record<string, number> } = {},
): Promise<CollectResult> {
  const submissions = await forms.listResponses(formId, options);
  // RFC3339 소수 초 자릿수가 응답마다 달라 문자열이 아니라 시각으로 비교한다(".5Z"가 "Z"보다 앞에 정렬되는 문제).
  const time = (s: FormSubmission) =>
    s.submitted_at === null ? Infinity : Date.parse(s.submitted_at);
  submissions.sort((a, b) => time(a) - time(b));
  const latest = submissions.findLast((s) => s.submitted_at !== null);
  return { form_id: formId, submissions, cursor: latest?.submitted_at ?? options.since ?? null };
}

// 유즈케이스 9. forms.get 1 + responses.list → 문항별 집계. 저장해 둔 질문 목록이 있으면 summarize를 바로 쓴다.
export async function summarizeResponses(
  forms: GoogleFormsPort,
  formId: string,
): Promise<QuestionSummary[]> {
  const [{ questions }, collected] = await Promise.all([
    forms.get(formId),
    collectResponses(forms, formId),
  ]);
  return summarize(questions, collected.submissions);
}

// 유즈케이스 6. 응답자 이메일만 받아 명단과 대조한다.
export async function getSubmissionStatus(
  forms: GoogleFormsPort,
  formId: string,
  rosterEmails: string[],
): Promise<SubmissionStatus> {
  return submissionStatus(await forms.listRespondentEmails(formId), rosterEmails);
}

export interface QuizScore {
  response_id: string;
  respondent_email: string | null;
  submitted_at: string | null;
  // 자동 채점 + 교수자가 UI에서 고친 점수
  total_score: number;
  // 채점 문항 배점 합
  max_score: number;
  grades: FormSubmission['grades'];
}

// 유즈케이스 10. 배점(forms.get) + 응답 전체를 **필터 없이** 받는다. lastSubmittedTime은 채점 변경을
// 반영하지 않아 증분 조회로는 교수자가 고친 점수를 놓친다. 성적 반영은 호출자 몫이다.
export async function collectQuizScores(
  forms: GoogleFormsPort,
  formId: string,
): Promise<QuizScore[]> {
  const graded = gradedQuestions((await forms.get(formId)).questions);
  const { submissions } = await collectResponses(forms, formId, { graded });
  const maxScore = Object.values(graded).reduce((a, b) => a + b, 0);
  return submissions.map((s) => ({
    response_id: s.id,
    respondent_email: s.respondent_email,
    submitted_at: s.submitted_at,
    total_score: s.total_score ?? 0,
    max_score: maxScore,
    grades: s.grades,
  }));
}

// 유즈케이스 11. 조마다 폼이면 폼마다 부른다. reviewees는 createGroupForms 결과를 저장해 둔 것.
export async function collectPeerReviews(
  forms: GoogleFormsPort,
  formId: string,
  reviewees: Record<string, string> | null = null,
  excludeSelf = true,
): Promise<PeerScore[]> {
  const [{ questions }, collected] = await Promise.all([
    forms.get(formId),
    collectResponses(forms, formId),
  ]);
  return summarizePeerReviews(questions, collected.submissions, reviewees, excludeSelf);
}

// 유즈케이스 12. Synsory가 CSV를 만든다(폼은 Drive 내보내기가 안 된다). Excel 한글 깨짐 방지로 UTF-8 BOM.
// xlsx는 라이브러리 의존성 결정 뒤에 추가한다(docs/STUDIO_PORTING.md 결정 필요 L).
export async function exportResponsesCsv(
  forms: GoogleFormsPort,
  formId: string,
  timeZone = 'Asia/Seoul',
): Promise<ExportedFile> {
  const [structure, collected] = await Promise.all([
    forms.get(formId),
    collectResponses(forms, formId),
  ]);
  const csv = toCsv(responseTable(structure.questions, collected.submissions, timeZone));
  return {
    file_id: formId,
    filename: `${structure.title || formId} 응답.csv`,
    mime_type: 'text/csv',
    content: new TextEncoder().encode('﻿' + csv),
  };
}

// ---------- 유즈케이스 4: 기존 폼을 템플릿으로 ----------

// Drive 복사 → (title이면) 제목 변경 → 게시 → (responderEmails면) 응답자 제한. 원본은 수정하지 않는다.
// 복사본은 미게시·응답자 제한 없음·응답 0건이고 질문 ID는 원본과 같다(2026-10-06 실측).
// 교수자가 Forms UI에서 만든 폼은 Picker로 고른 뒤에만 복사할 수 있다(고르기 전 404).
export async function createFormFromTemplate(
  forms: GoogleFormsPort,
  drive: GoogleDrivePort,
  input: {
    templateFormId: string;
    name: string;
    folderId?: string;
    title?: string;
    responderEmails?: string[];
    publish?: boolean;
  },
): Promise<{ form: FormInfo; responders: ResponderResult[] }> {
  const { id } = await drive.copyFile(input.templateFormId, input.name, input.folderId);
  if (input.title) await forms.update(id, { title: input.title });
  if (input.publish ?? true) await forms.setPublishState(id, true, true);
  const responders = input.responderEmails?.length
    ? await restrictResponders(drive, id, input.responderEmails)
    : [];
  return { form: await readForm(forms, drive, id), responders };
}
