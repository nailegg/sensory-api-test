// Zoom 도구의 Synsory 규칙: 미팅 형식, 무료 플랜 제한, 웹훅 이벤트로 출석 집계.
// synsory-api app/services/zoom/usecases.py·mapper.py·core/models.py에서 외부 호출 없는 부분의 이식본.
// 시각은 Zoom이 준 RFC3339 문자열 그대로 둔다.

export type MeetingStatus = 'scheduled' | 'started' | 'ended' | 'unknown';

// 반복 미팅의 한 회차. 회차만 바꾸거나 취소할 때 id(Zoom occurrence_id)를 쓴다.
export interface MeetingOccurrence {
  id: string;
  start_time: string | null;
  duration_minutes: number | null;
  // 취소한 회차는 목록에 status=deleted로 남는다(2026-10-05 실측).
  deleted: boolean;
}

// start_url은 2시간 만료 + 받은 사람은 누구나 호스트라 넣지 않는다(필요할 때 port에서 새로 받는다).
export interface Meeting {
  // 미팅 번호. 10자리를 넘을 수 있어 문자열이다.
  id: string;
  provider: 'zoom';
  topic: string;
  // Zoom status에는 ended가 없다. 종료는 웹훅으로만 안다.
  status: MeetingStatus;
  start_time: string | null;
  // 예정 길이. 실제 길이가 아니다.
  duration_minutes: number | null;
  timezone: string | null;
  join_url: string | null;
  host_id: string | null;
  // 미팅 인스턴스 식별자. 반복 미팅은 회차마다 새로 생긴다.
  uuid: string | null;
  // 반복 미팅(type 8)의 회차. 최대 50개.
  occurrences: MeetingOccurrence[];
}

// 유즈케이스 1. Basic(plan_type 1) 호스트의 미팅은 참가자가 1명 이상이면 40분에 끊긴다.
// plan_type: 1 Basic · 2 Licensed · 4 Unassigned
export function hasFortyMinuteLimit(planType: number): boolean {
  return planType === 1;
}

// ---------- 유즈케이스 6: 웹훅 이벤트 → 출석 ----------

// Zoom 웹훅 본문 중 출석에 쓰는 부분(meeting.participant_joined/left, meeting.ended).
export interface ZoomEvent {
  event: string;
  payload?: {
    object?: {
      id?: string | number;
      uuid?: string;
      end_time?: string;
      participant?: {
        user_name?: string;
        participant_uuid?: string;
        user_id?: string;
        join_time?: string;
        leave_time?: string;
      };
    };
  };
}

export interface AttendanceEntry {
  student_id: string;
  // 명단의 이름
  name: string;
  status: 'present' | 'late' | 'absent';
  // 겹치는 접속은 합쳐서 센 실제 체류 시간
  attended_seconds: number;
  first_join: string | null;
  // Zoom에 입력한 표시 이름(명단 이름과 다르면 확인 필요)
  display_names: string[];
  // 같은 학번으로 동시에 두 접속 → 기기 두 대 또는 대리 출석
  overlapping_sessions: boolean;
}

export interface UnmatchedSession {
  user_name: string;
  join_time: string;
  leave_time: string | null;
}

export interface AttendanceSummary {
  entries: AttendanceEntry[];
  // 학번을 못 찾았거나 명단에 없는 접속. 교수자가 직접 짝짓는다.
  unmatched: UnmatchedSession[];
}

interface Session {
  name: string;
  start: string;
  end: string | null;
}

// 접속(participant_uuid)마다 표시 이름·입장·퇴장. 도착 순서가 바뀔 수 있어 이벤트 안의 시각만 쓴다.
// 퇴장이 없으면 그 회차(uuid)의 meeting.ended 시각으로 닫고, 그것도 없으면 null로 둔다.
function sessions(events: ZoomEvent[], meetingId: string): Session[] {
  const ended = new Map<string, string>();
  const joins = new Map<string, { name: string; uuid: string; start: string }>();
  const leaves = new Map<string, string>();
  for (const e of events) {
    const obj = e.payload?.object ?? {};
    if (String(obj.id) !== meetingId) continue;
    const p = obj.participant ?? {};
    const key = p.participant_uuid || `${obj.uuid}:${p.user_id}`;
    if (e.event === 'meeting.ended' && obj.uuid && obj.end_time) ended.set(obj.uuid, obj.end_time);
    else if (e.event === 'meeting.participant_joined' && p.join_time)
      joins.set(key, { name: p.user_name ?? '', uuid: obj.uuid ?? '', start: p.join_time });
    else if (e.event === 'meeting.participant_left' && p.leave_time) leaves.set(key, p.leave_time);
  }
  return [...joins].map(([key, j]) => ({
    name: j.name,
    start: j.start,
    end: leaves.get(key) ?? ended.get(j.uuid) ?? null,
  }));
}

// 겹치는 구간을 합친 총 초, 겹침이 있었는지.
function mergedSeconds(intervals: [number, number][]): [number, boolean] {
  let total = 0;
  let overlap = false;
  let current: [number, number] | null = null;
  for (const [start, end] of intervals.toSorted((a, b) => a[0] - b[0] || a[1] - b[1])) {
    if (current && start < current[1]) {
      overlap = true;
      current[1] = Math.max(current[1], end);
      continue;
    }
    if (current) total += Math.trunc((current[1] - current[0]) / 1000);
    current = [start, end];
  }
  if (current) total += Math.trunc((current[1] - current[0]) / 1000);
  return [total, overlap];
}

// 웹훅 participant_joined/left를 학생별 출석으로 바꾼다. roster = {학번: 이름}.
// 학생은 표시 이름을 "학번 이름"으로 넣고 들어온다(개인 계정 학생은 이메일이 빈 값이라).
// 판정: 체류 ≥ minMinutes면 출석, 그중 첫 입장 > 시작 + lateAfterMinutes면 지각, 나머지는 결석.
export function summarizeAttendance(
  events: ZoomEvent[],
  roster: Record<string, string>,
  input: {
    meetingId: string;
    meetingStart: string;
    minMinutes: number;
    lateAfterMinutes: number;
    studentIdPattern?: RegExp;
  },
): AttendanceSummary {
  const pattern = input.studentIdPattern ?? /\d{8}/;
  const byStudent = new Map<string, Session[]>();
  const unmatched: UnmatchedSession[] = [];
  for (const s of sessions(events, input.meetingId)) {
    const id = pattern.exec(s.name)?.[0];
    if (id !== undefined && Object.hasOwn(roster, id))
      byStudent.set(id, [...(byStudent.get(id) ?? []), s]);
    else unmatched.push({ user_name: s.name, join_time: s.start, leave_time: s.end });
  }
  const lateAfter = Date.parse(input.meetingStart) + input.lateAfterMinutes * 60_000;
  return {
    entries: Object.entries(roster).map(([studentId, name]) => {
      const own = byStudent.get(studentId) ?? [];
      const [seconds, overlap] = mergedSeconds(
        own.flatMap((s) => (s.end === null ? [] : [[Date.parse(s.start), Date.parse(s.end)]])),
      );
      const first = own.reduce<string | null>(
        (min, s) => (min === null || Date.parse(s.start) < Date.parse(min) ? s.start : min),
        null,
      );
      const status =
        own.length === 0 || seconds < input.minMinutes * 60
          ? 'absent'
          : Date.parse(first ?? '') > lateAfter
            ? 'late'
            : 'present';
      return {
        student_id: studentId,
        name,
        status,
        attended_seconds: seconds,
        first_join: first,
        display_names: [...new Set(own.map((s) => s.name))].sort(),
        overlapping_sessions: overlap,
      };
    }),
    unmatched,
  };
}
