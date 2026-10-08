import type { z } from 'zod';

// Google REST 공통 호출. SDK 없이 fetch로 직접 부른다. Zoom은 Zoom 어댑터를 옮길 때 추가한다.
// 오류 본문 원문은 개인정보가 섞일 수 있어 보관하지 않고 분류에 필요한 값만 남긴다.

export type Fetch = typeof fetch;
export type AccessToken = () => Promise<string>;

const RATE_LIMIT_REASONS = new Set(['rateLimitExceeded', 'userRateLimitExceeded']);

export class ExternalApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
    // error.errors[0].reason. Drive는 403 rate limit과 권한 부족을 이것으로 구분한다.
    public readonly reason: string | null,
    // error.status (예: RESOURCE_EXHAUSTED, PERMISSION_DENIED).
    public readonly apiStatus: string | null,
  ) {
    super(message);
    this.name = 'ExternalApiError';
  }
  get rateLimited(): boolean {
    return (
      this.status === 429 ||
      this.apiStatus === 'RESOURCE_EXHAUSTED' ||
      (this.reason !== null && RATE_LIMIT_REASONS.has(this.reason))
    );
  }
}

// 응답 본문이 기대한 모양이 아닐 때. 외부 API 변경이나 fields 마스크 실수를 뜻한다.
export class ExternalResponseError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'ExternalResponseError';
  }
}

export interface ExternalRequest {
  method: 'GET' | 'POST' | 'PATCH' | 'DELETE';
  url: string;
  query?: Record<string, string | number | boolean | undefined>;
  json?: unknown;
  body?: BodyInit;
  headers?: Record<string, string>;
}

export interface HttpOptions {
  fetch?: Fetch;
  timeoutMs?: number;
}

export async function externalRequest(
  accessToken: string,
  request: ExternalRequest,
  options: HttpOptions = {},
): Promise<Response> {
  const url = new URL(request.url);
  for (const [key, value] of Object.entries(request.query ?? {}))
    if (value !== undefined) url.searchParams.set(key, String(value));
  const headers: Record<string, string> = {
    authorization: 'Bearer ' + accessToken,
    ...request.headers,
  };
  let body = request.body;
  if (request.json !== undefined) {
    headers['content-type'] = 'application/json; charset=UTF-8';
    body = JSON.stringify(request.json);
  }
  const init: RequestInit = {
    method: request.method,
    headers,
    signal: AbortSignal.timeout(options.timeoutMs ?? 30_000),
  };
  if (body !== undefined) init.body = body;
  const response = await (options.fetch ?? fetch)(url, init);
  if (!response.ok) throw toError(response.status, await response.text());
  return response;
}

export async function readJson<T>(response: Response, schema: z.ZodType<T>): Promise<T> {
  let data: unknown;
  try {
    data = await response.json();
  } catch {
    throw new ExternalResponseError('JSON이 아닌 응답입니다.');
  }
  const parsed = schema.safeParse(data);
  if (!parsed.success)
    throw new ExternalResponseError(
      '응답 형식이 예상과 다릅니다: ' + parsed.error.issues.map((i) => i.path.join('.')).join(', '),
    );
  return parsed.data;
}

// Google 오류 본문: { error: { message, status, errors: [{ reason }] } }. JSON이 아니어도 status는 남긴다.
function toError(status: number, text: string): ExternalApiError {
  let error: { message?: unknown; status?: unknown; errors?: { reason?: unknown }[] } = {};
  try {
    error = (JSON.parse(text) as { error?: typeof error }).error ?? {};
  } catch {
    // HTML 오류 페이지 등
  }
  const str = (v: unknown) => (typeof v === 'string' && v ? v : null);
  return new ExternalApiError(
    status,
    str(error.message) ?? `Google API 오류 (${status})`,
    str(error.errors?.[0]?.reason),
    str(error.status),
  );
}
