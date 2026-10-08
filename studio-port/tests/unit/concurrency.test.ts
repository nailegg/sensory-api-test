import { expect, it } from 'vitest';
import { mapConcurrently } from '../../packages/application/src/index.ts';

it('keeps input order and never runs more than the limit at once', async () => {
  let running = 0;
  let peak = 0;
  const out = await mapConcurrently(
    [30, 5, 20, 1, 10, 2],
    async (ms) => {
      running += 1;
      peak = Math.max(peak, running);
      await new Promise((r) => setTimeout(r, ms));
      running -= 1;
      return ms * 2;
    },
    3,
  );
  expect(out).toEqual([60, 10, 40, 2, 20, 4]);
  expect(peak).toBe(3);
});

it('handles an empty list and propagates errors', async () => {
  expect(await mapConcurrently([], async () => 1)).toEqual([]);
  await expect(
    mapConcurrently([1, 2], async (n) => {
      if (n === 2) throw new TypeError('bug');
      return n;
    }),
  ).rejects.toThrow(TypeError);
});
