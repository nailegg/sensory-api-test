// google-files.ts 흐름 실측: 그룹 파일 만들기 → 마감 → 다시 마감 → 되돌리기. 끝에 휴지통으로 보낸다.
// 태그 치환은 Docs 어댑터를 옮긴 뒤에 붙인다. 지금은 치환 없이(빈 결과) Drive 흐름만 본다.
// 실행 방법은 README "실측". 이 파일은 studio로 이식하지 않는다.
import {
  closeSubmissions,
  createGroupFilesFromTemplate,
  restoreEditors,
} from '../packages/application/src/index.ts';
import { createGoogleDrive } from '../packages/infrastructure/src/index.ts';

const accessToken = process.env['GOOGLE_ACCESS_TOKEN'];
const userFolderId = process.env['DRIVE_USER_FOLDER_ID'];
const shareEmail = process.env['DRIVE_SHARE_EMAIL'];
if (!accessToken || !userFolderId || !shareEmail)
  throw new Error('GOOGLE_ACCESS_TOKEN, DRIVE_USER_FOLDER_ID, DRIVE_SHARE_EMAIL이 필요합니다.');
// Google 계정이 아닌 주소. 알림 없이 공유하면 400 invalidSharingRequest (docs/google_drive.md 10절).
const nonGoogleEmail = 'nobody@synsory.invalid';

const drive = createGoogleDrive(async () => accessToken);
const results: [string, boolean][] = [];
function check(name: string, ok: boolean, detail = '') {
  results.push([name, ok]);
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? '  — ' + detail : ''}`);
}

const folder = await drive.createFolder(
  `studio-port 실측 google-files ${new Date().toISOString().slice(0, 19)}`,
  userFolderId,
);
try {
  const template = await drive.createFromContent({
    name: '템플릿',
    content: '# {{activity_name}}\n\n팀: {{team_name}}\n',
    source: 'markdown',
    target: 'doc',
    parentFolderId: folder.id,
  });

  const groups = await createGroupFilesFromTemplate(drive, {
    folderId: folder.id,
    activityName: '과제1',
    titleTemplate: '{{activity_name}} - {{team_name}}',
    templateFileId: template.id,
    groups: [
      { team_name: 'A조', member_emails: [shareEmail, nonGoogleEmail] },
      { team_name: 'B조', member_emails: [] },
    ],
    replaceTags: async () => ({}),
  });
  const [a, b] = groups;
  check(
    'group copies named from the title template, inside the folder',
    a?.document?.title === '과제1 - A조' &&
      b?.document?.title === '과제1 - B조' &&
      a.document.parent_folder_id === folder.id,
  );
  check(
    'share continues after a non-Google email fails',
    a?.shares[0]?.error === null && a.shares[1]?.error?.code === 'EXTERNAL_FAILED',
    `second share: ${a?.shares[1]?.error?.code} ${JSON.stringify(a?.shares[1]?.error?.details)}`,
  );

  const [invisible] = await createGroupFilesFromTemplate(drive, {
    folderId: folder.id,
    activityName: '과제1',
    titleTemplate: '{{team_name}}',
    templateFileId: userFolderId,
    groups: [{ team_name: 'C조', member_emails: [shareEmail] }],
    replaceTags: async () => ({}),
  });
  check(
    'template not visible to the app → EXTERNAL_NOT_FOUND, nothing copied',
    invisible?.document === null && invisible.error?.code === 'EXTERNAL_NOT_FOUND',
  );

  const ids = groups.flatMap((g) => (g.document ? [g.document.id] : []));
  const closed = await closeSubmissions(drive, [...ids, 'nonexistent-id-123']);
  check(
    'close downgrades the student writer and continues past a missing file',
    closed[0]?.downgraded.map((p) => p.role).join() === 'commenter' &&
      closed[1]?.downgraded.length === 0 &&
      closed[2]?.error?.code === 'EXTERNAL_NOT_FOUND',
  );
  const again = await closeSubmissions(drive, ids);
  check(
    'closing again changes nothing',
    again.every((r) => r.downgraded.length === 0 && !r.error),
  );

  const restored = await restoreEditors(drive, ids[0] ?? '', [shareEmail.toUpperCase()]);
  check(
    'restore brings the listed student back to writer (case-insensitive)',
    restored.map((p) => p.role).join() === 'writer',
  );
} finally {
  await drive.trashFile(folder.id);
  check('trashFile cleanup', (await drive.getFile(folder.id)).trashed);
}

const failed = results.filter(([, ok]) => !ok);
console.log(`\n${results.length - failed.length}/${results.length} passed`);
if (failed.length) process.exitCode = 1;
