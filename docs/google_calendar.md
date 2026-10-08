# Google Calendar 연동 스펙

상태: 1단계(API 탐색) 완료 · **보류**(2026-10-06 상현: Meet은 Calendar 없이 단독으로 쓴다. 학생 캘린더에 띄울 필요 없음). 예약·초대가 필요해지면 이 문서에서 다시 시작한다
최종 수정: 2026-10-06 · 작성: 상현
확인 기준: 공식 문서 2026-10-06(developers.google.com Calendar API v3 레퍼런스·가이드·릴리스 노트, support.google.com Calendar·Meet). 실측 없음.

**왜 조사했나.** Google Meet REST API에는 시각 필드가 없어 "시각이 있는 Meet 예약"은 Calendar 일정으로만 된다(`docs/google_meet.md` 1단계 요약). 이 문서는 Calendar를 Meet 예약 수단으로 쓸 수 있는지, 비용(scope·제약)이 얼마인지를 본다. **Calendar를 독립 서비스로 1~7단계를 밟을지, Drive처럼 Meet이 기대는 레이어로만 둘지는 2단계 결정이다.** 레이어로 두면 Calendar 호출은 `app/services/google_calendar/client.py`에 모으고 Meet의 `usecases.py`가 불러 쓴다(CLAUDE.md: 다른 서비스 client import는 usecases에서만).

이식 대상(예정, studio에 TS로 이식): `app/services/google_calendar/{client,mapper,scopes,usecases}.py`와 이 문서. Base URL `https://www.googleapis.com/calendar/v3`.

---

## 1단계 요약: 할 수 있는 일 · 못 하는 일 · 눈에 띄는 제약

2단계에서 유즈케이스를 고를 때 보는 한 장이다. 아래 3~12절은 이 요약의 근거다.

**리소스.** 캘린더(`calendarId`, 기본 캘린더는 `primary`, 앱이 만드는 **보조 캘린더**도 가능) 안에 일정(`events`)이 있다. 반복 일정은 부모 일정 하나 + `recurrence`(RRULE)이고, 회차(`instances`)는 계산되어 나오며 회차를 고치면 예외가 생긴다. 일정에 **Meet 회의(`conferenceData`)**를 붙이면 `hangoutLink`가 생긴다. 참석자(`attendees[]`)를 넣으면 **교수자 이메일로 초대 메일**이 가고, 응답(`responseStatus`)이 교수자 쪽 일정에 모인다.

**할 수 있는 일**

| 분류 | 내용 | 메서드 |
| --- | --- | --- |
| Meet 예약 | 시각·제목·설명이 있는 일정 + 새 Meet 링크를 한 번에 생성 | `events.insert?conferenceDataVersion=1` + `conferenceData.createRequest{type: hangoutsMeet}` |
| 반복 수업 | 매주 반복 일정(RRULE), 특정 회차만 변경·취소, 반복 종료일 | `recurrence[]`, `events.instances` → 회차 `update` |
| 초대·출석 응답 | 학생 이메일을 참석자로 넣어 초대 메일 발송(Google 계정 아니어도 됨), 수락·거절·미정 확인 | `attendees[]` + `sendUpdates=all`, `events.get` → `attendees[].responseStatus` |
| 변경·취소 | 시각 변경·취소 시 참석자에게 변경 메일 | `events.patch` / `update` / `delete` + `sendUpdates` |
| 앱 전용 캘린더 | "Synsory 수업" 같은 보조 캘린더를 만들어 앱 일정을 거기에만 둔다. 가장 좁은 scope로 가능 | `calendars.insert` + `calendar.app.created` |
| 태그·검색 | 일정에 `activityId`·`groupId`를 숨김 속성으로 달고 그 값으로 검색 | `extendedProperties.private` + `events.list?privateExtendedProperty=activityId=…` |
| 멱등 생성 | 일정 `id`를 앱이 지정(같은 id 재생성 시 409) | `events.insert`의 `id` |
| 변경 알림 | 일정이 바뀌면 **https 웹훅**으로 알림(Pub/Sub 아님) → `syncToken`으로 증분 조회 | `events.watch`, `events.list?syncToken=` |
| 빈 시간 | 교수자의 바쁜 시간대 조회 | `freeBusy.query` |

**못 하는 일 · 주의할 일**

- **Meet 설정은 Calendar로 못 한다.** `createRequest`에는 접근 방식·자동 녹화 같은 필드가 없다. Calendar가 만든 Meet 공간은 Meet API에서 **"다른 앱이 만든 공간"**으로 분류되어 `meetings.space.created`로는 관리할 수 없다. 설정은 `meetings.space.settings`(비민감), 회의 기록·출석 조회는 `meetings.space.readonly`(민감)가 필요하다(Meet 공간 개요 가이드의 scope 표).
- **이미 만든 Meet 공간(`spaces.create`)을 일정의 Meet 회의로 붙이는 공식 경로가 없다.** 문서에 있는 것은 "다른 일정의 `conferenceData` 전체 복사"뿐이고, 2026-02-17부터 Google은 **"이벤트마다 `createRequest`로 새 회의를 만들라, Meet 코드 재사용은 접근 문제와 노출을 일으킨다"**고 권고한다. 그래서 `docs/google_meet.md`에서 비교한 B안(Meet으로 링크 → Calendar에 붙이기)은 **링크를 일정 설명·장소에 텍스트로 넣는 방식만 남는다**(Meet 버튼 없음).
- **앱 캘린더를 학생에게 공유하려면 `calendar.acls`가 추가로 필요하다.** `calendar.app.created`는 ACL·`calendarList`·`move`를 허용하지 않는다. 학생에게 일정이 보이게 하는 기본 방법은 공유가 아니라 **참석자 초대**다.
- **초대 메일은 교수자 이메일 이름으로 나간다**("Attendees receive the invitation from the organizer's email address"). Synsory 이름으로 보낼 수 없다.
- **학생이 응답해야 캘린더에 들어갈 수 있다.** 받는 사람 설정이 "알려진 발신자만" / "응답할 때만"이면 교수와 연락한 적 없는 학생은 메일에서 응답해야 일정이 추가된다.
- **Meet 생성은 비동기다.** 첫 응답의 `conferenceData.createRequest.status`가 `pending`일 수 있어 `success`가 될 때까지 다시 읽는다.
- `conferenceDataVersion=1`을 빠뜨리면 **Meet이 조용히 무시**된다. 수정 요청에서도 빠뜨리면 회의 정보가 지워질 수 있다.

**눈에 띄는 제약**

| 항목 | 값 | 비고 |
| --- | --- | --- |
| 쿼터 | 프로젝트당 분당 10,000 · 사용자당 분당 600 · 프로젝트당 하루 1,000,000(과금 기준선) | `patch`는 **3단위**를 쓴다("prefer get followed by update"). 2026년 중 과금 세부 공지 예정(90일 전 고지) |
| Calendar 사용 한도 | 외부 초대 단기간 10,000건, 캘린더 생성 60개 등(Workspace 관리자 문서) | **개인 Gmail 수치는 비공개**("we don't publicize the exact limits"). 넘으면 403 `quotaExceeded` |
| 게스트 | 200명 넘으면 응답 전파 등 기능 제한 | 수업 단위로는 문제 없음 |
| scope 민감도 | 공식 표 없음. 이벤트 읽기는 민감 예시로 언급됨 | 콘솔 "데이터 액세스"에서 추가할 때 표시로 확인(12절). Meet `meetings.space.created`가 이미 민감이라 검증 부담은 어차피 생긴다 |
| 웹훅 | https 주소, 기본 수명 7일, **자동 갱신 없음**, 본문 없음 | Workspace Events API는 Calendar 미지원 |
| 반복 일정 | `timeZone` 필수 | 회차 수정은 예외 생성. 시리즈 전체 수정은 부모를 고친다 |
| 개인 계정 | Meet 붙이기가 되는지 명시 없음 | `calendars.get(primary)`의 `conferenceProperties.allowedConferenceSolutionTypes`에 `hangoutsMeet`이 있는지로 확인 |

**Meet 예약 방식 다시 보기** (`docs/google_meet.md`의 A·B·C안을 이 조사로 갱신)

| 안 | 흐름 | Calendar scope | Meet scope | 1단계 판단 |
| --- | --- | --- | --- | --- |
| **A. Calendar가 Meet까지** | 그룹마다 `events.insert` + `createRequest` → `hangoutLink`. 학생은 참석자로 초대 | `calendar.app.created`(보조 캘린더) 또는 `calendar.events.owned`(기본 캘린더) | 링크만 쓰면 **없음**. 출석·강제 종료까지 하면 `meetings.space.readonly`(민감) + 종료는 미확인 | Google 권장 경로. 일정에 Meet 버튼·초대·반복이 다 붙는다. 대신 출석·종료를 하려면 Meet scope가 오히려 넓어진다 |
| **B. Meet이 링크, Calendar는 일정만** | `spaces.create` → `meetingUri`를 `events.insert`의 `location`·`description`에 텍스트로 | 위와 같음 | `meetings.space.created` | 출석·종료·설정을 좁은 scope로 할 수 있다. 일정엔 Meet 버튼이 없고 텍스트 링크. 2026-02 권고(`conferenceData` 재사용 금지)와는 충돌하지 않는다(회의 데이터를 복사하지 않으므로) |
| **C. Calendar 없음** | `spaces.create`만, 시각은 Synsory | 없음 | `meetings.space.created` | 학생 캘린더에 안 뜬다. 가장 가볍다 |

정리하면 **"링크와 초대만" → A가 깔끔**, **"출석·강제 종료까지" → B가 scope 면에서 유리**, **"캘린더 불필요" → C**다.

**Synsory 관점에서 유즈케이스 후보 (2단계 참고용, 확정 아님)**

- 교수자 계정에 "Synsory" 보조 캘린더를 한 번 만들고(`calendars.insert`, `calendar.app.created`), 모든 수업 일정을 거기에 둔다. 교수자 기본 캘린더를 건드리지 않고, scope가 가장 좁다.
- 액티비티 그룹마다 일정을 만들고 그룹 학생을 참석자로 초대한다(`sendUpdates=all`). Meet은 A 또는 B. `extendedProperties.private`에 `activityId`·`groupId`를 넣어 다시 찾는다.
- 매주 반복 수업은 반복 일정 하나로 만들고, 휴강은 회차 취소(`status=cancelled`)로 처리한다.
- 시간 변경·취소는 일정 수정·삭제 + `sendUpdates=all`로 학생에게 변경 메일이 가게 한다.
- 학생 응답(수락·거절)을 읽어 Synsory에 "참석 예정" 표시를 한다(`responseStatus`). 실제 출석은 Meet 참가자 API의 몫이다.
- 일정 변경 감지(교수자가 캘린더에서 직접 옮긴 경우)는 `events.watch` 웹훅 + `syncToken` 증분 조회. 폴링으로도 충분한지 2단계에서 본다.

---

## 1. 이 서비스로 하는 일 (유즈케이스)

2단계에서 상현이 확정한다. 먼저 정할 것: ① Calendar를 쓰는지(쓰지 않으면 Meet C안), ② 쓴다면 Meet A안·B안 중 무엇인지, ③ 보조 캘린더(`calendar.app.created`)인지 교수자 기본 캘린더(`calendar.events.owned`)인지, ④ 독립 서비스인지 Meet용 레이어인지.

| # | 유즈케이스 | 호출 순서 | usecases 함수 |
| --- | --- | --- | --- |
| (2단계 후 채움) | | | |

## 2. 인증

Google 4종·Meet과 같은 OAuth 클라이언트·동의 화면을 쓴다(`docs/google_docs.md` 2절). Calendar에서 추가로 할 일:

- GCP 콘솔에서 **Google Calendar API**를 사용 설정한다. 2026-05-01 이후 새로 쓰기 시작한 프로젝트는 새 쿼터 등급 모델이 적용된다(8절).
- 동의 화면 "데이터 액세스"에 고른 Calendar scope를 추가하고 **민감도 표시를 기록한다**(공식 문서에 표가 없다).
- scope가 늘면 기존 사용자 전원 재동의. Meet scope와 같이 넣으면 재동의를 한 번으로 줄인다.
- 웹훅(9절)을 쓰면 https 공개 주소가 필요하다(ngrok, Zoom과 같은 조건). 도메인 소유 확인 요구는 현재 가이드에 없다.
- 사용자 모델: OAuth 연결은 교수자(일정 주최자). 학생은 앱을 연결하지 않고 초대 메일·캘린더로 일정을 받는다. Google 계정이 아니어도 초대 메일로 응답할 수 있다.

## 3. scope 표

출처: Calendar 인증 가이드와 각 메서드 레퍼런스의 "Authorization scopes"(2026-10-06). 등급은 공식 표가 없어 전부 미확인이다.

| scope | 공식 설명 | 1단계 판단 |
| --- | --- | --- |
| `https://www.googleapis.com/auth/calendar.app.created` | 보조 캘린더를 만들고 그 안의 일정을 보기·만들기·수정·삭제 | **기본 후보.** `calendars.insert/get/patch/delete`, `events.insert/get/list/patch/update/delete/instances/watch/import/quickAdd` 허용. 기본 캘린더·ACL·`calendarList`·`move`는 불가. `createRequest`(Meet)가 이 scope로 되는지는 막는 문구가 없을 뿐 미확인 |
| `…/calendar.events.owned` | 내가 소유한 캘린더의 일정 보기·만들기·수정·삭제 | 교수자 **기본 캘린더**에 넣어야 할 때 |
| `…/calendar.events.owned.readonly` | 내가 소유한 캘린더의 일정 보기 | |
| `…/calendar.events` | 모든 캘린더의 일정 보기·편집 | 넓다. 쓰지 않는다 |
| `…/calendar` | 모든 캘린더 보기·편집·공유·영구 삭제 | 가장 넓다. 쓰지 않는다 |
| `…/calendar.acls` | 내 캘린더의 공유 권한 보기·변경 | 보조 캘린더를 학생에게 **공유**할 때만. 초대로 충분하면 불필요 |
| `…/calendar.calendars` | 캘린더 속성 보기·변경, 보조 캘린더 생성 | `calendar.app.created`로 대체 |
| `…/calendar.calendarlist` | 구독 중인 캘린더 목록 추가·제거 | 불필요 |
| `…/calendar.freebusy`, `…/calendar.events.freebusy` | 빈 시간 보기 | 교수자 빈 시간에 맞춰 예약 제안을 하는 경우만 |
| `…/calendar.readonly`, `…/calendar.events.readonly`, `…/calendar.calendars.readonly`, `…/calendar.calendarlist.readonly`, `…/calendar.acls.readonly`, `…/calendar.settings.readonly`, `…/calendar.events.public.readonly`, `…/calendar.addons.*` | 읽기 전용·애드온 | 불필요 |

- 초대 발송에 별도 scope는 없다. 일정 쓰기 scope + `sendUpdates`.
- 1단계 권고: `calendar.app.created` 하나로 시작. 교수자가 "내 기본 캘린더에 보여야 한다"고 하면 `calendar.events.owned`로 바꾼다.

## 4. 엔드포인트 표

Base URL `https://www.googleapis.com/calendar/v3`.

**4.1 일정(events)**

| 메서드 | 경로 | 용도 | 비고 |
| --- | --- | --- | --- |
| `POST` | `/calendars/{calendarId}/events` | 생성 | 쿼리 `conferenceDataVersion=1`(Meet), `sendUpdates=all/externalOnly/none`, `maxAttendees`. 본문 `id`를 주면 멱등(중복 시 409) |
| `GET` | `/calendars/{cid}/events/{eid}` | 조회 | Meet `pending` 재확인, 참석자 응답 확인 |
| `GET` | `/calendars/{cid}/events` | 목록 | `timeMin`/`timeMax`(오프셋 필수), `singleEvents=true`(회차 전개) + `orderBy=startTime`, `privateExtendedProperty=k=v`, `showDeleted`, `maxResults` 기본 250·최대 2,500, `syncToken`(다른 필터와 함께 못 씀) |
| `PUT` | `/calendars/{cid}/events/{eid}` | 전체 교체 | 1단위. Meet 유지하려면 `conferenceDataVersion=1` |
| `PATCH` | `/calendars/{cid}/events/{eid}` | 부분 수정 | **3단위.** 배열 필드(`attendees` 등)는 보낸 값으로 통째 교체 |
| `DELETE` | `/calendars/{cid}/events/{eid}` | 삭제 | `sendUpdates`로 취소 메일 |
| `GET` | `/calendars/{cid}/events/{eid}/instances` | 반복 회차 | 회차 id로 `PUT`하면 그 회차만 변경(예외 생성) |
| `POST` | `/calendars/{cid}/events/watch` | 변경 알림 채널 | 9절 |
| `POST` | `/calendars/{cid}/events/{eid}/move?destination=` | 다른 캘린더로 이동(주최자 변경) | `calendar.app.created` 불가 |

**Event 주요 필드**

| 필드 | 내용 | 비고 |
| --- | --- | --- |
| `summary`, `description`, `location` | 제목·설명·장소 | B안이면 `meetingUri`를 `location`이나 `description`에 |
| `start`/`end` | `dateTime`(RFC3339) + `timeZone`(IANA), 또는 종일 `date` | `end`는 배타적. 반복이면 `timeZone` 필수 |
| `recurrence[]` | `RRULE:FREQ=WEEKLY;BYDAY=MO,WE;UNTIL=…`, `EXDATE` | `DTSTART`·`DTEND` 줄은 넣지 않는다 |
| `attendees[]` | `email`(필수), `displayName`, `optional`, `responseStatus`(needsAction/accepted/declined/tentative) | 200명 넘으면 응답 전파 안 됨 |
| `guestsCanModify` / `guestsCanInviteOthers` / `guestsCanSeeOtherGuests` | 기본 false / **true** / **true** | 수업이면 뒤의 둘을 false로(학생이 다른 학생 이메일을 보거나 외부인을 초대하지 못하게) |
| `reminders` | `useDefault` 또는 `overrides[]{method email/popup, minutes}` 최대 5개 | 참석자 각자의 캘린더에 따로 적용되는 값 |
| `conferenceData` | `createRequest{requestId, conferenceSolutionKey.type, status.statusCode}`, `conferenceId`(= Meet 코드 `aaa-bbbb-ccc`), `entryPoints[]`, `conferenceSolution` | 같은 `requestId`로 다시 보내면 무시. `hangoutsMeet`만 생성 가능(`eventHangout`류는 폐지) |
| `hangoutLink`, `htmlLink` | Meet 링크, 캘린더 웹 링크 | 읽기 전용 |
| `extendedProperties.private` / `.shared` | 앱 태그 | 키 44자·값 1,024자, 일정당 300개·32kB. `shared`는 주최자만 수정 |
| `id`, `iCalUID`, `recurringEventId`, `originalStartTime` | 식별자 | `id`는 base32hex(a-v, 0-9) 5~1,024자. 반복 회차는 `iCalUID` 공유, `id`는 회차마다 다름 |
| `status` | confirmed / tentative / cancelled | 취소된 일정은 증분 동기화나 `showDeleted`에서만 보임 |
| `organizer`, `creator` | 읽기 전용 | 주최자 변경은 `move` |
| `source` | `{url, title}` | Synsory 액티비티 링크를 넣을 수 있음(만든 사람에게만 보임) |
| `eventType` | default / birthday / focusTime / outOfOffice / workingLocation / fromGmail | 생성 후 변경 불가. 수업 일정은 default |

**4.2 캘린더·기타**

| 메서드 | 경로 | 용도 | 비고 |
| --- | --- | --- | --- |
| `POST` | `/calendars` | 보조 캘린더 생성 | `summary`만 필수, `timeZone` 권장. `calendar.app.created` 가능 |
| `GET` | `/calendars/{cid}` | 캘린더 정보 | `primary`로 부르면 `conferenceProperties.allowedConferenceSolutionTypes`로 Meet 가능 여부 확인 |
| `DELETE` | `/calendars/{cid}` | 보조 캘린더 삭제 | 보조만. 2025-11부터 데이터 소유자만 삭제 |
| `POST` | `/calendars/{cid}/acl` | 공유 | `calendar.acls` 필요 |
| `POST` | `/freeBusy` | 바쁜 시간대 | freebusy scope |
| `POST` | `/channels/stop` | 알림 채널 중지 | `{id, resourceId}` |

**4.3 Meet 예약 요청 모양(A안)**

```
POST /calendars/{cid}/events?conferenceDataVersion=1&sendUpdates=all
{
  "id": "<base32hex 멱등 키>",
  "summary": "{{activity_name}} · {{team_name}}",
  "start": {"dateTime": "2026-10-12T14:00:00+09:00", "timeZone": "Asia/Seoul"},
  "end":   {"dateTime": "2026-10-12T15:00:00+09:00", "timeZone": "Asia/Seoul"},
  "attendees": [{"email": "student@example.com"}],
  "guestsCanInviteOthers": false,
  "guestsCanSeeOtherGuests": false,
  "extendedProperties": {"private": {"activityId": "…", "groupId": "…"}},
  "conferenceData": {"createRequest": {"requestId": "<uuid>", "conferenceSolutionKey": {"type": "hangoutsMeet"}}}
}
```

응답의 `conferenceData.createRequest.status.statusCode`가 `pending`이면 `GET`으로 다시 읽어 `hangoutLink`를 얻는다. 반복이면 `"recurrence": ["RRULE:FREQ=WEEKLY;BYDAY=MO;UNTIL=20261220T000000Z"]`를 더한다.

## 5. 요청·응답 샘플

5단계에서 `samples/google_calendar/`에 채운다. 마스킹 대상: 토큰·참석자 이메일·`organizer`/`creator` 이메일·`hangoutLink`·`conferenceId`·`entryPoints[].pin`·`htmlLink`의 `eid`·`iCalUID`.

## 6. 공통 모델 매핑

Calendar 일정은 `Meeting`의 시각 부분을 채운다. Meet과 함께 쓸 때의 제안(확정은 2단계):

| Meeting 필드 | 출처 | 비고 |
| --- | --- | --- |
| `id` | Meet `spaces/{id}`(B안) 또는 Calendar 일정 `id`(A안) | A안이면 공간 이름은 `spaces.get("spaces/{conferenceId}")`로 얻는다 |
| `topic` | `summary` | Meet 공간에는 제목이 없어 Calendar가 유일한 출처 |
| `start_time` | `start.dateTime` | 반복이면 회차의 `originalStartTime`/`start` |
| `duration_minutes` | `end - start` | |
| `join_url` | `hangoutLink`(A) 또는 `meetingUri`(B) | |
| `host_id` | `organizer.email` | 샘플 저장 시 마스킹. 이메일을 모델에 넣을지는 2단계(`Document.owner`는 이름만 넣는 규칙) |
| `status` | `status == cancelled` → 취소. 진행 중·종료는 Meet API | `MeetingStatus`에 `CANCELLED` 추가 필요 여부 2단계 |

추가 제안: `calendar_event_id`, `recurring_event_id`, 참석자 응답 요약(수락 n·거절 n). 참석자 목록은 `Participant` 공통 모델 논의(`docs/google_meet.md` 6절)와 함께 정한다.

## 7. 에러와 예외 케이스

공식 에러 가이드(2026-10-06). 형식은 Google 표준 `{"error": {"code", "message", "errors": [{"reason"}]}}`.

| 상황 | HTTP | reason | 대응 |
| --- | --- | --- | --- |
| 빈 시간 범위 | 400 | `timeRangeEmpty` | 재시도 안 함 |
| 토큰 만료 | 401 | `authError` | refresh |
| 사용자·프로젝트 rate limit | 403 / 429 | `userRateLimitExceeded`, `rateLimitExceeded` | 지수 백오프 |
| Calendar 사용 한도 | 403 | `quotaExceeded` "Calendar usage limits exceeded." | 백오프로 안 풀림. 초대·생성량 줄이기 |
| 주최자 아닌 사람이 `shared` 속성 수정 | 403 | `forbiddenForNonOrganizer` | |
| 없는 일정 | 404 | `notFound` | |
| 같은 `id`로 재생성 | 409 | `duplicate` | 멱등 처리(이미 있음 = 성공으로 보고 `get`) |
| 오래된 `syncToken` | 410 | `fullSyncRequired` / `updatedMinTooLongAgo` | 저장소 비우고 전체 동기화 |
| ETag 불일치 | 412 | `conditionNotMet` | 다시 읽고 재적용 |
| 서버 오류 | 500 | `backendError` | 백오프 |
| Meet 생성 실패 | 200 | — | `createRequest.status.statusCode == failure`. HTTP는 성공이라 상태를 봐야 한다 |

에러 클래스는 Google 공통 `GoogleApiError` 형태를 따른다. 403은 rate limit일 수도 있어 `reason`으로 나눈다(Drive와 같은 규칙).

## 8. 쿼터 · rate limit · 플랜 제약

| 구분 | 값 |
| --- | --- |
| 프로젝트당 분당 | 10,000 요청 |
| 프로젝트·사용자당 분당 | 600 요청 |
| 프로젝트당 하루 | 1,000,000 요청(과금 기준선). "Full billing details will be shared later in 2026 with at least 90 days' notice" |
| `patch` | 요청 1회 = **3단위** |

- 2026-05-01 이후 처음 Calendar API를 쓰는 프로젝트에는 새 쿼터 등급 모델이 적용된다. 우리 프로젝트는 아직 Calendar를 쓰지 않았으므로 새 모델 대상이다. 세부 수치는 콘솔에서 확인(12절).
- **Calendar 사용 한도**(API 쿼터와 별개, 계정 단위): Workspace 문서 기준 외부 초대 단기간 10,000건, 일정 생성 100,000건 초과 시, 게스트에게 메일 약 2,000통, 캘린더 생성 60개, 공유 750건. 개인 Gmail은 "더 엄격할 수 있고 공개하지 않는다". 수업 규모(그룹 수십 개, 학생 수백 명)에서는 걸리지 않을 것으로 본다.
- Meet 무료 제한(3명 이상 60분)은 Calendar로 만들어도 같다. 주최자 계정 플랜을 따른다.

## 9. 웹훅 (해당 시)

Calendar는 **https 웹훅**으로 변경 알림을 보낸다(Pub/Sub 아님, Workspace Events API 미지원). Zoom 웹훅과 같은 인프라(ngrok)를 쓸 수 있다.

- 등록: `POST /calendars/{cid}/events/watch` `{"id": "<uuid, 최대 64자>", "type": "web_hook", "address": "https://<ngrok>/google/calendar/webhook", "token": "<검증용, 최대 256자>", "params": {"ttl": "604800"}}`. 유효한 SSL 인증서 필요(자체 서명 불가).
- 수명: 기본 7일(604,800초). 최대값은 "요청값과 내부 한도 중 더 짧은 것"이라 명시 없음. **자동 갱신 없음** — 만료 전에 새 `id`로 다시 `watch`(겹치는 기간 허용).
- 알림: **본문 없음.** 헤더 `X-Goog-Channel-ID`, `X-Goog-Resource-ID`, `X-Goog-Resource-State`(`sync` 등록 확인 / `exists` 변경 / `not_exists` 삭제), `X-Goog-Message-Number`, `X-Goog-Channel-Token`(설정 시). 토큰을 비교해 위조를 거른다(Zoom 같은 HMAC 서명은 없다).
- 응답: 2xx(102 포함)면 성공. 5xx면 지수 백오프로 재전송.
- 처리: 알림을 받으면 `events.list?syncToken=<저장값>`으로 바뀐 것만 받고 마지막 페이지의 `nextSyncToken`을 저장한다. 410이면 전체 동기화.
- 중지: `POST /channels/stop {id, resourceId}`.

**1단계 판단**: 앱이 만든 일정을 앱이 바꾸는 동안에는 알림이 필요 없다. 교수자가 Google 캘린더에서 직접 시각을 옮기는 경우를 Synsory에 반영해야 할 때만 쓴다. 그 전엔 Synsory 화면을 열 때 `events.get`으로 확인하는 정도로 충분하다.

## 10. 함정과 권장 패턴

1. **`conferenceDataVersion=1`을 모든 쓰기 요청에.** 빠뜨리면 생성 때는 Meet이 조용히 빠지고, 수정 때는 기존 회의가 지워질 수 있다. client에서 기본값으로 박는다.
2. **Meet 생성은 `pending`일 수 있다.** 응답에서 `hangoutLink`가 없으면 짧게 백오프하며 `get`. `failure`면 HTTP 200이어도 실패로 처리한다.
3. **Meet 코드를 일정끼리 재사용하지 않는다**(2026-02-17 권고). 그룹마다 `createRequest`. `requestId`는 그룹마다 새 UUID(같은 값이면 요청이 무시된다).
4. **Calendar가 만든 Meet은 "다른 앱이 만든 공간".** `meetings.space.created`로는 관리 못 한다. A안에서 출석·설정을 하려면 `meetings.space.readonly`·`settings`. 이 비용 때문에 B안이 남아 있다.
5. **멱등 키 = 일정 `id`.** `activityId+groupId`를 base32hex로 인코딩해 `id`로 쓰면 재시도·중복 클릭에도 일정이 하나만 생긴다. 409는 "이미 있음"으로 처리.
6. **앱 태그는 `extendedProperties.private`.** 학생 사본에 보이지 않고, `privateExtendedProperty`로 검색된다. Synsory DB에 일정 id를 저장하는 것과 병행한다.
7. **학생끼리 이메일이 보이는 기본값을 끈다.** `guestsCanSeeOtherGuests` 기본 true. 그룹 일정에는 false.
8. **`patch`는 3단위, 배열은 통째 교체.** 참석자 한 명 추가에 `patch`로 `attendees`를 보내면 보낸 목록으로 덮인다. `get` → 수정 → `update`.
9. **`sendUpdates=none`은 위험하다고 공식 경고.** 외부 캘린더 동기화가 안 되거나 일정이 사라질 수 있다. 학생에게 보내는 일정은 `all`, 교수자 혼자 보는 일정은 생략 대신 명시적으로 정한다. 생략했을 때의 실제 기본 동작은 문서 표기가 엉켜 있어 실측(12절).
10. **반복 일정은 `timeZone` 필수, 회차 수정은 예외.** 시리즈 전체 변경은 부모 일정을 고친다. 회차 하나씩 고쳐 전체를 바꾸지 않는다. "이후 모든 회차" 변경은 부모 `UNTIL`을 줄이고 새 시리즈를 만드는 방식(공식 가이드에 절차 없음).
11. **`timeMin`/`timeMax`에는 오프셋 필수.** `2026-10-12T00:00:00+09:00`. 오프셋 없는 값은 400.
12. **초대 메일은 교수자 이름으로 나간다.** 학생이 처음 받는 메일이라 스팸·무시될 수 있다. Synsory 화면에도 링크를 같이 보여준다.
13. **보조 캘린더 삭제는 데이터 소유자만**(2025-11~). 앱이 만든 캘린더를 정리할 때 교수자 토큰으로 지운다.
14. **SDK 없이 REST.** 메서드 몇 개, 전부 JSON. httpx로 충분.

## 11. 샘플 코드 (`usecases.py`의 흐름을 기준으로)

2단계에서 Calendar를 쓰기로 하면 5단계에서 `app/services/google_calendar/usecases.py`(또는 Meet `usecases.py`가 `google_calendar.client`를 부르는 형태)를 구현한 뒤 작성한다.

## 12. 미확인 · 보류 항목

| 항목 | 확인 방법 · 시점 |
| --- | --- |
| **개인 Gmail에서 일정에 Meet(`hangoutsMeet`)을 붙일 수 있는지** | 3단계. `calendars.get(primary)`의 `allowedConferenceSolutionTypes` 확인 후 `events.insert` 1회 |
| `calendar.app.created`만으로 보조 캘린더 일정에 `createRequest`가 되는지 | 3단계. 보조 캘린더 생성 → Meet 일정 생성 |
| Calendar scope 각각의 민감도 | 3단계. 콘솔 "데이터 액세스"에 추가할 때 표시 기록 |
| 반복 일정의 회차들이 Meet 링크 하나를 공유하는지 | 5단계. 반복 일정 생성 후 `instances`의 `conferenceData` 비교 |
| `spaces.create`로 만든 공간을 `conferenceData`(`conferenceId` + `entryPoints`)로 수동으로 붙이면 받아주는지(`signature` 포함) | 5단계에서 1회 시도. 권고상 쓰지 않을 경로라 우선순위 낮음 |
| Calendar가 만든 Meet 공간을 `meetings.space.created`로 `get`·`endActiveConference` 할 수 있는지 | Meet 3단계와 함께. 문서는 "다른 앱 공간"으로 분류 |
| `sendUpdates` 생략 시 실제 기본 동작(메일 발송 여부) | 5단계. koreaji8을 참석자로 넣어 확인 |
| 받는 사람 "초대 자동 추가" 설정의 기본값, 교수와 처음 연락하는 학생에게 일정이 바로 뜨는지 | 5단계. koreaji8로 확인 |
| `events.watch` 최대 TTL | 웹훅을 쓰기로 하면 5단계. 큰 `ttl`을 넣고 응답 `expiration` 확인 |
| 개인 Gmail의 Calendar 사용 한도 수치 | 비공개. 수업 규모에선 보류 |
| 새 쿼터 등급 모델(2026-05-01~)의 실제 수치 | 3단계. 콘솔 쿼터 페이지 |
| "이후 모든 회차" 변경의 공식 절차 | 반복 수업 유즈케이스가 확정되면 5단계 |
| 2026년 과금 세부 | 핸드오프 직전 재확인(Google 공통) |

## 출처 (2026-10-06 확인)

- API 개요·개념(일정·캘린더, 시간대) — https://developers.google.com/workspace/calendar/api/concepts/events-calendars
- Events 리소스 — https://developers.google.com/workspace/calendar/api/v3/reference/events ; insert · list · patch · watch · move — 같은 경로 `/insert`, `/list`, `/patch`, `/watch`, `/move`
- Calendars 리소스 — https://developers.google.com/workspace/calendar/api/v3/reference/calendars ; insert · delete — `/insert`, `/delete`
- ACL · CalendarList · Freebusy — https://developers.google.com/workspace/calendar/api/v3/reference/acl , …/calendarList , …/freebusy
- 일정 만들기(conferenceData, 비동기, 복사) — https://developers.google.com/workspace/calendar/api/guides/create-events
- 참석자 초대 — https://developers.google.com/workspace/calendar/api/concepts/inviting-attendees-to-events
- 반복 일정 — https://developers.google.com/workspace/calendar/api/guides/recurringevents
- 확장 속성 — https://developers.google.com/workspace/calendar/api/guides/extended-properties
- 일정 유형 — https://developers.google.com/workspace/calendar/api/guides/event-types
- 푸시 알림 — https://developers.google.com/workspace/calendar/api/guides/push ; 동기화(syncToken) — https://developers.google.com/workspace/calendar/api/guides/sync
- 쿼터 — https://developers.google.com/workspace/calendar/api/guides/quota ; 에러 — https://developers.google.com/workspace/calendar/api/guides/errors
- scope — https://developers.google.com/workspace/calendar/api/auth ; scope 민감도 표시 — https://developers.google.com/identity/protocols/oauth2/scopes , https://developers.google.com/identity/protocols/oauth2/production-readiness/sensitive-scope-verification
- 릴리스 노트(2026-02-17 Meet 재사용 금지, 2025-10-27 데이터 소유자, 2026-05-01 쿼터 등급) — https://developers.google.com/workspace/calendar/release-notes
- Calendar 사용 한도 — https://knowledge.workspace.google.com/admin/calendar/avoid-calendar-use-limits
- 외부 초대 응답 — https://support.google.com/calendar/answer/37161 ; 초대 자동 추가 설정 — https://support.google.com/calendar/answer/13159188 ; 게스트 수 — https://support.google.com/calendar/answer/172013
- Meet: Calendar가 만든 공간의 scope 구분 — https://developers.google.com/workspace/meet/api/guides/meeting-spaces-overview ; Calendar 공간 자동 산출물 — https://developers.google.com/workspace/meet/api/guides/meeting-spaces-configuration ; 무료 시간 제한 — https://support.google.com/meet/answer/7317473
- Workspace Events API 지원 대상(Calendar 없음) — https://developers.google.com/workspace/events/guides
