// Google Forms 도구의 Synsory 규칙: 응답 형식, 문항별 집계, 동료평가 집계, 제출 현황, 응답 표.
// synsory-api app/services/google_forms/usecases.py·mapper.py에서 외부 호출 없는 부분의 이식본.

export type QuestionKind =
  | 'choice_radio'
  | 'choice_checkbox'
  | 'choice_drop_down'
  | 'text'
  | 'paragraph'
  | 'scale'
  | 'rating'
  | 'date'
  | 'time'
  | 'grid_row'
  | 'file_upload'
  | 'unknown';

// 폼 문항 하나(폼 순서). 격자 질문은 행마다 하나(kind=grid_row, title="질문 [행]", options=열 값).
// 저장해 두면 forms.get 없이 응답을 해석할 수 있다.
export interface QuestionSpec {
  id: string;
  title: string;
  kind: QuestionKind;
  options: string[];
  point_value: number | null;
  group_title?: string;
  row_title?: string;
}

export interface AnswerGrade {
  score: number;
  correct: boolean;
  max_score: number | null;
}

// 응답 하나. 시각은 Forms가 준 RFC3339 문자열 그대로다.
export interface FormSubmission {
  id: string;
  form_id: string;
  // 이메일 수집이 VERIFIED·RESPONDER_INPUT일 때만 온다.
  respondent_email: string | null;
  created_at: string | null;
  // lastSubmittedTime. 교수자가 점수를 고쳐도 바뀌지 않는다.
  submitted_at: string | null;
  answers: Record<string, string[]>;
  file_ids: Record<string, string[]>;
  total_score: number | null;
  grades: Record<string, AnswerGrade>;
}

// 퀴즈 채점 대상 질문 ID → 배점. 퀴즈가 아니면 빈 객체.
export function gradedQuestions(questions: QuestionSpec[]): Record<string, number> {
  return Object.fromEntries(
    questions.flatMap((q) => (q.point_value === null ? [] : [[q.id, q.point_value]])),
  );
}

// "(기타)"는 객관식 '기타' 선택지 표시다.
export const OTHER_OPTION = '(기타)';

export interface QuestionSummary {
  id: string;
  title: string;
  kind: QuestionKind;
  // 이 질문에 답한 응답 수
  response_count: number;
  // 선택지·척도 값별 선택 수. 선택지 순서를 지키려고 배열로 둔다(0 포함, 끝에 "(기타)").
  counts: { option: string; count: number }[];
  other_answers: string[];
  // 척도·별점·숫자형 격자
  average: number | null;
  // 단답·장문·날짜·시간
  text_answers: string[];
}

const COUNTED = new Set<QuestionKind>([
  'choice_radio',
  'choice_checkbox',
  'choice_drop_down',
  'scale',
  'rating',
  'grid_row',
]);
const NUMERIC = new Set<QuestionKind>(['scale', 'rating', 'grid_row']);

const isNumber = (v: string) => v.trim() !== '' && !Number.isNaN(Number(v));
const round3 = (n: number) => Math.round(n * 1000) / 1000;
const average = (nums: number[]) =>
  nums.length ? round3(nums.reduce((a, b) => a + b, 0) / nums.length) : null;

// 문항별 집계.
export function summarize(
  questions: QuestionSpec[],
  submissions: FormSubmission[],
): QuestionSummary[] {
  return questions.map((q) => {
    const values = submissions.flatMap((s) => s.answers[q.id] ?? []);
    const summary: QuestionSummary = {
      id: q.id,
      title: q.title,
      kind: q.kind,
      response_count: submissions.filter((s) => (s.answers[q.id] ?? []).length > 0).length,
      counts: [],
      other_answers: [],
      average: null,
      text_answers: [],
    };
    if (!COUNTED.has(q.kind)) {
      summary.text_answers = values;
      return summary;
    }
    const counts = new Map(q.options.filter((o) => o !== OTHER_OPTION).map((o) => [o, 0]));
    let other = 0;
    for (const v of values) {
      const known = counts.get(v);
      if (known !== undefined) counts.set(v, known + 1);
      else {
        other += 1;
        summary.other_answers.push(v);
      }
    }
    summary.counts = [...counts].map(([option, count]) => ({ option, count }));
    if (other) summary.counts.push({ option: OTHER_OPTION, count: other });
    if (NUMERIC.has(q.kind)) summary.average = average(values.filter(isNumber).map(Number));
    return summary;
  });
}

export interface SubmissionStatus {
  // 명단 중 제출한 이메일
  submitted: string[];
  // 명단 중 미제출 → Synsory가 독촉 알림
  missing: string[];
  // 명단에 없는데 제출한 이메일(응답자 제한을 안 걸었거나 소유자·조교)
  not_in_roster: string[];
  // 이메일 없이 들어온 응답 수(이메일 수집을 안 켠 폼)
  without_email: number;
  // 같은 이메일로 2건 이상. 응답 1회 제한은 UI 설정이라 API로 못 막는다.
  resubmitted: Record<string, number>;
}

// 응답자 이메일과 명단을 대조한다. 대소문자 무시.
export function submissionStatus(
  respondentEmails: (string | null)[],
  rosterEmails: string[],
): SubmissionStatus {
  const counts = new Map<string, number>();
  let withoutEmail = 0;
  for (const raw of respondentEmails) {
    const email = (raw ?? '').trim().toLowerCase();
    if (email) counts.set(email, (counts.get(email) ?? 0) + 1);
    else withoutEmail += 1;
  }
  const roster = rosterEmails.map((e) => e.trim().toLowerCase());
  return {
    submitted: roster.filter((e) => counts.has(e)),
    missing: roster.filter((e) => !counts.has(e)),
    not_in_roster: [...counts.keys()].filter((e) => !roster.includes(e)).sort(),
    without_email: withoutEmail,
    resubmitted: Object.fromEntries([...counts].filter(([, n]) => n > 1)),
  };
}

// ---------- 동료평가 ----------

export interface PeerMember {
  // 격자 행 제목으로 보인다
  name: string;
  // 응답자 권한·자기 평가 판별에 쓴다
  email: string;
}

// 격자 행 제목. 같은 이름이 있으면 이메일 앞부분을 붙여 구분한다(행 제목이 같으면 응답을 구분할 수 없다).
export function memberLabels(members: PeerMember[]): string[] {
  const names = members.map((m) => m.name);
  return members.map((m) =>
    names.filter((n) => n === m.name).length === 1
      ? m.name
      : `${m.name} (${m.email.split('@')[0]})`,
  );
}

// 평가 항목마다 격자 질문 하나: 행 = 조원, 열 = 척도(단일 선택), 모든 행 필수.
// Google Forms Item JSON을 만드는 유일한 domain 코드다. 동료평가 폼의 구조 자체가 Synsory 규칙이고
// application이 만들어 port에 넘겨야 해서 여기 둔다(docs/STUDIO_PORTING.md 2절).
export function peerReviewItems(
  members: PeerMember[],
  criteria: string[],
  scale: string[],
): Record<string, unknown>[] {
  const labels = memberLabels(members);
  return criteria.map((criterion) => ({
    title: criterion,
    questionGroupItem: {
      grid: { columns: { type: 'RADIO', options: scale.map((value) => ({ value })) } },
      questions: labels.map((title) => ({ required: true, rowQuestion: { title } })),
    },
  }));
}

export interface PeerScore {
  // 피평가자 이메일(reviewees를 준 경우) 또는 격자 행 제목
  reviewee: string;
  // 평가 항목(격자 질문 제목). "(전체)"는 항목 평균의 평균이 아니라 모든 점수의 평균이다.
  criterion: string;
  average: number | null;
  // 반영된 평가 수
  count: number;
  // 자기 평가라 뺀 수
  self_excluded: number;
}

export const ALL_CRITERIA = '(전체)';

// 격자 행 질문 → 피평가자, 열 값 → 점수(숫자만).
// reviewees(행 질문 ID → 이메일)를 주면 평가자 이메일과 비교해 자기 평가를 뺄 수 있다.
export function summarizePeerReviews(
  questions: QuestionSpec[],
  submissions: FormSubmission[],
  reviewees: Record<string, string> | null = null,
  excludeSelf = true,
): PeerScore[] {
  const scores = new Map<string, { reviewee: string; criterion: string; values: number[] }>();
  const excluded = new Map<string, number>();
  for (const q of questions) {
    if (q.kind !== 'grid_row') continue;
    const reviewee = reviewees?.[q.id] ?? q.row_title ?? q.title;
    const criterion = q.group_title ?? q.title;
    const key = JSON.stringify([reviewee, criterion]);
    const entry = scores.get(key) ?? { reviewee, criterion, values: [] };
    scores.set(key, entry);
    for (const s of submissions)
      for (const v of s.answers[q.id] ?? []) {
        if (!isNumber(v)) continue;
        const self =
          excludeSelf &&
          reviewees !== null &&
          s.respondent_email !== null &&
          s.respondent_email.toLowerCase() === reviewee.toLowerCase();
        if (self) excluded.set(key, (excluded.get(key) ?? 0) + 1);
        else entry.values.push(Number(v));
      }
  }
  const out: PeerScore[] = [...scores].map(([key, e]) => ({
    reviewee: e.reviewee,
    criterion: e.criterion,
    average: average(e.values),
    count: e.values.length,
    self_excluded: excluded.get(key) ?? 0,
  }));
  for (const reviewee of new Set([...scores.values()].map((e) => e.reviewee))) {
    const keys = [...scores].filter(([, e]) => e.reviewee === reviewee);
    const values = keys.flatMap(([, e]) => e.values);
    out.push({
      reviewee,
      criterion: ALL_CRITERIA,
      average: average(values),
      count: values.length,
      self_excluded: keys.reduce((n, [key]) => n + (excluded.get(key) ?? 0), 0),
    });
  }
  return out;
}

// ---------- 응답 표 ----------

// 헤더 + 응답 행(모두 문자열). 열: 제출 시각, 이메일, 점수(퀴즈일 때), 질문별 한 열.
// 체크박스는 ", "로 잇고 격자는 행마다 한 열("질문 [행]"). 파일 업로드는 Drive 파일 ID를 잇는다.
export function responseTable(
  questions: QuestionSpec[],
  submissions: FormSubmission[],
  timeZone = 'Asia/Seoul',
  includeEmail = true,
): string[][] {
  const isQuiz = questions.some((q) => q.point_value !== null);
  // sv-SE 형식이 "YYYY-MM-DD HH:mm:ss"다.
  const format = new Intl.DateTimeFormat('sv-SE', {
    timeZone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hourCycle: 'h23',
  });
  const header = [
    '제출 시각',
    ...(includeEmail ? ['이메일'] : []),
    ...(isQuiz ? ['점수'] : []),
    ...questions.map((q) => q.title),
  ];
  const rows = submissions.map((s) => [
    s.submitted_at ? format.format(new Date(s.submitted_at)) : '',
    ...(includeEmail ? [s.respondent_email ?? ''] : []),
    ...(isQuiz ? [s.total_score === null ? '' : String(s.total_score)] : []),
    ...questions.map((q) => {
      const answers = s.answers[q.id] ?? [];
      return (answers.length ? answers : (s.file_ids[q.id] ?? [])).join(', ');
    }),
  ]);
  return [header, ...rows];
}

// RFC 4180 CSV(줄 끝 CRLF). 쉼표·따옴표·줄바꿈이 있는 칸만 따옴표로 감싼다(Python csv 기본과 같다).
export function toCsv(rows: string[][]): string {
  const cell = (v: string) => (/[",\r\n]/.test(v) ? `"${v.replaceAll('"', '""')}"` : v);
  return rows.map((r) => r.map(cell).join(',') + '\r\n').join('');
}
