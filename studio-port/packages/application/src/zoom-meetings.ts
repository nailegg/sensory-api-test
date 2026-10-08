import { AppError, renderTemplate, type Meeting } from '../../domain/src/index.ts';
import type { MeetingSchedule, ZoomPort } from './integration-ports.ts';

// Zoom 흐름 중 호출 여러 개를 엮는 것. synsory-api app/services/zoom/usecases.py의 이식본.
// 플랜 확인·소회의실·반복·취소·시작 링크는 ZoomPort 메서드 하나라 여기 두지 않는다.

export interface GroupMeetingResult {
  team_name: string;
  meeting: Meeting | null;
  error: AppError | null;
}

// 유즈케이스 2(A 방식): 그룹마다 예약 미팅 하나. 그룹 수만큼 생성하므로 하루 100회(생성+수정 합산)를
// 넘지 않게 호출자가 센다. 한 그룹이 실패해도 나머지를 계속한다. 학생에게 줄 링크는 각 meeting.join_url.
export async function createGroupMeetings(
  zoom: ZoomPort,
  input: Omit<MeetingSchedule, 'topic'> & {
    teamNames: string[];
    topicTemplate: string;
    activityName?: string;
  },
): Promise<GroupMeetingResult[]> {
  const { teamNames, topicTemplate, activityName, ...schedule } = input;
  const results: GroupMeetingResult[] = [];
  for (const team of teamNames) {
    const topic = renderTemplate(topicTemplate, {
      team_name: team,
      activity_name: activityName ?? '',
    });
    try {
      results.push({
        team_name: team,
        meeting: await zoom.createMeeting({ ...schedule, topic }),
        error: null,
      });
    } catch (e) {
      if (!(e instanceof AppError)) throw e;
      results.push({ team_name: team, meeting: null, error: e });
    }
  }
  return results;
}

// 유즈케이스 4. 주어진 값만 바꾼다. occurrenceId를 주면 반복 미팅의 그 회차만. 하루 100회에 포함된다.
// PATCH는 204라 바뀐 값을 다시 읽어 돌려준다.
export async function rescheduleMeeting(
  zoom: ZoomPort,
  meetingId: string,
  changes: { startTime?: Date; durationMinutes?: number; topic?: string },
  occurrenceId?: string,
): Promise<Meeting> {
  if (Object.values(changes).every((v) => v === undefined))
    throw new AppError('NO_CHANGES', 422, '바꿀 값이 없습니다.');
  await zoom.updateMeeting(meetingId, changes, occurrenceId);
  return zoom.getMeeting(meetingId);
}
