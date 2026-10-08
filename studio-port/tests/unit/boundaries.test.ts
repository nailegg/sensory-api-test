import { expect, it } from 'vitest';
import { importPaths, violatesBoundary } from '../../scripts/boundary-rules.ts';
it('finds static, side-effect, dynamic, type and re-export dependencies without matching comments', () => {
  expect(
    importPaths(
      'example.ts',
      `
    import 'pg';
    import type { Actor } from '@studio/domain';
    export { x } from './other.ts';
    const dynamic = import('@studio/db');
    const legacy = require('fastify');
    type Hidden = import('@studio/infrastructure').Hidden;
    // import 'ignored';
  `,
    ),
  ).toEqual([
    'pg',
    '@studio/domain',
    './other.ts',
    '@studio/db',
    'fastify',
    '@studio/infrastructure',
  ]);
});
it('restricts internal web dependencies to contracts and ui through aliases and resolved paths', () => {
  const file = 'apps/web/src/example.ts';
  for (const name of ['domain', 'application', 'db', 'infrastructure']) {
    expect(violatesBoundary('web', file, '@studio/' + name)).toBe(true);
    expect(violatesBoundary('web', file, '../../../packages/' + name + '/src/index.ts')).toBe(true);
  }
  for (const name of ['contracts', 'ui'])
    expect(violatesBoundary('web', file, '../../../packages/' + name + '/src/index.ts')).toBe(
      false,
    );
  expect(violatesBoundary('web', file, './ui.tsx')).toBe(false);
});
it('keeps domain and application independent of SDK implementations and upper layers', () => {
  for (const layer of ['domain', 'application'] as const)
    for (const specifier of [
      'fastify',
      '@supabase/supabase-js',
      '@studio/infrastructure',
      '@studio/db',
      '../../infrastructure/src/auth.ts',
      '../../../apps/api/src/app.ts',
    ])
      expect(violatesBoundary(layer, 'packages/' + layer + '/src/example.ts', specifier)).toBe(
        true,
      );
  expect(
    violatesBoundary(
      'application',
      'packages/application/src/example.ts',
      '../../domain/src/index.ts',
    ),
  ).toBe(false);
});
