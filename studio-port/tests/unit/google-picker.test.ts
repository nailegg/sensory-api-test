import { expect, it } from 'vitest';
import { acceptPickedFile, type GoogleDrivePort } from '../../packages/application/src/index.ts';
import { pickedFile, pickerSession } from '../../packages/contracts/src/index.ts';
import { documentFromDriveFile, pickerAppId } from '../../packages/infrastructure/src/index.ts';
import { pickGoogleFile, type PickerApi } from '../../packages/ui/src/index.ts';
import { fakePort, notFound } from '../fixtures/fake-port.ts';

// google.picker 흉내. 빌더 호출을 기록하고, setVisible 때 정해 둔 응답들을 콜백에 넘긴다.
function fakePicker(responses: { action: string; docs?: { id: string }[] }[]) {
  const calls: unknown[][] = [];
  class Builder {
    callback: (d: { action: string; docs?: { id: string }[] }) => void = () => {};
    setOAuthToken = (v: string) => (calls.push(['token', v]), this);
    setDeveloperKey = (v: string) => (calls.push(['key', v]), this);
    setAppId = (v: string) => (calls.push(['appId', v]), this);
    setOrigin = (v: string) => (calls.push(['origin', v]), this);
    setTitle = (v: string) => (calls.push(['title', v]), this);
    addView = (v: unknown) => (calls.push(['view', v]), this);
    setCallback = (cb: Builder['callback']) => ((this.callback = cb), this);
    build = () => ({ setVisible: () => responses.forEach((r) => this.callback(r)) });
  }
  class View {
    state: Record<string, unknown> = {};
    constructor(id: string) {
      this.state['viewId'] = id;
    }
    setMimeTypes = (v: string) => ((this.state['mime'] = v), this);
    setIncludeFolders = (v: boolean) => ((this.state['folders'] = v), this);
    setSelectFolderEnabled = (v: boolean) => ((this.state['selectFolder'] = v), this);
  }
  const api = {
    PickerBuilder: Builder,
    DocsView: View,
    ViewId: { DOCS: 'all' },
    Action: { PICKED: 'picked', CANCEL: 'cancel' },
  } as unknown as PickerApi;
  return { api, calls };
}

const OPTIONS = {
  accessToken: 'tok',
  developerKey: 'key',
  appId: '123456',
  origin: 'http://localhost:5173',
  kinds: ['doc' as const, 'slides' as const],
};

it('opens the Picker with token, key, appId and a MIME-filtered view; ignores "loaded"', async () => {
  const p = fakePicker([{ action: 'loaded' }, { action: 'picked', docs: [{ id: 'f1' }] }]);
  const id = await pickGoogleFile(OPTIONS, async () => p.api);
  expect(id).toBe('f1');
  expect(
    p.calls.filter((c) => ['token', 'key', 'appId', 'origin'].includes(String(c[0]))),
  ).toEqual([
    ['token', 'tok'],
    ['key', 'key'],
    ['appId', '123456'],
    ['origin', 'http://localhost:5173'],
  ]);
  const view = p.calls.find((c) => c[0] === 'view')?.[1] as { state: Record<string, unknown> };
  expect(view.state).toEqual({
    viewId: 'all',
    mime: 'application/vnd.google-apps.document,application/vnd.google-apps.presentation',
    folders: true,
    selectFolder: false,
  });
});

it('returns null when cancelled', async () => {
  const p = fakePicker([{ action: 'cancel' }]);
  expect(await pickGoogleFile(OPTIONS, async () => p.api)).toBeNull();
});

it('derives the project number from the web client ID unless set', () => {
  expect(pickerAppId('123456789-abc.apps.googleusercontent.com')).toBe('123456789');
  expect(pickerAppId('123456789-abc.apps.googleusercontent.com', '42')).toBe('42');
  expect(pickerAppId('not-a-number.apps.googleusercontent.com')).toBeNull();
});

it('accepts only a picked file the server can see and that is an allowed kind', async () => {
  const drive = fakePort<GoogleDrivePort>({
    getFile: async (id) => {
      if (id === 'not-via-picker') throw notFound();
      const mime = id === 'pdf' ? 'application/pdf' : 'application/vnd.google-apps.presentation';
      return documentFromDriveFile({ id, name: id, mimeType: mime, trashed: id === 'trashed' });
    },
  });
  const results = await Promise.all(
    ['deck', 'pdf', 'trashed', 'not-via-picker'].map((id) => acceptPickedFile(drive, id, ['slides'])),
  );
  expect(results.map((r) => [r.file_id, r.document?.kind ?? null, r.error?.code ?? null])).toEqual([
    ['deck', 'slides', null],
    ['pdf', null, 'UNSUPPORTED_TEMPLATE'],
    ['trashed', null, 'UNSUPPORTED_TEMPLATE'],
    ['not-via-picker', null, 'EXTERNAL_NOT_FOUND'],
  ]);
});

it('picker contracts reject a non-numeric app id and an empty file id', () => {
  const session = {
    access_token: 't',
    expires_at: '2026-10-09T10:00:00Z',
    developer_key: 'k',
    app_id: '123',
  };
  expect(pickerSession.parse(session)).toEqual(session);
  expect(pickerSession.safeParse({ ...session, app_id: 'my-project' }).success).toBe(false);
  expect(pickedFile.safeParse({ file_id: '' }).success).toBe(false);
});
