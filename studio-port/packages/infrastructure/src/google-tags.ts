import { z } from 'zod';

// Docs·Slides·Sheets 태그 치환 공통. {{key}} → 값을 batchUpdate 1회(쓰기 쿼터 1)에 담고,
// 응답 replies[]의 occurrencesChanged로 태그별 치환 횟수를 돌려준다. 0이면 템플릿에 그 태그가 없거나 서식이 갈라진 것.
// matchCase=true라 {{Team_name}} 같은 오타 태그는 걸리지 않는다.

export const tag = (key: string) => `{{${key}}}`;

// Docs·Slides replaceAllText. Docs는 tabId를 안 주면 모든 탭에 적용된다.
export function replaceAllTextRequests(variables: Record<string, string>) {
  return Object.entries(variables).map(([key, value]) => ({
    replaceAllText: { containsText: { text: tag(key), matchCase: true }, replaceText: value },
  }));
}

export const batchUpdateReplies = z.object({
  replies: z.array(z.record(z.string(), z.unknown())).default([]),
});

// replies[i][replyKey].occurrencesChanged → {key: 횟수}. replies는 요청과 1:1이고 0이면 필드가 빠진다.
export function tagCounts(
  variables: Record<string, string>,
  replies: Record<string, unknown>[],
  replyKey: 'replaceAllText' | 'findReplace',
): Record<string, number> {
  return Object.fromEntries(
    Object.keys(variables).map((key, i) => {
      const reply = replies[i]?.[replyKey] as { occurrencesChanged?: number } | undefined;
      return [key, reply?.occurrencesChanged ?? 0];
    }),
  );
}
