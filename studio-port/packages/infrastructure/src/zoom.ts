import { createHmac, timingSafeEqual } from 'node:crypto';
import { z } from 'zod';
import type { Meeting } from '../../domain/src/index.ts';
import type { MeetingSchedule, ZoomPort } from '../../application/src/index.ts';
import {
  externalRequest,
  readJson,
  type AccessToken,
  type ExternalRequest,
  type HttpOptions,
} from './external-http.ts';

// Zoom v2 어댑터 + 웹훅 검증. synsory-api app/services/zoom/client.py + mapper.py
// + usecases의 요청 본문·웹훅 함수 이식본. 함정은 synsory-api docs/zoom.md 10절.

const BASE_URL = 'https://api.zoom.us/v2';
const SCHEDULED = 2;
const RECURRING_FIXED = 8;

export const zoomMeeting = z.object({
  // int64라 JSON 숫자로 온다. 10자리를 넘을 수 있어 문자열로 바꾼다.
  id: z.union([z.number(), z.string()]),
  uuid: z.string().optional(),
  host_id: z.string().optional(),
  topic: z.string().optional(),
  status: z.string().optional(),
  start_time: z.string().optional(),
  duration: z.number().optional(),
  timezone: z.string().optional(),
  join_url: z.string().optional(),
  start_url: z.string().optional(),
  occurrences: z
    .array(
      z.object({
        occurrence_id: z.union([z.number(), z.string()]),
        start_time: z.string().optional(),
        duration: z.number().optional(),
        status: z.string().optional(),
      }),
    )
    .optional(),
});
export type ZoomMeeting = z.infer<typeof zoomMeeting>;

// Zoom status에는 ended가 없다. 종료는 웹훅으로만 안다.
export function meetingFromZoom(m: ZoomMeeting): Meeting {
  return {
    id: String(m.id),
    provider: 'zoom',
    topic: m.topic ?? '',
    status: m.status === 'waiting' ? 'scheduled' : m.status === 'started' ? 'started' : 'unknown',
    start_time: m.start_time ?? null,
    duration_minutes: m.duration ?? null,
    timezone: m.timezone ?? null,
    join_url: m.join_url ?? null,
    host_id: m.host_id ?? null,
    uuid: m.uuid ?? null,
    occurrences: (m.occurrences ?? []).map((o) => ({
      id: String(o.occurrence_id),
      start_time: o.start_time ?? null,
      duration_minutes: o.duration ?? null,
      deleted: o.status === 'deleted',
    })),
  };
}

// Zoom은 UTC "yyyy-MM-ddTHH:mm:ssZ"를 받는다(밀리초 없음).
export function zoomTime(date: Date): string {
  return date.toISOString().replace(/\.\d{3}Z$/, 'Z');
}

export function meetingBody(schedule: MeetingSchedule): Record<string, unknown> {
  return {
    topic: schedule.topic,
    type: SCHEDULED,
    start_time: zoomTime(schedule.startTime),
    duration: schedule.durationMinutes,
    timezone: schedule.timezone,
    ...(schedule.settings && { settings: schedule.settings }),
  };
}

export function createZoom(accessToken: AccessToken, options: HttpOptions = {}): ZoomPort {
  const call = async (request: ExternalRequest) =>
    externalRequest('zoom', await accessToken(), request, options);
  const create = async (body: Record<string, unknown>) =>
    meetingFromZoom(
      await readJson(
        await call({ method: 'POST', url: `${BASE_URL}/users/me/meetings`, json: body }),
        zoomMeeting,
      ),
    );
  const get = async (meetingId: string) =>
    readJson(await call({ method: 'GET', url: `${BASE_URL}/meetings/${meetingId}` }), zoomMeeting);
  return {
    // GET /users/me (LIGHT)
    async getMe() {
      const me = await readJson(
        await call({ method: 'GET', url: `${BASE_URL}/users/me` }),
        z.object({ type: z.number(), timezone: z.string().optional() }),
      );
      return { plan_type: me.type, timezone: me.timezone ?? null };
    },

    // POST /users/me/meetings (LIGHT, 하루 100회). 응답 201.
    createMeeting: (schedule) => create(meetingBody(schedule)),

    createBreakoutMeeting(schedule, rooms) {
      const breakout = {
        enable: true,
        rooms: Object.entries(rooms).map(([name, participants]) => ({ name, participants })),
      };
      return create(
        meetingBody({ ...schedule, settings: { ...schedule.settings, breakout_room: breakout } }),
      );
    },

    createRecurringMeeting(schedule, recurrence) {
      return create({
        ...meetingBody(schedule),
        type: RECURRING_FIXED,
        recurrence: {
          type: 2, // 매주
          repeat_interval: 1,
          weekly_days: recurrence.weeklyDays.join(','),
          ...('endDateTime' in recurrence
            ? { end_date_time: zoomTime(recurrence.endDateTime) }
            : { end_times: recurrence.endTimes }),
        },
      });
    },

    // GET /meetings/{id} (LIGHT). status는 waiting/started뿐이다.
    getMeeting: async (meetingId) => meetingFromZoom(await get(meetingId)),

    // PATCH /meetings/{id} (LIGHT, 하루 100회에 포함). 204.
    async updateMeeting(meetingId, changes, occurrenceId) {
      await call({
        method: 'PATCH',
        url: `${BASE_URL}/meetings/${meetingId}`,
        query: { occurrence_id: occurrenceId },
        json: {
          ...(changes.startTime && { start_time: zoomTime(changes.startTime) }),
          ...(changes.durationMinutes !== undefined && { duration: changes.durationMinutes }),
          ...(changes.topic !== undefined && { topic: changes.topic }),
        },
      });
    },

    // DELETE /meetings/{id} (LIGHT). 204.
    async deleteMeeting(meetingId, occurrenceId) {
      await call({
        method: 'DELETE',
        url: `${BASE_URL}/meetings/${meetingId}`,
        query: { occurrence_id: occurrenceId ?? undefined },
      });
    },

    async getStartUrl(meetingId) {
      const url = (await get(meetingId)).start_url;
      if (!url) throw new Error('Zoom 응답에 start_url이 없습니다.');
      return url;
    },
  };
}

// ---------- 웹훅 (유즈케이스 6) ----------

const hmacHex = (secret: string, message: string | Uint8Array) =>
  createHmac('sha256', secret).update(message).digest('hex');

// endpoint.url_validation 요청에 돌려줄 본문. 3초 안에 200으로 응답해야 한다.
export function urlValidationResponse(secretToken: string, plainToken: string) {
  return { plainToken, encryptedToken: hmacHex(secretToken, plainToken) };
}

// x-zm-signature 검증. 서명 대상은 JSON을 다시 직렬화한 것이 아니라 받은 그대로의 본문이다.
// Fastify는 기본으로 JSON을 파싱하므로 이 라우트만 원본 바이트를 받게 설정한다.
export function verifySignature(
  secretToken: string,
  timestamp: string,
  rawBody: Uint8Array,
  signature: string,
): boolean {
  const message = Buffer.concat([Buffer.from(`v0:${timestamp}:`), rawBody]);
  const expected = Buffer.from('v0=' + hmacHex(secretToken, message));
  const given = Buffer.from(signature);
  return expected.length === given.length && timingSafeEqual(expected, given);
}
