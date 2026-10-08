import {
  AppError,
  groupVariables,
  renderTemplate,
  type ExternalDocument,
} from '../../domain/src/index.ts';
import { mapConcurrently } from './concurrency.ts';
import type {
  DrivePermission,
  DriveRole,
  GoogleDrivePort,
  PermissionResult,
  UploadSource,
  UploadTarget,
} from './integration-ports.ts';

// Docs·Slides·Sheets가 함께 쓰는 Drive 흐름: 그룹 파일 만들기, 공유, 마감(권한 낮추기), 되돌리기.
// synsory-api app/services/google_drive/usecases.py의 이식본.
// 외부 호출 실패(AppError)는 결과에 담고 다음 대상으로 넘어간다. 그 밖의 예외(버그)는 그대로 올라간다.
// 그룹·파일끼리는 동시에(mapConcurrently), 같은 파일의 권한 변경은 배치나 순차로 한다(Drive 공식 권고).

export interface GroupSpec {
  team_name: string;
  member_emails: string[];
}

export type ShareResult = PermissionResult;

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

// 그룹원 모두에게 편집 공유(배치 요청 하나). 사람별로 성공·실패가 담기고,
// 배치 자체가 실패하면(토큰 만료 등) 모든 사람에게 그 오류를 담는다.
export async function shareFile(
  drive: GoogleDrivePort,
  fileId: string,
  emails: string[],
  options: { notify?: boolean; message?: string } = {},
): Promise<ShareResult[]> {
  const [results, error] = await attempt(() =>
    drive.shareWithUsers(fileId, emails, 'writer', options),
  );
  return results ?? emails.map((email) => ({ email, permission_id: null, error }));
}

// 그룹마다 템플릿을 폴더 안에 복사 → 태그 치환 → 그룹원에게 편집 공유.
// 그룹당 files.copy 1 + 치환 1 + 공유 배치 1. 그룹끼리는 동시에 처리한다.
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
  const shareOptions = {
    ...(input.notify !== undefined && { notify: input.notify }),
    ...(input.shareMessage !== undefined && { message: input.shareMessage }),
  };
  return mapConcurrently(input.groups, async (group): Promise<GroupFileResult> => {
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
    if (copyError) return failed(null, copyError);
    const [replaced, replaceError] = await attempt(() => input.replaceTags(document.id, variables));
    if (replaceError) return failed(document, replaceError);
    return {
      team_name: group.team_name,
      document,
      replaced,
      shares: await shareFile(drive, document.id, group.member_emails, shareOptions),
      error: null,
    };
  });
}

// 그룹마다 텍스트 템플릿의 태그를 치환해 변환 업로드 → 그룹원에게 편집 공유. 그룹당 업로드 1 + 공유 배치 1.
// Docs는 Markdown(서식 유지), Sheets는 CSV(값만 있는 표. 서식·검증·수식·시트 여러 장은 못 넣고
// 학번 앞자리 0이 숫자로 바뀐다 → 보통은 xlsx 템플릿 복사인 createGroupFilesFromTemplate).
// 업로드가 실패한 그룹은 error만 남기고 다음 그룹을 계속한다.
export async function createGroupFilesFromContent(
  drive: GoogleDrivePort,
  input: {
    folderId: string;
    activityName: string;
    titleTemplate: string;
    bodyTemplate: string;
    source: UploadSource;
    target: UploadTarget;
    groups: GroupSpec[];
    due?: string;
    notify?: boolean;
    shareMessage?: string;
  },
): Promise<GroupFileResult[]> {
  const shareOptions = {
    ...(input.notify !== undefined && { notify: input.notify }),
    ...(input.shareMessage !== undefined && { message: input.shareMessage }),
  };
  return mapConcurrently(input.groups, async (group): Promise<GroupFileResult> => {
    const variables = groupVariables(group.team_name, input.activityName, input.due ?? null);
    const [document, error] = await attempt(() =>
      drive.createFromContent({
        name: renderTemplate(input.titleTemplate, variables),
        content: renderTemplate(input.bodyTemplate, variables),
        source: input.source,
        target: input.target,
        parentFolderId: input.folderId,
      }),
    );
    if (error)
      return { team_name: group.team_name, document: null, replaced: {}, shares: [], error };
    return {
      team_name: group.team_name,
      document,
      replaced: {},
      shares: await shareFile(drive, document.id, group.member_emails, shareOptions),
      error: null,
    };
  });
}

// 파일 하나의 writer를 toRole로 낮춘다. 소유자(owner)는 조건에 안 걸려 남는다.
// 조교·공동 교수자처럼 writer를 유지할 사람은 keepEmails로 뺀다(대소문자 무시).
// 같은 파일의 권한 변경이라 순서대로 한다(동시에 하면 마지막 쓰기만 남는다).
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

// 마감. 파일마다 downgradeEditors를 하고(파일끼리는 동시에) 한 파일이 실패해도 나머지를 계속한다.
// 다시 실행해도 안전하다(이미 낮춘 권한은 건너뛴다). 제출본 확보는 이어서 exportFile로 한다.
export async function closeSubmissions(
  drive: GoogleDrivePort,
  fileIds: string[],
  options: { toRole?: DriveRole; keepEmails?: string[] } = {},
): Promise<CloseResult[]> {
  return mapConcurrently(fileIds, async (fileId) => {
    const [downgraded, error] = await attempt(() => downgradeEditors(drive, fileId, options));
    return { file_id: fileId, downgraded: downgraded ?? [], error };
  });
}

// 되돌리기(마감 연장): 지정한 이메일의 권한을 다시 writer로. 이미 writer면 건너뛴다. 같은 파일이라 순서대로.
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
