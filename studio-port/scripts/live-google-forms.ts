// Forms 흐름 실측. 응답은 API로 넣을 수 없어 응답 수집은 0건 상태만 본다(응답 해석은 단위 테스트와 Python 실측 샘플).
// 실행 방법은 README "실측". 끝에 폴더째 휴지통으로 보낸다. 이 파일은 studio로 이식하지 않는다.
import {
  closeForm,
  collectResponses,
  createForm,
  createFormFromTemplate,
  createGroupForms,
  exportResponsesCsv,
  getSubmissionStatus,
  openForm,
  restrictResponders,
} from '../packages/application/src/index.ts';
import { createGoogleDrive, createGoogleForms } from '../packages/infrastructure/src/index.ts';

const accessToken = process.env['GOOGLE_ACCESS_TOKEN'];
const userFolderId = process.env['DRIVE_USER_FOLDER_ID'];
const shareEmail = process.env['DRIVE_SHARE_EMAIL'];
if (!accessToken || !userFolderId || !shareEmail)
  throw new Error('GOOGLE_ACCESS_TOKEN, DRIVE_USER_FOLDER_ID, DRIVE_SHARE_EMAIL이 필요합니다.');
const nonGoogleEmail = 'nobody@synsory.invalid';

const drive = createGoogleDrive(async () => accessToken);
const forms = createGoogleForms(async () => accessToken);
const results: [string, boolean][] = [];
function check(name: string, ok: boolean, detail = '') {
  results.push([name, ok]);
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? '  — ' + detail : ''}`);
}

const folder = await drive.createFolder(
  `studio-port 실측 google-forms ${new Date().toISOString().slice(0, 19)}`,
  userFolderId,
);
try {
  const quiz = await createForm(forms, drive, {
    title: '1차 퀴즈',
    folderId: folder.id,
    description: '연습용',
    emailCollection: 'VERIFIED',
    quiz: true,
    items: [
      { title: '학번', questionItem: { question: { required: true, textQuestion: {} } } },
      {
        title: '404의 뜻',
        questionItem: {
          question: {
            grading: { pointValue: 2, correctAnswers: { answers: [{ value: '찾을 수 없음' }] } },
            choiceQuestion: {
              type: 'RADIO',
              options: [{ value: '권한 없음' }, { value: '찾을 수 없음' }],
            },
          },
        },
      },
      {
        title: '난이도',
        questionItem: { question: { scaleQuestion: { low: 0, high: 3 } } },
      },
    ],
  });
  check(
    'createForm: published after items, in folder, quiz + VERIFIED',
    quiz.published === true &&
      quiz.accepting_responses === true &&
      quiz.document.parent_folder_id === folder.id &&
      quiz.is_quiz &&
      quiz.email_collection === 'VERIFIED' &&
      quiz.document.title === '1차 퀴즈' &&
      !!quiz.responder_url,
  );
  const kinds = quiz.questions.map((q) => `${q.kind}${q.point_value ? `(${q.point_value})` : ''}`);
  check(
    'questions read back with kinds and point values',
    kinds.join() === 'text,choice_radio(2),scale',
    kinds.join(),
  );
  const scale = quiz.questions.find((q) => q.kind === 'scale');
  check(
    'scale 0–3 keeps the 0 option (Forms omits low=0)',
    scale?.options.join() === '0,1,2,3',
    `options=${scale?.options.join()}`,
  );

  const closed = await closeForm(forms, drive, quiz.document.id);
  const reopened = await openForm(forms, drive, quiz.document.id);
  check(
    'closeForm keeps published, stops responses; openForm resumes',
    closed.published === true &&
      closed.accepting_responses === false &&
      reopened.accepting_responses === true,
  );

  const restricted = await restrictResponders(drive, quiz.document.id, [shareEmail]);
  const perms = await drive.listPermissions(quiz.document.id, { includePublishedView: true });
  check(
    'restrictResponders adds the student and removes anyoneWithLink',
    restricted.every((r) => r.error === null) &&
      perms.some((p) => p.view === 'published' && p.type === 'user') &&
      !perms.some((p) => p.type === 'anyone'),
    `${perms.filter((p) => p.view === 'published').length} responder permission(s)`,
  );
  const rerun = await restrictResponders(drive, quiz.document.id, [shareEmail]);
  check(
    'restrictResponders rerun is safe',
    rerun.every((r) => r.error === null),
  );

  const collected = await collectResponses(forms, quiz.document.id);
  const status = await getSubmissionStatus(forms, quiz.document.id, [shareEmail]);
  // TextDecoder는 기본으로 BOM을 지우므로 ignoreBOM으로 남겨서 확인한다.
  const csv = new TextDecoder('utf-8', { ignoreBOM: true }).decode(
    (await exportResponsesCsv(forms, quiz.document.id)).content,
  );
  check(
    'no responses: empty collect, roster missing, CSV header only',
    collected.submissions.length === 0 &&
      collected.cursor === null &&
      status.missing.length === 1 &&
      csv === '﻿제출 시각,이메일,점수,학번,404의 뜻,난이도\r\n',
    JSON.stringify(csv.slice(1)),
  );

  const [group] = await createGroupForms(forms, drive, {
    folderId: folder.id,
    activityName: '1차',
    groups: [
      {
        team_name: 'A조',
        members: [
          { name: '가', email: shareEmail },
          { name: '나', email: nonGoogleEmail },
        ],
      },
    ],
    criteria: ['기여도', '협업'],
    scale: ['1', '2', '3'],
  });
  check(
    'createGroupForms: grid rows → member emails, partial responder failure',
    group?.error === null &&
      group.form?.document.title === '1차 동료평가 - A조' &&
      Object.values(group.reviewees).sort().join() ===
        [shareEmail, shareEmail, nonGoogleEmail, nonGoogleEmail].sort().join() &&
      group.responders.map((r) => r.error === null).join() === 'true,false,true',
    `responders: ${group?.responders.map((r) => r.error?.code ?? 'ok').join()}`,
  );

  const copy = await createFormFromTemplate(forms, drive, {
    templateFormId: quiz.document.id,
    name: '1차 퀴즈 사본',
    folderId: folder.id,
    title: '1차 퀴즈 (B반)',
    responderEmails: [shareEmail],
  });
  check(
    'createFormFromTemplate: retitled, published, same question ids',
    copy.form.document.title === '1차 퀴즈 (B반)' &&
      copy.form.published === true &&
      copy.form.questions.map((q) => q.id).join() === quiz.questions.map((q) => q.id).join(),
  );
} finally {
  await drive.trashFile(folder.id);
  check('trashFile cleanup', (await drive.getFile(folder.id)).trashed);
}

const failed = results.filter(([, ok]) => !ok);
console.log(`\n${results.length - failed.length}/${results.length} passed`);
if (failed.length) process.exitCode = 1;
