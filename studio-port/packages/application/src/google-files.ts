import {
  AppError,
  groupVariables,
  renderTemplate,
  type ExternalDocument,
} from '../../domain/src/index.ts';
import type { DrivePermission, DriveRole, GoogleDrivePort } from './integration-ports.ts';

// Docs·Slides·Sheets가 함께 쓰는 Drive 흐름: 그룹 파일 만들기, 공유, 마감(권한 낮추기), 되돌리기.
// synsory-api app/services/google_drive/usecases.py의 이식본.
// 외부 호출 실패(AppError)는 결과에 담고 다음 대상으로 넘어간다. 그 밖의 예외(버그)는 그대로 올라간다.

export interface GroupSpec {
  team_name: string;
  member_emails: string[];
}

export interface ShareResult {
  email: string;
  permission_id: string | null;
  error: AppError | null;
}

export interface GroupFileResult {
  team_name: string;
  document: ExternalDocument | null;
  // 태그별 치환 횟수. 0이면 템플릿에 그 태그가 없거나 서식이 갈라진 것이다.
  replaced: Record<string, number>;
  shares: ShareResult[];
  error: AppError | null;
}

// (복사본 파일 ID, 변수) → 태그별 치환 횟수. Docs·Slides·Sheets 어댑터의 치환 요청을 넘긴다.
export type ReplaceTags = (
  fileId: string,
  variables: Record<string, string>,
) => Promise<Record<string, number>>;

async function attempt<T>(work: () => Promise<T>): Promise<[T, null] | [null, AppError]> {
  try {
    return [await work(), null];
  } catch (e) {
    if (e instanceof AppError) return [null, e];
    throw e;
  }
}

// 그룹원마다 편집 공유. 한 명이 실패해도 나머지는 계속한다.
export async function shareFile(
  drive: GoogleDrivePort,
  fileId: string,
  emails: string[],
  options: { notify?: boolean; message?: string } = {},
): Promise<ShareResult[]> {
  const results: ShareResult[] = [];
  for (const email of emails) {
    const [permission, error] = await attempt(() =>
      drive.shareWithUser(fileId, email, 'writer', options),
    );
    results.push({ email, permission_id: permission?.id ?? null, error });
  }
  return results;
}

// 그룹마다 템플릿을 폴더 안에 복사 → 태그 치환 → 그룹원에게 편집 공유.
// 그룹당 files.copy 1 + 치환 1 + 그룹원 수만큼 permissions.create.
// 템플릿은 앱이 변환 업로드한 파일이거나 교수자가 Picker로 고른 파일이다. 원본은 건드리지 않는다.
// 복사가 실패하면(Picker로 안 고른 템플릿이면 404) 그 그룹은 error만 남긴다.
// 치환이 실패하면 복사본은 폴더에 남기고 공유는 하지 않는다.
export async function createGroupFilesFromTemplate(
  drive: GoogleDrivePort,
  input: {
    folderId: string;
    activityName: string;
    titleTemplate: string;
    templateFileId: string;
    groups: GroupSpec[];
    replaceTags: ReplaceTags;
    due?: string;
    notify?: boolean;
    shareMessage?: string;
  },
): Promise<GroupFileResult[]> {
  const results: GroupFileResult[] = [];
  for (const group of input.groups) {
    const variables = groupVariables(group.team_name, input.activityName, input.due ?? null);
    const failed = (document: ExternalDocument | null, error: AppError): GroupFileResult => ({
      team_name: group.team_name,
      document,
      replaced: {},
      shares: [],
      error,
    });
    const [document, copyError] = await attempt(() =>
      drive.copyFile(
        input.templateFileId,
        renderTemplate(input.titleTemplate, variables),
        input.folderId,
      ),
    );
    if (copyError) {
      results.push(failed(null, copyError));
      continue;
    }
    const [replaced, replaceError] = await attempt(() => input.replaceTags(document.id, variables));
    if (replaceError) {
      results.push(failed(document, replaceError));
      continue;
    }
    const shareOptions = {
      ...(input.notify !== undefined && { notify: input.notify }),
      ...(input.shareMessage !== undefined && { message: input.shareMessage }),
    };
    results.push({
      team_name: group.team_name,
      document,
      replaced,
      shares: await shareFile(drive, document.id, group.member_emails, shareOptions),
      error: null,
    });
  }
  return results;
}

// 파일 하나의 writer를 toRole로 낮춘다. 소유자(owner)는 조건에 안 걸려 남는다.
// 조교·공동 교수자처럼 writer를 유지할 사람은 keepEmails로 뺀다(대소문자 무시).
export async function downgradeEditors(
  drive: GoogleDrivePort,
  fileId: string,
  options: { toRole?: DriveRole; keepEmails?: string[] } = {},
): Promise<DrivePermission[]> {
  const keep = new Set((options.keepEmails ?? []).map((e) => e.toLowerCase()));
  const changed: DrivePermission[] = [];
  for (const p of await drive.listPermissions(fileId)) {
    if (p.role !== 'writer' || (p.type !== 'user' && p.type !== 'group')) continue;
    if (keep.has((p.email ?? '').toLowerCase())) continue;
    changed.push(await drive.updatePermissionRole(fileId, p.id, options.toRole ?? 'commenter'));
  }
  return changed;
}

export interface CloseResult {
  file_id: string;
  downgraded: DrivePermission[];
  error: AppError | null;
}

// 마감. 파일마다 downgradeEditors를 하고 한 파일이 실패해도 나머지를 계속한다.
// 다시 실행해도 안전하다(이미 낮춘 권한은 건너뛴다). 제출본 확보는 이어서 exportFile로 한다.
export async function closeSubmissions(
  drive: GoogleDrivePort,
  fileIds: string[],
  options: { toRole?: DriveRole; keepEmails?: string[] } = {},
): Promise<CloseResult[]> {
  const results: CloseResult[] = [];
  for (const fileId of fileIds) {
    const [downgraded, error] = await attempt(() => downgradeEditors(drive, fileId, options));
    results.push({ file_id: fileId, downgraded: downgraded ?? [], error });
  }
  return results;
}

// 되돌리기(마감 연장): 지정한 이메일의 권한을 다시 writer로. 이미 writer면 건너뛴다.
export async function restoreEditors(
  drive: GoogleDrivePort,
  fileId: string,
  emails: string[],
): Promise<DrivePermission[]> {
  const wanted = new Set(emails.map((e) => e.toLowerCase()));
  const changed: DrivePermission[] = [];
  for (const p of await drive.listPermissions(fileId))
    if (wanted.has((p.email ?? '').toLowerCase()) && p.role !== 'writer')
      changed.push(await drive.updatePermissionRole(fileId, p.id, 'writer'));
  return changed;
}
