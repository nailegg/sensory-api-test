import { readdir, readFile } from 'node:fs/promises';
export async function files(path: string): Promise<string[]> {
  const entries = await readdir(path, { withFileTypes: true });
  const lists = await Promise.all(
    entries
      .filter((e) => !['node_modules', 'dist', '.git'].includes(e.name))
      .map((e) => (e.isDirectory() ? files(path + '/' + e.name) : [path + '/' + e.name])),
  );
  return lists.flat();
}
export { readFile };
