import { z } from 'zod';
import { AppError, type DocumentKind, type ExternalDocument } from '../../domain/src/index.ts';
import type {
  DrivePermission,
  ExportFormat,
  GoogleDrivePort,
  UploadSource,
  UploadTarget,
} from '../../application/src/index.ts';
import {
  externalRequest,
  readJson,
  type AccessToken,
  type ExternalRequest,
  type HttpOptions,
} from './external-http.ts';

// Google Drive v3 어댑터. synsory-api app/services/google_drive/client.py + mapper.py의 이식본.
// 쿼터 단위·함정은 synsory-api docs/google_drive.md 8절·10절.

const BASE_URL = 'https://www.googleapis.com/drive/v3';
const UPLOAD_URL = 'https://www.googleapis.com/upload/drive/v3';

// ExternalDocument를 채우는 데 필요한 최소 필드. Docs·Sheets·Slides·Forms 어댑터도 쓴다.
export const DOCUMENT_META_FIELDS =
  'id,name,mimeType,webViewLink,createdTime,modifiedTime,owners(displayName),parents,trashed,contentRestrictions(readOnly,reason,restrictionTime)';
const PERMISSION_FIELDS = 'id,type,role,emailAddress,displayName,view';

const FOLDER_MIME = 'application/vnd.google-apps.folder';
const NATIVE_MIME: Record<UploadTarget | 'form', string> = {
  doc: 'application/vnd.google-apps.document',
  sheet: 'application/vnd.google-apps.spreadsheet',
  slides: 'application/vnd.google-apps.presentation',
  form: 'application/vnd.google-apps.form',
};
const KIND_BY_MIME = new Map<string, DocumentKind>([
  [NATIVE_MIME.doc, 'doc'],
  [NATIVE_MIME.sheet, 'sheet'],
  [NATIVE_MIME.slides, 'slides'],
  [NATIVE_MIME.form, 'form'],
  [FOLDER_MIME, 'folder'],
]);

const DOCX = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document';
const PPTX = 'application/vnd.openxmlformats-officedocument.presentationml.presentation';
const XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet';

const UPLOAD_MIME: Record<UploadSource, string> = {
  markdown: 'text/markdown',
  pptx: PPTX,
  xlsx: XLSX,
  csv: 'text/csv',
};

// files.export 형식표. 파일 종류마다 가능한 형식이 다르다.
const EXPORT_MIME: Partial<Record<DocumentKind, Partial<Record<ExportFormat, string>>>> = {
  doc: {
    docx: DOCX,
    pdf: 'application/pdf',
    txt: 'text/plain',
    md: 'text/markdown',
    html: 'text/html',
  },
  // Slides 이미지(png 등)는 Drive export에 없다. 슬라이드 이미지는 Slides getThumbnail.
  slides: {
    pptx: PPTX,
    pdf: 'application/pdf',
    txt: 'text/plain',
    odp: 'application/vnd.oasis.opendocument.presentation',
  },
  // csv·tsv는 첫 시트만 내보낸다. 전체 보존은 xlsx.
  sheet: {
    xlsx: XLSX,
    pdf: 'application/pdf',
    csv: 'text/csv',
    tsv: 'text/tab-separated-values',
    ods: 'application/vnd.oasis.opendocument.spreadsheet',
    zip: 'application/zip',
  },
};

export const driveFile = z.object({
  id: z.string(),
  name: z.string().optional(),
  mimeType: z.string().optional(),
  webViewLink: z.string().optional(),
  createdTime: z.string().optional(),
  modifiedTime: z.string().optional(),
  owners: z.array(z.object({ displayName: z.string().optional() })).optional(),
  parents: z.array(z.string()).optional(),
  trashed: z.boolean().optional(),
  contentRestrictions: z.array(z.object({ readOnly: z.boolean().optional() })).optional(),
});
export type DriveFile = z.infer<typeof driveFile>;

const drivePermission = z.object({
  id: z.string(),
  type: z.enum(['user', 'group', 'domain', 'anyone']),
  role: z.string(),
  emailAddress: z.string().optional(),
  displayName: z.string().optional(),
  view: z.string().optional(),
});

export function kindFromMime(mimeType: string | undefined): DocumentKind {
  return KIND_BY_MIME.get(mimeType ?? '') ?? 'file';
}

// files.get 응답(DOCUMENT_META_FIELDS 기준) → ExternalDocument.
// Docs·Sheets·Slides·Forms 어댑터는 자기 API 응답으로 title·text를 보강할 때 이 결과를 바탕으로 쓴다.
export function documentFromDriveFile(
  file: DriveFile,
  text: string | null = null,
): ExternalDocument {
  return {
    id: file.id,
    provider: 'google',
    kind: kindFromMime(file.mimeType),
    title: file.name ?? '',
    url: file.webViewLink ?? null,
    mime_type: file.mimeType ?? null,
    owner: file.owners?.[0]?.displayName ?? null,
    created_at: file.createdTime ?? null,
    modified_at: file.modifiedTime ?? null,
    parent_folder_id: file.parents?.[0] ?? null,
    trashed: file.trashed ?? false,
    locked: (file.contentRestrictions ?? []).some((r) => r.readOnly === true),
    text,
  };
}

function permissionFromDrive(p: z.infer<typeof drivePermission>): DrivePermission {
  return {
    id: p.id,
    type: p.type,
    role: p.role,
    email: p.emailAddress ?? null,
    display_name: p.displayName ?? null,
    view: p.view ?? null,
  };
}

// Drive multipart/related 본문: 메타데이터 JSON + 파일 바이트.
function multipartRelated(metadata: unknown, content: Uint8Array, contentType: string) {
  const boundary = 'synsory-' + crypto.randomUUID();
  const encoder = new TextEncoder();
  const head = encoder.encode(
    `--${boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n${JSON.stringify(metadata)}\r\n` +
      `--${boundary}\r\nContent-Type: ${contentType}\r\n\r\n`,
  );
  const tail = encoder.encode(`\r\n--${boundary}--`);
  const body = new Uint8Array(head.length + content.length + tail.length);
  body.set(head, 0);
  body.set(content, head.length);
  body.set(tail, head.length + content.length);
  return { body, contentType: `multipart/related; boundary=${boundary}` };
}

function withParent(metadata: Record<string, unknown>, parentFolderId?: string) {
  return parentFolderId ? { ...metadata, parents: [parentFolderId] } : metadata;
}

export function createGoogleDrive(
  accessToken: AccessToken,
  options: HttpOptions = {},
): GoogleDrivePort {
  const call = async (request: ExternalRequest) =>
    externalRequest(await accessToken(), request, options);
  const document = async (request: ExternalRequest) => {
    const response = await call({
      ...request,
      query: { fields: DOCUMENT_META_FIELDS, ...request.query },
    });
    return documentFromDriveFile(await readJson(response, driveFile));
  };
  const permission = async (request: ExternalRequest) => {
    const response = await call({
      ...request,
      query: { fields: PERMISSION_FIELDS, ...request.query },
    });
    return permissionFromDrive(await readJson(response, drivePermission));
  };
  return {
    // files.get (쿼터 5)
    getFile: (fileId) => document({ method: 'GET', url: `${BASE_URL}/files/${fileId}` }),

    // files.create (쿼터 50)
    createFolder: (name, parentFolderId) =>
      document({
        method: 'POST',
        url: `${BASE_URL}/files`,
        json: withParent({ name, mimeType: FOLDER_MIME }, parentFolderId),
      }),

    createFromContent({ name, content, source, target, parentFolderId }) {
      const bytes = typeof content === 'string' ? new TextEncoder().encode(content) : content;
      const metadata = withParent({ name, mimeType: NATIVE_MIME[target] }, parentFolderId);
      const { body, contentType } = multipartRelated(metadata, bytes, UPLOAD_MIME[source]);
      return document({
        method: 'POST',
        url: `${UPLOAD_URL}/files`,
        query: { uploadType: 'multipart' },
        headers: { 'content-type': contentType },
        body,
      });
    },

    copyFile: (fileId, name, parentFolderId) =>
      document({
        method: 'POST',
        url: `${BASE_URL}/files/${fileId}/copy`,
        json: withParent({ name }, parentFolderId),
      }),

    // files.update (쿼터 50)
    moveFile: (fileId, toFolderId) =>
      document({
        method: 'PATCH',
        url: `${BASE_URL}/files/${fileId}`,
        query: { addParents: toFolderId },
        json: {},
      }),

    // files.list (쿼터 100, 비싸다). 휴지통 파일도 기본으로 오므로 항상 뺀다.
    async listFiles(pageSize = 20) {
      const response = await call({
        method: 'GET',
        url: `${BASE_URL}/files`,
        query: { pageSize, q: 'trashed = false', fields: `files(${DOCUMENT_META_FIELDS})` },
      });
      const data = await readJson(response, z.object({ files: z.array(driveFile).default([]) }));
      return data.files.map((f) => documentFromDriveFile(f));
    },

    // files.get + files.export (쿼터 5 + 200). 결과는 10MB까지.
    async exportFile(fileId, format) {
      const meta = await readJson(
        await call({
          method: 'GET',
          url: `${BASE_URL}/files/${fileId}`,
          query: { fields: 'id,name,mimeType' },
        }),
        driveFile,
      );
      const mimeType = EXPORT_MIME[kindFromMime(meta.mimeType)]?.[format];
      if (!mimeType)
        throw new AppError(
          'UNSUPPORTED_EXPORT_FORMAT',
          422,
          '이 파일 종류는 해당 형식으로 내보낼 수 없습니다.',
        );
      const response = await call({
        method: 'GET',
        url: `${BASE_URL}/files/${fileId}/export`,
        query: { mimeType },
      });
      return {
        file_id: fileId,
        filename: `${meta.name ?? fileId}.${format}`,
        mime_type: mimeType,
        content: new Uint8Array(await response.arrayBuffer()),
      };
    },

    async trashFile(fileId) {
      await call({
        method: 'PATCH',
        url: `${BASE_URL}/files/${fileId}`,
        query: { fields: 'id,trashed' },
        json: { trashed: true },
      });
    },

    // permissions.create. 같은 이메일을 다시 공유하면 기존 permission이 온다(재시도 안전).
    shareWithUser: (fileId, email, role, { notify = false, message } = {}) =>
      permission({
        method: 'POST',
        url: `${BASE_URL}/files/${fileId}/permissions`,
        query: { sendNotificationEmail: notify, emailMessage: notify ? message : undefined },
        json: { type: 'user', role, emailAddress: email },
      }),

    // 편집 공유(view 없음)와 다르다. synsory-api docs/google_forms.md 10절 4항.
    shareAsResponder: (fileId, email) =>
      permission({
        method: 'POST',
        url: `${BASE_URL}/files/${fileId}/permissions`,
        query: { sendNotificationEmail: email ? false : undefined },
        json: {
          role: 'reader',
          view: 'published',
          ...(email ? { type: 'user', emailAddress: email } : { type: 'anyone' }),
        },
      }),

    async listPermissions(fileId, { includePublishedView = false } = {}) {
      const response = await call({
        method: 'GET',
        url: `${BASE_URL}/files/${fileId}/permissions`,
        query: {
          fields: `permissions(${PERMISSION_FIELDS})`,
          includePermissionsForView: includePublishedView ? 'published' : undefined,
        },
      });
      const data = await readJson(
        response,
        z.object({ permissions: z.array(drivePermission).default([]) }),
      );
      return data.permissions.map(permissionFromDrive);
    },

    updatePermissionRole: (fileId, permissionId, role) =>
      permission({
        method: 'PATCH',
        url: `${BASE_URL}/files/${fileId}/permissions/${permissionId}`,
        json: { role },
      }),

    async deletePermission(fileId, permissionId) {
      await call({
        method: 'DELETE',
        url: `${BASE_URL}/files/${fileId}/permissions/${permissionId}`,
      });
    },
  };
}
