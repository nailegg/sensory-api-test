import { describe, expect, it } from 'vitest';
import type { DrivePermission, GoogleDrivePort } from '../../packages/application/src/index.ts';
import {
  closeSubmissions,
  createGroupFilesFromTemplate,
  downgradeEditors,
  restoreEditors,
} from '../../packages/application/src/google-files.ts';
import { AppError, renderTemplate } from '../../packages/domain/src/index.ts';
import { documentFromDriveFile } from '../../packages/infrastructure/src/index.ts';
import { fakePort, notFound } from '../fixtures/fake-port.ts';

const doc = (id: string, name: string) =>
  documentFromDriveFile({ id, name, mimeType: 'application/vnd.google-apps.spreadsheet' });
const perm = (id: string, role: string, email: string): DrivePermission => ({
  id,
  type: 'user',
  role,
  email,
  display_name: null,
  view: null,
});

it('renderTemplate replaces known tags and keeps unknown ones (test_render_template…)', () => {
  expect(
    renderTemplate('# {{activity_name}}\n팀 {{ team_name }} / {{unknown}} / {x}', {
      activity_name: '과제1',
      team_name: 'A조',
    }),
  ).toBe('# 과제1\n팀 A조 / {{unknown}} / {x}');
});

describe('createGroupFilesFromTemplate (google_drive test_usecases.py)', () => {
  function drive(invisibleTemplate?: string, failEmail?: string) {
    const copied: { source: string; name: string; parent: string | undefined }[] = [];
    const shared: [string, string, string][] = [];
    const port = fakePort<GoogleDrivePort>({
      async copyFile(fileId, name, parent) {
        if (fileId === invisibleTemplate) throw notFound();
        copied.push({ source: fileId, name, parent });
        return doc(`copy-${copied.length}`, name);
      },
      async shareWithUser(fileId, email, role) {
        if (email === failEmail) throw new AppError('EXTERNAL_FAILED', 502, '공유하지 못했습니다.');
        shared.push([fileId, email, role]);
        return perm(`perm-${email}`, role, email);
      },
    });
    return { port, copied, shared };
  }

  it('copies, replaces with the copy id and variables, then shares', async () => {
    const d = drive();
    const calls: [string, Record<string, string>][] = [];
    const results = await createGroupFilesFromTemplate(d.port, {
      folderId: 'folder-1',
      activityName: '과제1',
      titleTemplate: '{{activity_name}} - {{team_name}}',
      templateFileId: 'tpl',
      groups: [
        { team_name: 'A조', member_emails: ['a@example.com'] },
        { team_name: 'B조', member_emails: [] },
      ],
      replaceTags: async (fileId, variables) => {
        calls.push([fileId, variables]);
        return { team_name: 2, due: 0 };
      },
      due: '2026-10-10',
    });
    expect(d.copied).toEqual([
      { source: 'tpl', name: '과제1 - A조', parent: 'folder-1' },
      { source: 'tpl', name: '과제1 - B조', parent: 'folder-1' },
    ]);
    expect(calls).toEqual([
      ['copy-1', { team_name: 'A조', activity_name: '과제1', due: '2026-10-10' }],
      ['copy-2', { team_name: 'B조', activity_name: '과제1', due: '2026-10-10' }],
    ]);
    const [a, b] = results;
    expect(a?.document?.id).toBe('copy-1');
    expect(a?.replaced).toEqual({ team_name: 2, due: 0 });
    expect(a?.shares.map((s) => [s.email, s.error])).toEqual([['a@example.com', null]]);
    expect([b?.shares, b?.error]).toEqual([[], null]);
  });

  it('records 404 per group when the template is not visible to the app and does not copy', async () => {
    const d = drive('picked-but-not-via-picker');
    const results = await createGroupFilesFromTemplate(d.port, {
      folderId: 'folder-1',
      activityName: '과제1',
      titleTemplate: '{{team_name}}',
      templateFileId: 'picked-but-not-via-picker',
      groups: [{ team_name: 'A조', member_emails: ['a@example.com'] }],
      replaceTags: () => {
        throw new Error('복사가 안 됐으면 치환을 부르지 않는다');
      },
    });
    expect(results[0]?.document).toBeNull();
    expect(results[0]?.error?.code).toBe('EXTERNAL_NOT_FOUND');
    expect([d.copied, d.shared]).toEqual([[], []]);
  });

  it('keeps the copy and skips sharing when replacement fails; bugs propagate', async () => {
    const d = drive();
    const results = await createGroupFilesFromTemplate(d.port, {
      folderId: 'f',
      activityName: '과제1',
      titleTemplate: '{{team_name}}',
      templateFileId: 'tpl',
      groups: [
        { team_name: 'A조', member_emails: ['a@example.com'] },
        { team_name: 'B조', member_emails: ['b@example.com'] },
      ],
      replaceTags: async (fileId) => {
        if (fileId === 'copy-1') throw new AppError('EXTERNAL_FAILED', 502, 'bad tag');
        return { team_name: 1 };
      },
    });
    const [a, b] = results;
    expect([a?.document?.id, a?.error?.message, a?.shares]).toEqual(['copy-1', 'bad tag', []]);
    expect(b?.error).toBeNull();
    expect(d.shared).toEqual([['copy-2', 'b@example.com', 'writer']]);

    await expect(
      createGroupFilesFromTemplate(drive().port, {
        folderId: 'f',
        activityName: 'x',
        titleTemplate: '{{team_name}}',
        templateFileId: 'tpl',
        groups: [{ team_name: 'A조', member_emails: [] }],
        replaceTags: () => Promise.reject(new TypeError('bug')),
      }),
    ).rejects.toThrow(TypeError);
  });

  it('continues sharing after one member fails (test_create_group_documents…partial_share_failure)', async () => {
    const d = drive(undefined, 'bad@example.com');
    const [a] = await createGroupFilesFromTemplate(d.port, {
      folderId: 'f',
      activityName: '과제1',
      titleTemplate: '{{team_name}}',
      templateFileId: 'tpl',
      groups: [{ team_name: 'A조', member_emails: ['a1@example.com', 'bad@example.com'] }],
      replaceTags: async () => ({}),
    });
    expect(a?.shares.map((s) => [s.email, s.error?.code ?? null])).toEqual([
      ['a1@example.com', null],
      ['bad@example.com', 'EXTERNAL_FAILED'],
    ]);
  });
});

describe('closing and restoring edit access (google_docs test_usecases.py)', () => {
  function drive() {
    const updated: [string, string][] = [];
    const port = fakePort<GoogleDrivePort>({
      async listPermissions(fileId) {
        if (fileId === 'missing') throw notFound();
        return [
          perm('p-owner', 'owner', 'prof@example.com'),
          perm('p-ta', 'writer', 'TA@example.com'),
          perm('p-s1', 'writer', 's1@example.com'),
          perm('p-s2', 'commenter', 's2@example.com'),
        ];
      },
      async updatePermissionRole(_fileId, permissionId, role) {
        updated.push([permissionId, role]);
        return perm(permissionId, role, '');
      },
    });
    return { port, updated };
  }

  it('downgrades writers except the owner and keep emails, case-insensitively', async () => {
    const d = drive();
    const changed = await downgradeEditors(d.port, 'doc', { keepEmails: ['ta@example.com'] });
    expect(d.updated).toEqual([['p-s1', 'commenter']]);
    expect(changed.map((p) => [p.id, p.role])).toEqual([['p-s1', 'commenter']]);
  });

  it('restores only listed non-writers', async () => {
    const d = drive();
    await restoreEditors(d.port, 'doc', ['s2@example.com', 's1@example.com']);
    expect(d.updated).toEqual([['p-s2', 'writer']]);
  });

  it('continues closing after a file fails', async () => {
    const d = drive();
    const results = await closeSubmissions(d.port, ['doc-1', 'missing', 'doc-2'], {
      keepEmails: ['ta@example.com'],
    });
    expect(results.map((r) => r.file_id)).toEqual(['doc-1', 'missing', 'doc-2']);
    expect(results[0]?.downgraded.map((p) => p.id)).toEqual(['p-s1']);
    expect([results[1]?.error?.code, results[1]?.downgraded]).toEqual(['EXTERNAL_NOT_FOUND', []]);
    expect(results[2]?.error).toBeNull();
  });
});
