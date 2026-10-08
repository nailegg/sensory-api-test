// Zoom 흐름 실측. 미팅을 다음 주로 예약해 확인하고 끝에 모두 지운다(생성·수정 하루 100회 중 6회 정도).
// 웹훅·출석은 공개 https 수신 주소가 필요해 여기서 다루지 않는다(서명·집계는 단위 테스트).
// 토큰은 GOOGLE과 같은 방식으로 synsory-api 토큰 저장소의 "zoom"에서 받는다(README "실측").
// 이 파일은 studio로 이식하지 않는다.
import { createGroupMeetings, rescheduleMeeting } from '../packages/application/src/index.ts';
import { hasFortyMinuteLimit } from '../packages/domain/src/index.ts';
import { createZoom, ExternalApiError } from '../packages/infrastructure/src/index.ts';

const accessToken = process.env['ZOOM_ACCESS_TOKEN'];
if (!accessToken) throw new Error('ZOOM_ACCESS_TOKEN이 필요합니다.');

const zoom = createZoom(async () => accessToken);
const results: [string, boolean][] = [];
function check(name: string, ok: boolean, detail = '') {
  results.push([name, ok]);
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? '  — ' + detail : ''}`);
}

// 다음 주 같은 요일 14:00 KST
const start = new Date(Date.now() + 7 * 86_400_000);
start.setUTCHours(5, 0, 0, 0);
const schedule = { startTime: start, durationMinutes: 40, timezone: 'Asia/Seoul' };
const created: string[] = [];

try {
  const me = await zoom.getMe();
  check(
    'getMe plan type',
    me.plan_type > 0,
    `plan_type=${me.plan_type}, 40분 제한=${hasFortyMinuteLimit(me.plan_type)}`,
  );

  const groups = await createGroupMeetings(zoom, {
    ...schedule,
    teamNames: ['A조', 'B조'],
    topicTemplate: '[studio-port 실측] {{activity_name}} - {{team_name}}',
    activityName: '과제1',
  });
  for (const g of groups) if (g.meeting) created.push(g.meeting.id);
  check(
    'createGroupMeetings: one meeting per team, topic rendered, UTC start kept',
    groups.every((g) => g.meeting?.status === 'scheduled' && !!g.meeting.join_url) &&
      groups[1]?.meeting?.topic === '[studio-port 실측] 과제1 - B조' &&
      Date.parse(groups[0]?.meeting?.start_time ?? '') === start.getTime(),
    `start_time=${groups[0]?.meeting?.start_time}`,
  );

  const recurring = await zoom.createRecurringMeeting(
    { ...schedule, topic: '[studio-port 실측] 정기 수업' },
    { weeklyDays: [start.getUTCDay() + 1], endTimes: 3 },
  );
  created.push(recurring.id);
  check(
    'createRecurringMeeting: 3 weekly occurrences',
    recurring.occurrences.length === 3,
    `${recurring.occurrences.length} occurrence(s)`,
  );

  const second = recurring.occurrences[1]?.id ?? '';
  const third = recurring.occurrences[2]?.id ?? '';
  const rescheduled = await rescheduleMeeting(zoom, recurring.id, { durationMinutes: 30 }, second);
  const durations = rescheduled.occurrences.map((o) => o.duration_minutes);
  check(
    'rescheduleMeeting changes only that occurrence',
    durations.join() === '40,30,40',
    durations.join(),
  );

  await zoom.deleteMeeting(recurring.id, third);
  const after = await zoom.getMeeting(recurring.id);
  check(
    'deleteMeeting(occurrence) leaves the series, marks that occurrence deleted',
    // 취소한 회차는 목록에서 빠지지 않고 status=deleted로 남는다(Python 실측과 같음).
    after.occurrences.map((o) => o.deleted).join() === 'false,false,true',
    after.occurrences.map((o) => `${o.id.slice(-4)}:${o.deleted}`).join(' '),
  );

  const startUrl = await zoom.getStartUrl(recurring.id);
  check(
    'getStartUrl returns a host link (not printed)',
    /^https:\/\/[^ ]*zoom\.us\/s\//.test(startUrl),
  );

  const missing = await zoom.getMeeting('1').catch((e: unknown) => e);
  check(
    'unknown meeting → EXTERNAL_NOT_FOUND with Zoom code',
    missing instanceof ExternalApiError && missing.code === 'EXTERNAL_NOT_FOUND',
    missing instanceof ExternalApiError
      ? `status=${missing.externalStatus} zoomCode=${missing.zoomCode}`
      : String(missing),
  );
} finally {
  for (const id of created) await zoom.deleteMeeting(id, null);
  const gone = await Promise.all(created.map((id) => zoom.getMeeting(id).catch((e: unknown) => e)));
  check(
    'cleanup: all created meetings deleted',
    gone.every((e) => e instanceof ExternalApiError && e.code === 'EXTERNAL_NOT_FOUND'),
    `${created.length} meeting(s)`,
  );
}

const failed = results.filter(([, ok]) => !ok);
console.log(`\n${results.length - failed.length}/${results.length} passed`);
if (failed.length) process.exitCode = 1;
