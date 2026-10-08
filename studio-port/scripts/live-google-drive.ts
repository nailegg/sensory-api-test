// Drive 어댑터 실측. 실제 Google Drive에 폴더·문서를 만들고 확인한 뒤 휴지통으로 보낸다.
// 토큰은 synsory-api 토큰 저장소에서 받아 환경 변수로만 넘긴다 (README "실측").
// 이 파일은 studio로 이식하지 않는다.
import { AppError } from '../packages/domain/src/index.ts';
import { createGoogleDrive, ExternalApiError } from '../packages/infrastructure/src/index.ts';

const accessToken = process.env['GOOGLE_ACCESS_TOKEN'];
if (!accessToken) throw new Error('GOOGLE_ACCESS_TOKEN이 필요합니다.');
// 교수자가 Drive 웹에서 만든(앱이 못 보는) 폴더. 없으면 내 드라이브 최상위에 만든다.
const userFolderId = process.env['DRIVE_USER_FOLDER_ID'];
// 공유 실측 상대. 없으면 공유 단계를 건너뛴다.
const shareEmail = process.env['DRIVE_SHARE_EMAIL'];

const drive = createGoogleDrive(async () => accessToken);
const results: [string, boolean, string][] = [];
function check(name: string, ok: boolean, detail = '') {
  results.push([name, ok, detail]);
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? '  — ' + detail : ''}`);
}
async function failure(work: Promise<unknown>) {
  try {
    await work;
    return null;
  } catch (e) {
    return e;
  }
}

const stamp = new Date().toISOString().slice(0, 19);
const folder = await drive.createFolder(`studio-port 실측 ${stamp}`, userFolderId);
check(
  'createFolder under user folder',
  folder.kind === 'folder' && folder.parent_folder_id === (userFolderId ?? folder.parent_folder_id),
  `parent=${folder.parent_folder_id}`,
);
try {
  const doc = await drive.createFromContent({
    name: '안내문',
    content: '# 과제 안내\n\n- **마감**: 금요일\n- 팀명: {{team_name}}\n',
    source: 'markdown',
    target: 'doc',
    parentFolderId: folder.id,
  });
  check(
    'createFromContent markdown → doc',
    doc.kind === 'doc' && doc.parent_folder_id === folder.id,
  );

  const fetched = await drive.getFile(doc.id);
  check(
    'getFile metadata',
    fetched.title === '안내문' && !!fetched.url && !!fetched.created_at && !!fetched.owner,
    `owner set=${!!fetched.owner}, locked=${fetched.locked}`,
  );

  const md = await drive.exportFile(doc.id, 'md');
  const mdText = new TextDecoder().decode(md.content);
  check(
    'exportFile md keeps formatting, escapes _',
    md.filename === '안내문.md' &&
      mdText.includes('# 과제 안내') &&
      mdText.includes('**마감**') &&
      // Drive Markdown 내보내기는 _를 \_로 이스케이프한다 (docs/google_drive.md 10절).
      mdText.includes('{{team\\_name}}'),
    `${md.filename} ${JSON.stringify(mdText)}`,
  );
  const docx = await drive.exportFile(doc.id, 'docx');
  check(
    'exportFile docx',
    docx.content.length > 1000 && docx.content[0] === 0x50,
    `${docx.content.length} bytes`,
  );
  // 내보낸 docx를 다시 변환 업로드한다. 제목·굵게가 왕복에서 남는지 본다.
  const fromDocx = await drive.createFromContent({
    name: '안내문 (docx)',
    content: docx.content,
    source: 'docx',
    target: 'doc',
    parentFolderId: folder.id,
  });
  const roundText = new TextDecoder().decode((await drive.exportFile(fromDocx.id, 'md')).content);
  check(
    'createFromContent docx → doc keeps formatting',
    fromDocx.kind === 'doc' &&
      fromDocx.parent_folder_id === folder.id &&
      roundText.includes('# 과제 안내') &&
      roundText.includes('**마감**'),
    JSON.stringify(roundText),
  );
  const wrong = await failure(drive.exportFile(doc.id, 'pptx'));
  check(
    'exportFile rejects pptx for a doc',
    wrong instanceof AppError && wrong.code === 'UNSUPPORTED_EXPORT_FORMAT',
  );

  const sub = await drive.createFolder('그룹', folder.id);
  const copy = await drive.copyFile(doc.id, '안내문 - A조', folder.id);
  check('copyFile into folder', copy.kind === 'doc' && copy.parent_folder_id === folder.id);
  // Python 흐름처럼 addParents만 보낸다. 단일 부모 정책이면 원래 폴더에서 빠져야 한다.
  const moved = await drive.moveFile(copy.id, sub.id);
  check(
    'moveFile with addParents only',
    moved.parent_folder_id === sub.id,
    `parents→${moved.parent_folder_id === sub.id ? 'sub' : moved.parent_folder_id}`,
  );

  const sheet = await drive.createFromContent({
    name: '명단',
    content: '학번,이름\n0123,홍길동\n',
    source: 'csv',
    target: 'sheet',
    parentFolderId: folder.id,
  });
  const csv = await drive.exportFile(sheet.id, 'csv');
  check(
    'createFromContent csv → sheet + csv export',
    sheet.kind === 'sheet' && csv.mime_type === 'text/csv',
    JSON.stringify(new TextDecoder().decode(csv.content)),
  );

  const perms = await drive.listPermissions(doc.id);
  check(
    'listPermissions owner only',
    perms.length === 1 && perms[0]?.role === 'owner',
    `${perms.length} permission(s)`,
  );

  if (shareEmail) {
    const p = await drive.shareWithUser(doc.id, shareEmail, 'writer');
    const lowered = await drive.updatePermissionRole(doc.id, p.id, 'commenter');
    check('shareWithUser writer → commenter', p.role === 'writer' && lowered.role === 'commenter');
    await drive.deletePermission(doc.id, p.id);
    const after = await drive.listPermissions(doc.id);
    check('deletePermission', !after.some((x) => x.id === p.id));
  }

  const files = await drive.listFiles(5);
  check('listFiles', files.length > 0 && files.every((f) => !f.trashed), `${files.length} file(s)`);

  const missing = await failure(drive.getFile('nonexistent-id-123'));
  check(
    'unknown id → 404 notFound',
    missing instanceof ExternalApiError &&
      missing.externalStatus === 404 &&
      missing.reason === 'notFound',
  );
  if (userFolderId) {
    const hidden = await failure(drive.getFile(userFolderId));
    check(
      'user folder is invisible under drive.file (404)',
      hidden instanceof ExternalApiError && hidden.externalStatus === 404,
    );
  }
} finally {
  await drive.trashFile(folder.id);
  const trashed = await drive.getFile(folder.id);
  check('trashFile cleanup', trashed.trashed);
}

const failed = results.filter(([, ok]) => !ok);
console.log(`\n${results.length - failed.length}/${results.length} passed`);
if (failed.length) process.exitCode = 1;
