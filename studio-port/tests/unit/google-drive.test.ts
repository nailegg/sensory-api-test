import { describe, expect, it } from 'vitest';
import { AppError, externalDocument } from '../../packages/domain/src/index.ts';
import {
  createGoogleDrive,
  documentFromDriveFile,
  ExternalApiError,
  kindFromMime,
} from '../../packages/infrastructure/src/index.ts';
import { DRIVE_FILE, NOT_FOUND } from '../fixtures/google-drive.ts';
import { recordingFetch, token } from '../fixtures/http.ts';

describe('documentFromDriveFile (synsory-api test_mapper.py)', () => {
  it('maps files.get metadata', () => {
    const d = documentFromDriveFile(DRIVE_FILE);
    expect(d).toMatchObject({
      id: 'file-1',
      provider: 'google',
      kind: 'doc',
      title: '회의록',
      owner: 'Tester',
      parent_folder_id: 'folder-1',
      created_at: '2026-09-30T12:00:00.000Z',
      modified_at: '2026-10-01T01:02:03.000Z',
      text: null,
      trashed: false,
    });
    expect(externalDocument.parse(d)).toEqual(d);
  });
  it('leaves missing optional fields null', () => {
    const d = documentFromDriveFile({ id: 'x', name: 'n' });
    expect(d.kind).toBe('file');
    expect([d.owner, d.parent_folder_id, d.url]).toEqual([null, null, null]);
  });
  it('maps kinds from mime types', () => {
    expect(kindFromMime('application/vnd.google-apps.spreadsheet')).toBe('sheet');
    expect(kindFromMime('application/vnd.google-apps.presentation')).toBe('slides');
    expect(kindFromMime('application/vnd.google-apps.form')).toBe('form');
    expect(kindFromMime('application/pdf')).toBe('file');
    expect(kindFromMime(undefined)).toBe('file');
  });
  it('keeps the trashed flag', () => {
    expect(documentFromDriveFile({ ...DRIVE_FILE, trashed: true }).trashed).toBe(true);
  });
  it('derives locked from contentRestrictions', () => {
    const with_ = (r: { readOnly?: boolean }[]) =>
      documentFromDriveFile({ ...DRIVE_FILE, contentRestrictions: r }).locked;
    expect(with_([{ readOnly: true }])).toBe(true);
    expect(with_([{ readOnly: false }])).toBe(false);
    expect(documentFromDriveFile(DRIVE_FILE).locked).toBe(false);
  });
});

describe('GoogleDrivePort requests', () => {
  it('creates a folder under a parent with metadata fields and the bearer token', async () => {
    const http = recordingFetch({
      json: { ...DRIVE_FILE, mimeType: 'application/vnd.google-apps.folder' },
    });
    const doc = await createGoogleDrive(token, http).createFolder('과제1', 'parent-1');
    const [r] = http.requests;
    expect(r?.method).toBe('POST');
    expect(r?.url.pathname).toBe('/drive/v3/files');
    expect(r?.url.searchParams.get('fields')).toContain('contentRestrictions');
    expect(r?.headers['authorization']).toBe('Bearer test-token');
    expect(r?.json).toEqual({
      name: '과제1',
      mimeType: 'application/vnd.google-apps.folder',
      parents: ['parent-1'],
    });
    expect(doc.kind).toBe('folder');
  });

  it('copies without parents when no folder is given and moves with addParents only', async () => {
    const http = recordingFetch({ json: DRIVE_FILE }, { json: DRIVE_FILE });
    const drive = createGoogleDrive(token, http);
    await drive.copyFile('tpl', '과제1 - A조');
    await drive.moveFile('file-1', 'folder-2');
    expect(http.requests[0]?.url.pathname).toBe('/drive/v3/files/tpl/copy');
    expect(http.requests[0]?.json).toEqual({ name: '과제1 - A조' });
    expect(http.requests[1]?.url.searchParams.get('addParents')).toBe('folder-2');
    expect(http.requests[1]?.url.searchParams.has('removeParents')).toBe(false);
  });

  it('lists only untrashed files', async () => {
    const http = recordingFetch({ json: { files: [DRIVE_FILE] } });
    const files = await createGoogleDrive(token, http).listFiles(5);
    expect(http.requests[0]?.url.searchParams.get('q')).toBe('trashed = false');
    expect(http.requests[0]?.url.searchParams.get('pageSize')).toBe('5');
    expect(files.map((f) => f.id)).toEqual(['file-1']);
  });

  it('uploads with conversion as multipart/related', async () => {
    const http = recordingFetch({ json: DRIVE_FILE });
    await createGoogleDrive(token, http).createFromContent({
      name: '안내문',
      content: '# 제목\n본문',
      source: 'markdown',
      target: 'doc',
      parentFolderId: 'folder-1',
    });
    const [r] = http.requests;
    expect(r?.url.pathname).toBe('/upload/drive/v3/files');
    expect(r?.url.searchParams.get('uploadType')).toBe('multipart');
    const boundary = /boundary=(.+)$/.exec(r?.headers['content-type'] ?? '')?.[1];
    expect(r?.headers['content-type']).toMatch(/^multipart\/related; boundary=/);
    expect(r?.body).toContain(
      '{"name":"안내문","mimeType":"application/vnd.google-apps.document","parents":["folder-1"]}',
    );
    expect(r?.body).toContain('Content-Type: text/markdown\r\n\r\n# 제목\n본문');
    expect(r?.body?.endsWith(`--${boundary}--`)).toBe(true);
  });

  it('uploads docx bytes converting to a Google Doc', async () => {
    const http = recordingFetch({ json: DRIVE_FILE });
    await createGoogleDrive(token, http).createFromContent({
      name: '안내문',
      content: new Uint8Array([0x50, 0x4b, 0x03, 0x04]),
      source: 'docx',
      target: 'doc',
    });
    const [r] = http.requests;
    expect(r?.body).toContain(
      '{"name":"안내문","mimeType":"application/vnd.google-apps.document"}',
    );
    expect(r?.body).toContain(
      'Content-Type: application/vnd.openxmlformats-officedocument.wordprocessingml.document\r\n\r\nPK',
    );
  });

  it('exports with the format table of the file kind', async () => {
    const http = recordingFetch(
      { json: { id: 'file-1', name: '회의록', mimeType: 'application/vnd.google-apps.document' } },
      { bytes: new TextEncoder().encode('# 회의록') },
    );
    const file = await createGoogleDrive(token, http).exportFile('file-1', 'md');
    expect(http.requests[1]?.url.pathname).toBe('/drive/v3/files/file-1/export');
    expect(http.requests[1]?.url.searchParams.get('mimeType')).toBe('text/markdown');
    expect(file.filename).toBe('회의록.md');
    expect(new TextDecoder().decode(file.content)).toBe('# 회의록');
  });

  it('refuses a format the kind does not support without exporting', async () => {
    const http = recordingFetch({
      json: { id: 'f', name: '발표', mimeType: 'application/vnd.google-apps.presentation' },
    });
    const error = await createGoogleDrive(token, http)
      .exportFile('f', 'docx')
      .catch((e: unknown) => e);
    expect(error).toBeInstanceOf(AppError);
    expect(error).toMatchObject({ code: 'UNSUPPORTED_EXPORT_FORMAT', status: 422 });
    expect(http.requests).toHaveLength(1);
  });

  it('shares without notification by default and maps the permission', async () => {
    const http = recordingFetch({
      json: { id: 'perm-1', type: 'user', role: 'writer', emailAddress: 'a@example.com' },
    });
    const p = await createGoogleDrive(token, http).shareWithUser(
      'file-1',
      'a@example.com',
      'writer',
      { message: '알림 꺼짐이면 무시' },
    );
    const [r] = http.requests;
    expect(r?.url.searchParams.get('sendNotificationEmail')).toBe('false');
    expect(r?.url.searchParams.has('emailMessage')).toBe(false);
    expect(r?.json).toEqual({ type: 'user', role: 'writer', emailAddress: 'a@example.com' });
    expect(p).toEqual({
      id: 'perm-1',
      type: 'user',
      role: 'writer',
      email: 'a@example.com',
      display_name: null,
      view: null,
    });
  });

  it('grants Forms responder access as view=published, anyone when no email', async () => {
    const http = recordingFetch(
      { json: { id: 'anyoneWithLink', type: 'anyone', role: 'reader', view: 'published' } },
      { json: { permissions: [] } },
    );
    const drive = createGoogleDrive(token, http);
    await drive.shareAsResponder('form-1', null);
    await drive.listPermissions('form-1', { includePublishedView: true });
    expect(http.requests[0]?.json).toEqual({ role: 'reader', view: 'published', type: 'anyone' });
    expect(http.requests[0]?.url.searchParams.has('sendNotificationEmail')).toBe(false);
    expect(http.requests[1]?.url.searchParams.get('includePermissionsForView')).toBe('published');
  });

  it('trashes files and accepts an empty 204 body when deleting a permission', async () => {
    const http = recordingFetch({ json: { id: 'file-1', trashed: true } }, { status: 204 });
    const drive = createGoogleDrive(token, http);
    await drive.trashFile('file-1');
    await drive.deletePermission('file-1', 'perm-1');
    expect(http.requests[0]?.json).toEqual({ trashed: true });
    expect(http.requests.map((r) => [r.method, r.url.pathname])).toEqual([
      ['PATCH', '/drive/v3/files/file-1'],
      ['DELETE', '/drive/v3/files/file-1/permissions/perm-1'],
    ]);
  });
});

describe('external errors', () => {
  const failing = async (reply: Parameters<typeof recordingFetch>[0]) =>
    createGoogleDrive(token, recordingFetch(reply))
      .getFile('x')
      .catch((e: unknown) => e);

  it('keeps Drive 404 notFound as a non rate-limit error', async () => {
    const e = await failing({ status: 404, json: NOT_FOUND });
    expect(e).toBeInstanceOf(ExternalApiError);
    expect(e).toBeInstanceOf(AppError);
    expect(e).toMatchObject({ code: 'EXTERNAL_NOT_FOUND', status: 404, reason: 'notFound' });
    // Google 원문 메시지는 externalMessage에만 두고, API 응답에 나가는 message·details에는 넣지 않는다.
    expect(e).toMatchObject({ externalMessage: 'File not found: nonexistent-id-123.' });
    expect((e as AppError).message).not.toContain('nonexistent-id-123');
    expect(JSON.stringify((e as AppError).details)).not.toContain('nonexistent-id-123');
  });

  it('treats Drive 403 user rate limit as rate limited', async () => {
    const e = await failing({
      status: 403,
      json: { error: { message: 'slow down', errors: [{ reason: 'userRateLimitExceeded' }] } },
    });
    expect(e).toMatchObject({ code: 'EXTERNAL_RATE_LIMITED', status: 429, externalStatus: 403 });
  });

  it('treats 403 insufficient permissions as not rate limited', async () => {
    const e = await failing({
      status: 403,
      json: {
        error: {
          message: 'no',
          status: 'PERMISSION_DENIED',
          errors: [{ reason: 'insufficientPermissions' }],
        },
      },
    });
    expect(e).toMatchObject({
      code: 'EXTERNAL_FAILED',
      status: 502,
      externalStatus: 403,
      apiStatus: 'PERMISSION_DENIED',
    });
  });

  it('treats 429 and RESOURCE_EXHAUSTED as rate limited', async () => {
    expect(await failing({ status: 429, text: 'busy' })).toMatchObject({ rateLimited: true });
    expect(
      await failing({ status: 400, json: { error: { status: 'RESOURCE_EXHAUSTED' } } }),
    ).toMatchObject({ rateLimited: true });
  });

  it('survives non-JSON error bodies', async () => {
    const e = await failing({ status: 502, text: '<html>bad gateway</html>' });
    expect(e).toMatchObject({
      code: 'EXTERNAL_FAILED',
      externalStatus: 502,
      reason: null,
      externalMessage: null,
    });
  });

  it('rejects responses that do not match the expected shape', async () => {
    const e = await failing({ json: { name: 'no id' } });
    expect(e).toMatchObject({ name: 'ExternalResponseError' });
  });
});
