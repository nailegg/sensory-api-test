import type { Meeting } from '../../domain/src/index.ts';

// Zoom port. Google port(integration-ports.ts)와 파일을 나눈 이유: studio에서 Google 도구와 Zoom 도구를
// 다른 사람이 다른 브랜치로 작업한다(2026-10-09). 메서드 설명은 docs/zoom.md 11.x.

// 미팅 예약 입력. start_time은 UTC로 보내고 표시 시간대는 timezone으로 따로 준다.
export interface MeetingSchedule {
  topic: string;
  startTime: Date;
  durationMinutes: number;
  timezone: string;
}

// Zoom. 사용자 단위 OAuth(General App). 생성·수정은 사용자당 하루 100회(UTC)라 호출자가 센다.
export interface ZoomPort {
  // GET /users/me. plan_type 1 Basic · 2 Licensed · 4 Unassigned
  getMe(): Promise<{ plan_type: number; timezone: string | null }>;
  // 예약 미팅(type 2).
  createMeeting(schedule: MeetingSchedule): Promise<Meeting>;
  // 매주 반복(type 8). weeklyDays는 1=일 … 7=토. 끝은 날짜 또는 횟수(≤60) 중 하나.
  // join_url은 모든 회차가 같고, 회차별 변경·취소는 occurrences[].id로 한다.
  createRecurringMeeting(
    schedule: MeetingSchedule,
    recurrence: { weeklyDays: number[] } & ({ endDateTime: Date } | { endTimes: number }),
  ): Promise<Meeting>;
  getMeeting(meetingId: string): Promise<Meeting>;
  // 주어진 값만 바꾼다(204). occurrenceId를 주면 그 회차만.
  updateMeeting(
    meetingId: string,
    changes: { startTime?: Date; durationMinutes?: number; topic?: string },
    occurrenceId?: string,
  ): Promise<void>;
  // occurrenceId가 null이면 미팅 전체(반복이면 시리즈 전체)를 지운다. 실수를 막으려고 인자를 꼭 받는다.
  deleteMeeting(meetingId: string, occurrenceId: string | null): Promise<void>;
  // 호스트 시작 링크. 2시간 만료 + 받은 사람은 누구나 호스트라 저장·로그 금지. 누를 때마다 새로 받는다.
  getStartUrl(meetingId: string): Promise<string>;
}
