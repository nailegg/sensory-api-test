import { files, readFile } from './files.ts';
import { importPaths, violatesBoundary, type BoundaryLayer } from './boundary-rules.ts';
const failures: string[] = [];
const roots: [string, BoundaryLayer][] = [
  ['packages/domain', 'domain'],
  ['packages/application', 'application'],
];
for (const [root, layer] of roots)
  for (const file of await files(root)) {
    if (!/\.[jt]sx?$/.test(file)) continue;
    const source = await readFile(file, 'utf8');
    for (const path of importPaths(file, source))
      if (violatesBoundary(layer, file, path)) failures.push(file + ': ' + path);
  }
if (failures.length) throw new Error(failures.join('\n'));
console.log('패키지 의존 경계 검사 통과');
