// synsory-api tests/google_drive/test_mapper.py의 DRIVE_FILE과 같은 값.
export const DRIVE_FILE = {
  id: 'file-1',
  name: '회의록',
  mimeType: 'application/vnd.google-apps.document',
  webViewLink: 'https://docs.google.com/document/d/file-1/edit',
  createdTime: '2026-09-30T12:00:00.000Z',
  modifiedTime: '2026-10-01T01:02:03.000Z',
  owners: [{ displayName: 'Tester' }],
  parents: ['folder-1'],
  trashed: false,
};

// synsory-api samples/google_drive/error-trash-not-found.json의 Drive 404. 오타 ID와 앱이 못 보는 파일이 같은 응답이다.
export const NOT_FOUND = {
  error: {
    code: 404,
    message: 'File not found: nonexistent-id-123.',
    errors: [{ reason: 'notFound', message: 'File not found: nonexistent-id-123.' }],
  },
};
