import { createHmac } from 'node:crypto';
import { describe, expect, it } from 'vitest';
import {
  createGroupMeetings,
  rescheduleMeeting,
  type ZoomPort,
} from '../../packages/application/src/index.ts';
import {
  AppError,
  hasFortyMinuteLimit,
  summarizeAttendance,
  type ZoomEvent,
} from '../../packages/domain/src/index.ts';
import {
  createZoom,
  ExternalApiError,
  meetingFromZoom,
  urlValidationResponse,
  verifySignature,
} from '../../packages/infrastructure/src/index.ts';
import { fakePort } from '../fixtures/fake-port.ts';
import { recordingFetch, token } from '../fixtures/http.ts';

// ---------- 응답 해석 (synsory-api tests/zoom/test_mapper.py) ----------

const SCHEDULED = {
  id: 81234567890,
  uuid: 'abc/def==',
  host_id: 'h1',
  topic: '과제1 - A조',
  type: 2,
  status: 'waiting',
  start_time: '2026-10-10T05:00:00Z',
  duration: 40,
  timezone: 'Asia/Seoul',
  join_url: 'https://zoom.us/j/81234567890',
  start_url: 'https://zoom.us/s/secret',
};

describe('meetingFromZoom', () => {
  it('maps a scheduled meeting and leaves out start_url', () => {
    const m = meetingFromZoom(SCHEDULED);
    expect(m).toMatchObject({
      id: '81234567890', // int64 → 문자열
      status: 'scheduled',
      start_time: '2026-10-10T05:00:00Z',
      duration_minutes: 40,
      timezone: 'Asia/Seoul',
      uuid: 'abc/def==',
    });
    expect(JSON.stringify(m)).not.toContain('zoom.us/s/'); // 호스트 권한 링크는 넣지 않는다
  });

  it('maps occurrences and unknown status', () => {
    const m = meetingFromZoom({
      id: 1,
      topic: '수업',
      status: 'ended?',
      occurrences: [
        {
          occurrence_id: 1791000000000,
          start_time: '2026-10-12T05:00:00Z',
          duration: 40,
          status: 'available',
        },
        {
          occurrence_id: 1791600000000,
          start_time: '2026-10-19T05:00:00Z',
          duration: 40,
          status: 'deleted',
        },
      ],
    });
    expect(m.status).toBe('unknown');
    expect(m.occurrences.map((o) => [o.id, o.deleted])).toEqual([
      ['1791000000000', false],
      ['1791600000000', true],
    ]);
  });
});

// ---------- 웹훅 ----------

const SECRET = 'test-secret';
const hmac = (message: string) => createHmac('sha256', SECRET).update(message).digest('hex');

it('url validation response is the HMAC of the plain token', () => {
  expect(urlValidationResponse(SECRET, 'abc')).toEqual({
    plainToken: 'abc',
    encryptedToken: hmac('abc'),
  });
});

it('verifies x-zm-signature over the raw body', () => {
  const body = '{"event":"meeting.participant_joined","payload":{}}';
  const bytes = new TextEncoder().encode(body);
  const sig = 'v0=' + hmac(`v0:1700000000:${body}`);
  expect(verifySignature(SECRET, '1700000000', bytes, sig)).toBe(true);
  expect(verifySignature(SECRET, '1700000001', bytes, sig)).toBe(false); // 타임스탬프가 다르면 실패
  expect(verifySignature(SECRET, '1700000000', new TextEncoder().encode(body + ' '), sig)).toBe(
    false,
  ); // 본문 1바이트
  expect(verifySignature('other', '1700000000', bytes, sig)).toBe(false);
  expect(verifySignature(SECRET, '1700000000', bytes, 'v0=short')).toBe(false); // 길이가 달라도 예외 없이 실패
});

// ---------- 유즈케이스 1~5 (synsory-api tests/zoom/test_usecases.py) ----------

// 2026-10-10 14:00 KST = 05:00 UTC
const KST_14 = new Date('2026-10-10T14:00:00+09:00');

it('host profile: Basic plan has the 40-minute limit', async () => {
  const http = recordingFetch({ json: { type: 1, timezone: 'Asia/Seoul' } });
  const me = await createZoom(token, http).getMe();
  expect(me).toEqual({ plan_type: 1, timezone: 'Asia/Seoul' });
  expect(http.requests[0]?.url.pathname).toBe('/v2/users/me');
  expect(hasFortyMinuteLimit(me.plan_type)).toBe(true);
  expect(hasFortyMinuteLimit(2)).toBe(false);
});

it('group meetings render the topic, send UTC time and continue after a failure', async () => {
  const created: Record<string, unknown>[] = [];
  const zoom = fakePort<ZoomPort>({
    async createMeeting(schedule) {
      if (schedule.topic === '과제1 - B조')
        throw new AppError('EXTERNAL_RATE_LIMITED', 429, 'daily limit');
      created.push({ ...schedule });
      return meetingFromZoom({ id: created.length, topic: schedule.topic, status: 'waiting' });
    },
  });
  const results = await createGroupMeetings(zoom, {
    teamNames: ['A조', 'B조', 'C조'],
    topicTemplate: '{{activity_name}} - {{team_name}}',
    activityName: '과제1',
    startTime: KST_14,
    durationMinutes: 40,
    timezone: 'Asia/Seoul',
  });
  expect(
    results.map((r) => [r.team_name, r.meeting?.topic ?? null, r.error?.code ?? null]),
  ).toEqual([
    ['A조', '과제1 - A조', null],
    ['B조', null, 'EXTERNAL_RATE_LIMITED'],
    ['C조', '과제1 - C조', null],
  ]);

  const http = recordingFetch({ json: { id: 1 } });
  await createZoom(token, http).createMeeting({
    topic: '과제1 - A조',
    startTime: KST_14,
    durationMinutes: 40,
    timezone: 'Asia/Seoul',
  });
  expect(http.requests[0]?.url.pathname).toBe('/v2/users/me/meetings');
  expect(http.requests[0]?.json).toEqual({
    topic: '과제1 - A조',
    type: 2,
    start_time: '2026-10-10T05:00:00Z',
    duration: 40,
    timezone: 'Asia/Seoul',
  });
});

it('breakout meeting keeps given settings and adds pre-assigned rooms', async () => {
  const http = recordingFetch({ json: { id: 1 } });
  await createZoom(token, http).createBreakoutMeeting(
    {
      topic: '과제1',
      startTime: KST_14,
      durationMinutes: 40,
      timezone: 'Asia/Seoul',
      settings: { waiting_room: true },
    },
    { A조: ['a@x.com'] },
  );
  expect((http.requests[0]?.json as { settings: unknown }).settings).toEqual({
    waiting_room: true,
    breakout_room: { enable: true, rooms: [{ name: 'A조', participants: ['a@x.com'] }] },
  });
});

it('recurring meeting is type 8 with a weekly recurrence', async () => {
  const http = recordingFetch({ json: { id: 1 } }, { json: { id: 2 } });
  const zoom = createZoom(token, http);
  const schedule = {
    topic: '수업',
    startTime: new Date('2026-10-12T14:00:00+09:00'),
    durationMinutes: 40,
    timezone: 'Asia/Seoul',
  };
  await zoom.createRecurringMeeting(schedule, { weeklyDays: [2, 4], endTimes: 8 });
  await zoom.createRecurringMeeting(schedule, {
    weeklyDays: [2],
    endDateTime: new Date('2026-12-15T00:00:00Z'),
  });
  const bodies = http.requests.map((r) => r.json as { type: number; recurrence: unknown });
  expect(bodies[0]?.type).toBe(8);
  expect(bodies[0]?.recurrence).toEqual({
    type: 2,
    repeat_interval: 1,
    weekly_days: '2,4',
    end_times: 8,
  });
  expect(bodies[1]?.recurrence).toEqual({
    type: 2,
    repeat_interval: 1,
    weekly_days: '2',
    end_date_time: '2026-12-15T00:00:00Z',
  });
});

it('reschedule sends only the given fields for an occurrence, then reads back', async () => {
  const http = recordingFetch(
    { status: 204 },
    { json: { id: 9, topic: '바뀐 주제', status: 'waiting' } },
  );
  const zoom = createZoom(token, http);
  const m = await rescheduleMeeting(zoom, '9', { durationMinutes: 30 }, 'o1');
  expect(http.requests[0]?.method).toBe('PATCH');
  expect(http.requests[0]?.url.searchParams.get('occurrence_id')).toBe('o1');
  expect(http.requests[0]?.json).toEqual({ duration: 30 });
  expect(http.requests[1]?.method).toBe('GET');
  expect(m.topic).toBe('바뀐 주제');
  await expect(rescheduleMeeting(zoom, '9', {})).rejects.toMatchObject({ code: 'NO_CHANGES' });
});

it('cancel without occurrence deletes the series; start url is read fresh', async () => {
  const http = recordingFetch({ status: 204 }, { json: { ...SCHEDULED, id: 9 } });
  const zoom = createZoom(token, http);
  await zoom.deleteMeeting('9', null);
  expect(http.requests[0]?.method).toBe('DELETE');
  expect(http.requests[0]?.url.searchParams.has('occurrence_id')).toBe(false);
  expect(await zoom.getStartUrl('9')).toBe('https://zoom.us/s/secret');
});

it('parses Zoom error bodies ({ code, message })', async () => {
  const failing = async (reply: Parameters<typeof recordingFetch>[0]) =>
    createZoom(token, recordingFetch(reply))
      .getMeeting('9')
      .catch((e: unknown) => e);
  const missing = await failing({
    status: 404,
    json: { code: 3001, message: 'Meeting does not exist: 9.' },
  });
  expect(missing).toBeInstanceOf(ExternalApiError);
  expect(missing).toMatchObject({
    code: 'EXTERNAL_NOT_FOUND',
    provider: 'zoom',
    zoomCode: 3001,
    externalMessage: 'Meeting does not exist: 9.',
    message: 'Zoom에서 미팅을 찾을 수 없습니다.',
  });
  expect(await failing({ status: 429, json: { code: 429, message: 'limit' } })).toMatchObject({
    code: 'EXTERNAL_RATE_LIMITED',
  });
  expect(await failing({ status: 400, json: { code: 200, message: 'paid only' } })).toMatchObject({
    code: 'EXTERNAL_FAILED',
    zoomCode: 200,
  });
});

// ---------- 유즈케이스 6: 출석 집계 ----------

const START = '2026-10-12T05:00:00Z';

function ev(
  event: string,
  o: {
    uuid?: string;
    meetingId?: number;
    name?: string;
    puid?: string;
    join?: string;
    leave?: string;
    end?: string;
  },
): ZoomEvent {
  return {
    event,
    payload: {
      object: {
        id: o.meetingId ?? 111,
        uuid: o.uuid ?? 'u1',
        ...(o.end && { end_time: o.end }),
        ...(o.name !== undefined && {
          participant: {
            user_name: o.name,
            ...(o.puid !== undefined && { participant_uuid: o.puid, user_id: o.puid }),
            ...(o.join && { join_time: o.join }),
            ...(o.leave && { leave_time: o.leave }),
          },
        }),
      },
    },
  };
}

const ROSTER = { '20231234': '홍길동', '20235678': '김철수', '20239999': '이영희' };

it('summarizes attendance: merged stays, late, absent, unmatched, other meetings ignored', () => {
  const events = [
    // 홍길동: 정시 입장 → 나갔다 재입장, 두 번째 접속 중 기기 하나 더(겹침). 총 체류 = 20분 + 15분 = 35분
    ev('meeting.participant_joined', {
      name: '20231234 홍길동',
      puid: 'a1',
      join: '2026-10-12T05:00:00Z',
    }),
    ev('meeting.participant_left', {
      name: '20231234 홍길동',
      puid: 'a1',
      leave: '2026-10-12T05:20:00Z',
    }),
    ev('meeting.participant_joined', {
      name: '20231234 홍길동',
      puid: 'a2',
      join: '2026-10-12T05:25:00Z',
    }),
    ev('meeting.participant_joined', {
      name: '20231234 길동폰',
      puid: 'a3',
      join: '2026-10-12T05:30:00Z',
    }),
    ev('meeting.participant_left', {
      name: '20231234 길동폰',
      puid: 'a3',
      leave: '2026-10-12T05:35:00Z',
    }),
    ev('meeting.participant_left', {
      name: '20231234 홍길동',
      puid: 'a2',
      leave: '2026-10-12T05:40:00Z',
    }),
    // 김철수: 15분 늦게 입장, 퇴장 기록 없음 → 회차 종료 05:40에서 닫힘 = 25분. 도착 순서가 뒤바뀌어도 된다
    ev('meeting.ended', { end: '2026-10-12T05:40:00Z' }),
    ev('meeting.participant_joined', {
      name: '김철수 20235678',
      puid: 'b1',
      join: '2026-10-12T05:15:00Z',
    }),
    // 명단에 없는 학번, 학번 없는 이름 → 미확인
    ev('meeting.participant_joined', {
      name: '20230000 청강생',
      puid: 'c1',
      join: '2026-10-12T05:01:00Z',
    }),
    ev('meeting.participant_joined', { name: 'iPhone', puid: 'd1', join: '2026-10-12T05:02:00Z' }),
    // 다른 미팅 이벤트는 무시
    ev('meeting.participant_joined', {
      meetingId: 222,
      name: '20239999 이영희',
      puid: 'e1',
      join: '2026-10-12T05:00:00Z',
    }),
  ];
  const res = summarizeAttendance(events, ROSTER, {
    meetingId: '111',
    meetingStart: START,
    minMinutes: 20,
    lateAfterMinutes: 10,
  });
  const by = Object.fromEntries(res.entries.map((e) => [e.student_id, e]));
  expect(by['20231234']).toMatchObject({
    status: 'present',
    attended_seconds: 35 * 60,
    overlapping_sessions: true,
  });
  expect(by['20231234']?.display_names).toEqual(['20231234 길동폰', '20231234 홍길동']);
  expect(by['20235678']).toMatchObject({ status: 'late', attended_seconds: 25 * 60 });
  expect(by['20239999']).toMatchObject({ status: 'absent', attended_seconds: 0 });
  expect(res.unmatched.map((u) => u.user_name).sort()).toEqual(['20230000 청강생', 'iPhone']);
  expect(res.unmatched.every((u) => u.leave_time === '2026-10-12T05:40:00Z')).toBe(true); // 퇴장 없으면 종료 시각
});

it('a short stay is absent even when on time', () => {
  const res = summarizeAttendance(
    [
      ev('meeting.participant_joined', {
        name: '20231234 홍길동',
        puid: 'a1',
        join: '2026-10-12T05:00:00Z',
      }),
      ev('meeting.participant_left', {
        name: '20231234 홍길동',
        puid: 'a1',
        leave: '2026-10-12T05:05:00Z',
      }),
    ],
    { '20231234': '홍길동' },
    { meetingId: '111', meetingStart: START, minMinutes: 20, lateAfterMinutes: 10 },
  );
  expect(res.entries[0]).toMatchObject({ status: 'absent', attended_seconds: 300 });
});
