// Docs·Slides·Sheets 어댑터와 그룹 파일 흐름, Forms 유즈케이스 13(시트 내보내기) 실측.
// 템플릿 pptx·xlsx는 레포에 두지 않고 실행 전에 만든다(README "실측"). 끝에 폴더째 휴지통으로 보낸다.
// 이 파일은 studio로 이식하지 않는다.
import { readFile } from 'node:fs/promises';
import {
  closeSubmissions,
  createForm,
  createGroupFilesFromContent,
  createGroupFilesFromTemplate,
  exportResponsesToSheet,
} from '../packages/application/src/index.ts';
import {
  createGoogleDocs,
  createGoogleDrive,
  createGoogleForms,
  createGoogleSheets,
  createGoogleSlides,
} from '../packages/infrastructure/src/index.ts';

const accessToken = process.env['GOOGLE_ACCESS_TOKEN'];
const userFolderId = process.env['DRIVE_USER_FOLDER_ID'];
const shareEmail = process.env['DRIVE_SHARE_EMAIL'];
const pptxPath = process.env['TEMPLATE_PPTX'];
const xlsxPath = process.env['TEMPLATE_XLSX'];
if (!accessToken || !userFolderId || !shareEmail || !pptxPath || !xlsxPath)
  throw new Error(
    'GOOGLE_ACCESS_TOKEN, DRIVE_USER_FOLDER_ID, DRIVE_SHARE_EMAIL, TEMPLATE_PPTX, TEMPLATE_XLSX가 필요합니다.',
  );

const token = async () => accessToken;
const drive = createGoogleDrive(token);
const docs = createGoogleDocs(token);
const slides = createGoogleSlides(token);
const sheets = createGoogleSheets(token);
const forms = createGoogleForms(token);
const results: [string, boolean][] = [];
function check(name: string, ok: boolean, detail = '') {
  results.push([name, ok]);
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? '  — ' + detail : ''}`);
}
const groups = [{ team_name: 'A조', member_emails: [shareEmail] }];
const common = {
  activityName: '과제1',
  titleTemplate: '{{activity_name}} - {{team_name}}',
  groups,
  due: '2026-10-16',
};

const folder = await drive.createFolder(
  `studio-port 실측 editors ${new Date().toISOString().slice(0, 19)}`,
  userFolderId,
);
try {
  // ---------- Docs ----------
  const docTemplate = await drive.createFromContent({
    name: 'Docs 템플릿',
    content: '# {{activity_name}}\n\n팀: **{{team_name}}**\n\n마감: {{due}}\n',
    source: 'markdown',
    target: 'doc',
    parentFolderId: folder.id,
  });
  const [docGroup] = await createGroupFilesFromTemplate(drive, {
    ...common,
    folderId: folder.id,
    templateFileId: docTemplate.id,
    replaceTags: docs.replaceTags,
  });
  const docText = new TextDecoder().decode(
    (await drive.exportFile(docGroup?.document?.id ?? '', 'txt')).content,
  );
  check(
    'Docs: copy → replaceAllText → share',
    docGroup?.error === null &&
      JSON.stringify(docGroup.replaced) === '{"team_name":1,"activity_name":1,"due":1}' &&
      docText.includes('팀: A조') &&
      !docText.includes('{{') &&
      docGroup.shares[0]?.error === null,
    JSON.stringify(docGroup?.replaced),
  );
  const [mdGroup] = await createGroupFilesFromContent(drive, {
    ...common,
    folderId: folder.id,
    bodyTemplate: '# {{activity_name}}\n\n팀: {{team_name}}\n',
    source: 'markdown',
    target: 'doc',
  });
  check(
    'Docs: Markdown template rendered and uploaded per group',
    mdGroup?.document?.kind === 'doc' && mdGroup.document.title === '과제1 - A조',
  );

  // ---------- Slides ----------
  const slideTemplate = await drive.createFromContent({
    name: 'Slides 템플릿',
    content: new Uint8Array(await readFile(pptxPath)),
    source: 'pptx',
    target: 'slides',
    parentFolderId: folder.id,
  });
  const [slideGroup] = await createGroupFilesFromTemplate(drive, {
    ...common,
    folderId: folder.id,
    templateFileId: slideTemplate.id,
    replaceTags: slides.replaceTags,
  });
  const slideText = new TextDecoder().decode(
    (await drive.exportFile(slideGroup?.document?.id ?? '', 'txt')).content,
  );
  check(
    'Slides: pptx → Slides template, copy → replaceAllText',
    slideGroup?.error === null &&
      slideGroup.replaced['team_name'] === 1 &&
      slideText.includes('과제1 - A조') &&
      slideText.includes('마감: 2026-10-16'),
    JSON.stringify(slideGroup?.replaced),
  );

  // ---------- Sheets ----------
  const sheetTemplate = await drive.createFromContent({
    name: 'Sheets 템플릿',
    content: new Uint8Array(await readFile(xlsxPath)),
    source: 'xlsx',
    target: 'sheet',
    parentFolderId: folder.id,
  });
  const [sheetGroup] = await createGroupFilesFromTemplate(drive, {
    ...common,
    folderId: folder.id,
    templateFileId: sheetTemplate.id,
    replaceTags: sheets.replaceTags,
  });
  const sheetId = sheetGroup?.document?.id ?? '';
  const tabs = await sheets.listSheets(sheetId);
  const values = await sheets.readValues(sheetId);
  const second = await sheets.readValues(sheetId, { sheetId: tabs[1]?.sheet_id ?? -1 });
  check(
    'Sheets: xlsx → Sheets, findReplace on all sheets and inside formulas, text 0123 kept',
    sheetGroup?.error === null &&
      values.values[1]?.[0] === '팀: A조' &&
      values.values[2]?.[1] === '0123' &&
      values.values[3]?.[0] === 'A조 합계' &&
      second.values[0]?.[0] === 'A조 역할',
    `replaced=${JSON.stringify(sheetGroup?.replaced)} sheetIds=${tabs.map((t) => t.sheet_id).join(',')}`,
  );
  const locked = await sheets.lockRanges(sheetId, tabs[0]?.sheet_id ?? 0, ['B3:B3']);
  await sheets.unlockRanges(sheetId, locked);
  check('Sheets: lock and unlock a range', locked.length === 1);
  const [csvGroup] = await createGroupFilesFromContent(drive, {
    ...common,
    folderId: folder.id,
    bodyTemplate: '팀,학번\n{{team_name}},0123\n',
    source: 'csv',
    target: 'sheet',
  });
  const csvValues = await sheets.readValues(csvGroup?.document?.id ?? '');
  check(
    'Sheets: CSV template (known: 0123 becomes a number)',
    csvValues.values[1]?.[0] === 'A조' && csvValues.values[1]?.[1] === 123,
    JSON.stringify(csvValues.values[1]),
  );

  const closed = await closeSubmissions(
    drive,
    [docGroup, slideGroup, sheetGroup].map((g) => g?.document?.id ?? ''),
  );
  check(
    'close: student writer → commenter on all three',
    closed.every((c) => c.error === null && c.downgraded.map((p) => p.role).join() === 'commenter'),
  );

  // ---------- Forms 유즈케이스 13 ----------
  const quiz = await createForm(forms, drive, {
    title: '내보내기 테스트',
    folderId: folder.id,
    items: [{ title: '학번', questionItem: { question: { textQuestion: {} } } }],
  });
  const exported = await exportResponsesToSheet(forms, drive, sheets, quiz.document.id, {
    folderId: folder.id,
  });
  await sheets.writeValues(exported.spreadsheet_id, exported.sheet_title, 'E1', [['교수자 메모']]);
  const again = await exportResponsesToSheet(forms, drive, sheets, quiz.document.id, {
    spreadsheetId: exported.spreadsheet_id,
    previousColumns: exported.columns,
  });
  const sheetValues = await sheets.readValues(exported.spreadsheet_id);
  const moved = await drive.getFile(exported.spreadsheet_id);
  check(
    'Forms 13: export creates sheet in folder, re-export keeps the memo column',
    exported.created &&
      !again.created &&
      moved.parent_folder_id === folder.id &&
      sheetValues.values[0]?.[0] === '제출 시각' &&
      sheetValues.values[0]?.[4] === '교수자 메모',
    JSON.stringify(sheetValues.values[0]),
  );
} finally {
  await drive.trashFile(folder.id);
  check('trashFile cleanup', (await drive.getFile(folder.id)).trashed);
}

const failed = results.filter(([, ok]) => !ok);
console.log(`\n${results.length - failed.length}/${results.length} passed`);
if (failed.length) process.exitCode = 1;
