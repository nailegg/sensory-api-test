import type { Fetch } from '../../packages/infrastructure/src/index.ts';

export interface RecordedRequest {
  method: string;
  url: URL;
  headers: Record<string, string>;
  body: string | null;
  json: unknown;
}

type Reply = { status?: number; json?: unknown; text?: string; bytes?: Uint8Array<ArrayBuffer> };

// 외부 HTTP 대신 쓰는 fetch. 보낸 요청을 기록하고 정해 둔 응답을 차례로 돌려준다.
export function recordingFetch(...replies: Reply[]) {
  const requests: RecordedRequest[] = [];
  const fetchImpl: Fetch = async (input, init) => {
    const headers = Object.fromEntries(new Headers(init?.headers).entries());
    const raw = init?.body;
    const body =
      raw === undefined || raw === null
        ? null
        : typeof raw === 'string'
          ? raw
          : new TextDecoder().decode(raw as Uint8Array);
    let json: unknown = null;
    if (body && headers['content-type']?.startsWith('application/json')) json = JSON.parse(body);
    requests.push({
      method: init?.method ?? 'GET',
      url: new URL(String(input)),
      headers,
      body,
      json,
    });
    const reply = replies.shift() ?? { json: {} };
    const status = reply.status ?? 200;
    const payload =
      reply.bytes ?? reply.text ?? (reply.json === undefined ? '' : JSON.stringify(reply.json));
    return new Response(status === 204 ? null : payload, { status });
  };
  return { fetch: fetchImpl, requests };
}

export const token = async () => 'test-token';
