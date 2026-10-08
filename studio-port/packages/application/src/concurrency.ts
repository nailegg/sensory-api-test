// 서로 다른 파일·미팅을 만드는 작업(그룹마다, 파일마다)을 동시에 몇 개씩 처리한다.
// 실측(2026-10-09, 6개 조): 순차 대비 동시 3개 약 3배, 6개 약 6배 빨랐고 한도 오류는 없었다.
// 같은 파일의 권한 변경은 동시에 하면 안 된다(Drive: 마지막 쓰기만 남음) → 배치나 순차로 한다.
export const CONCURRENCY = 4;

// items 순서대로 결과를 돌려준다. 한 작업의 예외는 그대로 올라간다(호출부가 외부 실패를 결과로 담는다).
export async function mapConcurrently<T, R>(
  items: readonly T[],
  work: (item: T) => Promise<R>,
  limit = CONCURRENCY,
): Promise<R[]> {
  const results = new Array<R>(items.length);
  let next = 0;
  const worker = async () => {
    while (next < items.length) {
      const i = next++;
      results[i] = await work(items[i] as T);
    }
  };
  await Promise.all(Array.from({ length: Math.min(limit, items.length) }, worker));
  return results;
}
