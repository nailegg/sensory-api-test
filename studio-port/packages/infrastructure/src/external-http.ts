import type { z } from 'zod';
import { AppError } from '../../domain/src/index.ts';

// Google REST 공통 호출. SDK 없이 fetch로 직접 부른다. Zoom은 Zoom 어댑터를 옮길 때 추가한다.
// 오류 본문 원문은 개인정보가 섞일 수 있어 보관하지 않고 분류에 필요한 값만 남긴다.

export type Fetch = typeof fetch;
export type AccessToken = () => Promise<string>;

const RATE_LIMIT_REASONS = new Set(['rateLimitExceeded', 'userRateLimitExceeded']);

// Google 오류를 studio AppError로 낸다. application은 infrastructure를 import할 수 없으므로
// AppError로 "외부 호출 실패"를 알아보고, 그 밖의 예외는 버그로 보고 올린다.
// 코드 이름은 docs/STUDIO_PORTING.md 5절 제안(결정 필요 C).
export class ExternalApiError extends AppError {
  constructor(
    public readonly externalStatus: number,
    // error.errors[0].reason. Drive는 403 rate limit과 권한 부족을 이것으로 구분한다.
    public readonly reason: string | null,
    // error.status (예: RESOURCE_EXHAUSTED, PERMISSION_DENIED).
    public readonly apiStatus: string | null,
    // Google 원문 메시지. 원인 추적용이다. 파일 ID·이메일이 섞일 수 있어 details(API 응답에 나감)에
    // 넣지 않는다. 로그에 남길지·가릴지는 studio 로깅 정책을 따른다(STUDIO_PORTING.md 결정 필요 M).
    public readonly externalMessage: string | null,
  ) {
    const rateLimited =
      externalStatus === 429 ||
      apiStatus === 'RESOURCE_EXHAUSTED' ||
      (reason !== null && RATE_LIMIT_REASONS.has(reason));
    const [code, status, message] = rateLimited
      ? ['EXTERNAL_RATE_LIMITED', 429, 'Google 요청 한도를 넘었습니다. 잠시 후 다시 시도하세요.']
      : externalStatus === 404
        ? ['EXTERNAL_NOT_FOUND', 404, 'Google에서 파일을 찾을 수 없거나 앱에 접근 권한이 없습니다.']
        : ['EXTERNAL_FAILED', 502, 'Google 요청이 실패했습니다.'];
    super(code, status, message, { status: externalStatus, reason, api_status: apiStatus });
    this.name = 'ExternalApiError';
  }
  get rateLimited(): boolean {
    return this.code === 'EXTERNAL_RATE_LIMITED';
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
    str(error.errors?.[0]?.reason),
    str(error.status),
    str(error.message),
  );
}
