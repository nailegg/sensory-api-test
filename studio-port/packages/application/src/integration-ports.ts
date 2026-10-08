import type {
  AppError,
  ExternalDocument,
  FormSubmission,
  Meeting,
  QuestionSpec,
} from '../../domain/src/index.ts';

// 외부 서비스 port. 메서드는 의미 단위이고 Google 요청 모양은 infrastructure 어댑터 뒤에 둔다.
// 토큰은 인자로 받지 않는다. 어댑터가 만들어질 때 그 교수자의 토큰 공급자를 받는다.
// synsory-api에서 실측된 흐름(usecases.py)이 쓰는 호출만 둔다.

export type DriveRole = 'reader' | 'commenter' | 'writer';

// 사람 한 명분 권한 부여 결과. 실패한 사람만 error가 있다.
export interface PermissionResult {
  email: string;
  permission_id: string | null;
  error: AppError | null;
}

export interface DrivePermission {
  id: string;
  type: 'user' | 'group' | 'domain' | 'anyone';
  role: string;
  email: string | null;
  display_name: string | null;
  // Forms 응답자 권한이면 'published'.
  view: string | null;
}

// 변환 업로드: Markdown·docx → Docs, pptx → Slides, xlsx·csv → Sheets.
export type UploadSource = 'markdown' | 'docx' | 'pptx' | 'xlsx' | 'csv';
export type UploadTarget = 'doc' | 'slides' | 'sheet';

// files.export 형식. Drive에는 Slides 이미지 형식이 없고, Sheets csv·tsv는 첫 시트만 나온다.
export type ExportFormat =
  'docx' | 'pdf' | 'txt' | 'md' | 'html' | 'pptx' | 'odp' | 'xlsx' | 'csv' | 'tsv' | 'ods' | 'zip';

export interface ExportedFile {
  file_id: string;
  filename: string;
  mime_type: string;
  content: Uint8Array;
}

// Google Drive. drive.file scope라 앱이 만든 파일과 사용자가 Picker로 고른 파일만 보인다.
// 그 밖의 파일은 오타 ID와 같은 404다.
export interface GoogleDrivePort {
  getFile(fileId: string): Promise<ExternalDocument>;
  // 사용자가 Drive 웹에서 만든(앱이 못 보는) 폴더 아래에도 만들 수 있다.
  createFolder(name: string, parentFolderId?: string): Promise<ExternalDocument>;
  // 업로드하면서 Google 형식으로 변환한다. multipart 업로드라 5MB 이하.
  createFromContent(input: {
    name: string;
    content: Uint8Array | string;
    source: UploadSource;
    target: UploadTarget;
    parentFolderId?: string;
  }): Promise<ExternalDocument>;
  // 사본은 앱이 만든 파일이 된다. 원본이 앱에 안 보이면(Picker로 안 고른 템플릿) 404.
  copyFile(fileId: string, name: string, parentFolderId?: string): Promise<ExternalDocument>;
  // Docs·Slides·Sheets·Forms 생성 API는 폴더를 못 정해서 만든 뒤 옮긴다.
  moveFile(fileId: string, toFolderId: string): Promise<ExternalDocument>;
  // 휴지통 파일은 뺀다.
  listFiles(pageSize?: number): Promise<ExternalDocument[]>;
  // 파일 종류에 맞는 형식표로 내보낸다. 파일 이름은 Drive 이름 + 확장자. 10MB 상한.
  exportFile(fileId: string, format: ExportFormat): Promise<ExportedFile>;
  trashFile(fileId: string): Promise<void>;
  // 여러 명에게 편집·보기 권한. 같은 파일의 권한 변경은 동시에 하면 안 되므로(마지막 쓰기만 남음)
  // Drive 배치 요청 한 번에 담는다(공식 권장: 순차 또는 배치). 사람별로 성공·실패를 돌려준다.
  // 같은 이메일을 다시 공유하면 기존 permission이 온다(재시도 안전).
  shareWithUsers(
    fileId: string,
    emails: string[],
    role: DriveRole,
    options?: { notify?: boolean; message?: string },
  ): Promise<PermissionResult[]>;
  // Forms 응답자 권한(view=published). 알림은 보내지 않는다. 배치 요청 하나.
  shareAsResponders(fileId: string, emails: string[]): Promise<PermissionResult[]>;
  // includePublishedView면 Forms 응답자 권한도 함께 온다.
  listPermissions(
    fileId: string,
    options?: { includePublishedView?: boolean },
  ): Promise<DrivePermission[]>;
  // 마감: 편집자(writer)를 commenter·reader로 낮춘다.
  updatePermissionRole(
    fileId: string,
    permissionId: string,
    role: DriveRole,
  ): Promise<DrivePermission>;
  deletePermission(fileId: string, permissionId: string): Promise<void>;
}

export type EmailCollection = 'DO_NOT_COLLECT' | 'VERIFIED' | 'RESPONDER_INPUT';

// Google Forms Item JSON(questionItem·questionGroupItem 등). application은 모양을 보지 않고 넘긴다.
export type FormItem = Record<string, unknown>;

// forms.get 결과 중 Synsory가 쓰는 값.
export interface FormStructure {
  form_id: string;
  // 응답자에게 보이는 제목(info.title). Drive 파일 이름과 다를 수 있다.
  title: string | null;
  // 학생에게 줄 링크(/viewform). Drive webViewLink는 편집 화면이다.
  responder_url: string | null;
  // 레거시 폼(publishSettings 없음)은 null.
  published: boolean | null;
  accepting_responses: boolean | null;
  email_collection: EmailCollection | null;
  is_quiz: boolean;
  linked_sheet_id: string | null;
  revision_id: string | null;
  questions: QuestionSpec[];
}

// Google Forms. drive.file scope로 앱이 만든 폼과 Picker로 고른 폼의 모든 메서드가 동작한다.
// 응답은 읽기만 된다(제출·수정·삭제 API 없음). 폴더·권한·복사·휴지통은 GoogleDrivePort.
export interface GoogleFormsPort {
  // 항상 미게시로 만든다. 파라미터 없이 만들면 바로 게시·응답 받기 상태다(2026-10-06 실측, 공식 문서와 다름).
  create(title: string): Promise<string>;
  // batchUpdate 1회(원자적): 설정(퀴즈가 grading보다 먼저) → 제목·설명 → 질문(인덱스 0부터).
  // quiz를 false로 바꾸면 모든 문항의 grading이 지워진다.
  update(
    formId: string,
    changes: {
      title?: string;
      description?: string;
      emailCollection?: EmailCollection;
      quiz?: boolean;
      items?: FormItem[];
    },
  ): Promise<void>;
  // 마감 = (true, false), 열기·재개 = (true, true). 레거시 폼은 오류.
  setPublishState(formId: string, published: boolean, acceptingResponses: boolean): Promise<void>;
  get(formId: string): Promise<FormStructure>;
  // 응답 전체(모든 페이지). since를 주면 lastSubmittedTime >= since만. 경계 응답이 다시 올 수 있어
  // 저장할 때 id로 멱등 처리한다. graded(채점 질문 ID → 배점)를 주면 틀린 문항도 0점으로 grades에 들어간다.
  // expensive read 쿼터(사용자당 분당 180), 페이지마다 1회.
  listResponses(
    formId: string,
    options?: { since?: string; graded?: Record<string, number> },
  ): Promise<FormSubmission[]>;
  // 제출 현황용. 이메일만 받아 응답 크기를 줄인다.
  listRespondentEmails(formId: string): Promise<(string | null)[]>;
}

// 미팅 예약 입력. start_time은 UTC로 보내고 표시 시간대는 timezone으로 따로 준다.
// settings는 Zoom 미팅 settings JSON(대기실 등)이고 application은 모양을 보지 않고 넘긴다.
export interface MeetingSchedule {
  topic: string;
  startTime: Date;
  durationMinutes: number;
  timezone: string;
  settings?: Record<string, unknown>;
}

// Zoom. 사용자 단위 OAuth(General App). 생성·수정은 사용자당 하루 100회(UTC)라 호출자가 센다.
export interface ZoomPort {
  // GET /users/me. plan_type 1 Basic · 2 Licensed · 4 Unassigned
  getMe(): Promise<{ plan_type: number; timezone: string | null }>;
  // 예약 미팅(type 2).
  createMeeting(schedule: MeetingSchedule): Promise<Meeting>;
  // 미팅 하나 + 그룹별 소회의실 사전 배정. rooms = {그룹명: [학생 이메일]}.
  // 학생이 그 이메일의 Zoom 계정으로 로그인해야 자동 배정된다. 계정 설정 "예약 시 참가자를
  // 소회의실에 할당"이 꺼져 있으면 200인데 배정이 조용히 버려진다(docs/zoom.md 10절).
  createBreakoutMeeting(
    schedule: MeetingSchedule,
    rooms: Record<string, string[]>,
  ): Promise<Meeting>;
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

// 태그 치환: {{key}} → 값, 태그별 치환 횟수(0이면 템플릿에 그 태그가 없거나 서식이 갈라진 것).
// google-files.ts의 ReplaceTags와 같은 모양이라 createGroupFilesFromTemplate에 그대로 넘긴다.
export type TagCounts = Record<string, number>;

// Google Docs. 앱이 만든 문서와 Picker로 고른 문서에 drive.file로 동작한다.
export interface GoogleDocsPort {
  replaceTags(documentId: string, variables: Record<string, string>): Promise<TagCounts>;
}

// Google Slides. 텍스트를 바꾸면 도형의 autofit이 꺼져 긴 값이 넘친다.
export interface GoogleSlidesPort {
  replaceTags(presentationId: string, variables: Record<string, string>): Promise<TagCounts>;
}

export interface SheetInfo {
  // 불변. URL의 gid. 이름은 사용자가 바꿀 수 있어 저장 식별자는 이 값이다.
  // 변환 업로드·복사된 파일은 0이 아닐 수 있다(2026-10-04 실측).
  sheet_id: number;
  title: string;
  index: number;
  hidden: boolean;
}

export interface SheetValues {
  sheet_id: number;
  sheet_title: string;
  // 실제 응답 범위(A1). 뒤쪽 빈 행·열은 잘려 있다.
  range: string;
  // UNFORMATTED_VALUE: 숫자는 숫자, 날짜는 1899-12-30 기준 일련번호. 행 끝 빈 칸은 빠진다.
  values: unknown[][];
}

// Google Sheets. 읽기·쓰기 모두 사용자당 분당 60회(요청 수 기준)라 모아서 보낸다.
// 값은 A1 표기(values.*), 구조·보호·치환은 batchUpdate(GridRange)로 다른 API다.
export interface GoogleSheetsPort {
  // findReplace(allSheets, 수식 안 태그 포함).
  replaceTags(spreadsheetId: string, variables: Record<string, string>): Promise<TagCounts>;
  // 빈 스프레드시트(locale ko_KR, Asia/Seoul). 폴더는 못 정해서 Drive moveFile로 옮긴다.
  create(title: string, sheetTitles?: string[]): Promise<string>;
  // index 순.
  listSheets(spreadsheetId: string): Promise<SheetInfo[]>;
  // 시트 하나의 값. sheetId(불변)로 고르면 현재 이름을 찾아 읽는다. 없으면 첫 시트.
  readValues(
    spreadsheetId: string,
    options?: { sheetId?: number; cellRange?: string },
  ): Promise<SheetValues>;
  // RAW로 덮어쓴다(학번 "0123" 유지, 수식도 문자열). USER_ENTERED는 앞자리 0을 잃는다.
  writeValues(
    spreadsheetId: string,
    sheetTitle: string,
    cellRange: string,
    values: string[][],
  ): Promise<void>;
  // A열부터 columns개 열의 값만 지운다(서식·검증은 남는다). 그 오른쪽 열은 건드리지 않는다.
  clearColumns(spreadsheetId: string, sheetTitle: string, columns: number): Promise<void>;
  // 마감 선택지: 파일은 열어 두고 학생 입력 범위만 보호. editors를 항상 명시한다(생략하면 학생 writer도
  // 편집 가능으로 들어가 보호가 무의미, 2026-10-04 실측). 보호는 소유자 토큰의 API 쓰기를 막지 않는다.
  lockRanges(
    spreadsheetId: string,
    sheetId: number,
    cellRanges: string[],
    options?: { description?: string; editorEmails?: string[] },
  ): Promise<number[]>;
  unlockRanges(spreadsheetId: string, protectedRangeIds: number[]): Promise<void>;
}
