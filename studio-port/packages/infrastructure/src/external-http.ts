import type { z } from 'zod';
import { AppError } from '../../domain/src/index.ts';

// Google·Zoom REST 공통 호출. SDK 없이 fetch로 직접 부른다.

export type ExternalProvider = 'google' | 'zoom';
export type Fetch = typeof fetch;
export type AccessToken = () => Promise<string>;

const RATE_LIMIT_REASONS = new Set(['rateLimitExceeded', 'userRateLimitExceeded']);

const MESSAGES: Record<
  ExternalProvider,
  { rateLimited: string; notFound: string; failed: string }
> = {
  google: {
    rateLimited: 'Google 요청 한도를 넘었습니다. 잠시 후 다시 시도하세요.',
    notFound: 'Google에서 파일을 찾을 수 없거나 앱에 접근 권한이 없습니다.',
    failed: 'Google 요청이 실패했습니다.',
  },
  zoom: {
    rateLimited: 'Zoom 요청 한도를 넘었습니다. 잠시 후 다시 시도하세요.',
    notFound: 'Zoom에서 미팅을 찾을 수 없습니다.',
    failed: 'Zoom 요청이 실패했습니다.',
  },
};

// 외부 오류를 studio AppError로 낸다. application은 infrastructure를 import할 수 없으므로
// AppError로 "외부 호출 실패"를 알아보고, 그 밖의 예외는 버그로 보고 올린다.
// 코드 이름은 docs/STUDIO_PORTING.md 5절 제안(결정 필요 C).
export class ExternalApiError extends AppError {
  constructor(
    public readonly provider: ExternalProvider,
    public readonly externalStatus: number,
    // Google error.errors[0].reason. Drive는 403 rate limit과 권한 부족을 이것으로 구분한다.
    public readonly reason: string | null,
    // Google error.status (예: RESOURCE_EXHAUSTED, PERMISSION_DENIED).
    public readonly apiStatus: string | null,
    // 원문 메시지. 원인 추적용이다. 파일 ID·이메일이 섞일 수 있어 details(API 응답에 나감)에
    // 넣지 않는다. 로그에 남길지·가릴지는 studio 로깅 정책을 따른다(STUDIO_PORTING.md 결정 필요 M).
    public readonly externalMessage: string | null,
    // Zoom 본문 code (124 토큰 무효, 3001 미팅 없음, 200 유료 전용).
    public readonly zoomCode: number | null = null,
  ) {
    const rateLimited =
      externalStatus === 429 ||
      apiStatus === 'RESOURCE_EXHAUSTED' ||
      (reason !== null && RATE_LIMIT_REASONS.has(reason));
    const text = MESSAGES[provider];
    const [code, status, message] = rateLimited
      ? ['EXTERNAL_RATE_LIMITED', 429, text.rateLimited]
      : externalStatus === 404
        ? ['EXTERNAL_NOT_FOUND', 404, text.notFound]
        : ['EXTERNAL_FAILED', 502, text.failed];
    super(code, status, message, {
      status: externalStatus,
      reason,
      api_status: apiStatus,
      zoom_code: zoomCode,
    });
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
  method: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE';
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
  provider: ExternalProvider,
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
  if (!response.ok) throw externalError(provider, response.status, await response.text());
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

// Google 오류 본문: { error: { message, status, errors: [{ reason }] } }
// Zoom 오류 본문: { code, message }
// JSON이 아니어도(HTML 오류 페이지 등) status는 남긴다.
export function externalError(
  provider: ExternalProvider,
  status: number,
  text: string,
): ExternalApiError {
  let body: Record<string, unknown> = {};
  try {
    body = (JSON.parse(text) as Record<string, unknown> | null) ?? {};
  } catch {
    // JSON이 아님
  }
  const str = (v: unknown) => (typeof v === 'string' && v ? v : null);
  if (provider === 'zoom')
    return new ExternalApiError(
      provider,
      status,
      null,
      null,
      str(body['message']),
      typeof body['code'] === 'number' ? body['code'] : null,
    );
  const error = (body['error'] ?? {}) as {
    message?: unknown;
    status?: unknown;
    errors?: { reason?: unknown }[];
  };
  return new ExternalApiError(
    provider,
    status,
    str(error.errors?.[0]?.reason),
    str(error.status),
    str(error.message),
  );
}
