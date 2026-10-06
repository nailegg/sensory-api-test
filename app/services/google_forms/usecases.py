"""Forms 시나리오 흐름. 여러 client와 mapper를 엮는다. FastAPI를 import하지 않는다.

유즈케이스(docs/google_forms.md 1절, 2026-10-06 확정 13개):
1·2 설문·퀴즈 생성 → create_form            3 조별 동료평가 폼 → create_group_forms
4 기존 폼 복사 → create_form_from_template   5 응답자 제한 → restrict_responders
6 제출 현황 → get_submission_status          7·8 마감·재개·열기 → close_form / reopen_form / open_form
9 응답 수집·집계 → collect_responses / summarize_responses
10 퀴즈 점수 → collect_quiz_scores           11 동료평가 집계 → collect_peer_reviews
12 CSV·xlsx → export_responses               13 시트로 내보내기 → export_responses_to_sheet
결과의 원본은 Synsory DB다. 9~12는 Synsory로 가져오는 데까지, 13은 교수자 Drive에 쓰는 한 방향 사본이다.
"""

import csv
import io
from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

from app.core.models import AnswerGrade, Document, FormSubmission
from app.services.google_drive.client import MIME_FORM, DriveApiError, DriveClient
from app.services.google_drive.usecases import ExportedFile, render_template
from app.services.google_forms.client import FormsApiError, FormsClient
from app.services.google_forms.mapper import (
    document_from_form,
    graded_questions,
    publish_state,
    question_ids,
    question_specs,
    submission_from_response,
)

EMAIL_COLLECTION_TYPES = {"DO_NOT_COLLECT", "VERIFIED", "RESPONDER_INPUT"}


@dataclass
class FormInfo:
    document: Document
    responder_url: str | None  # 학생에게 줄 링크(/viewform). document.url은 편집 화면이다
    published: bool | None
    accepting_responses: bool | None
    email_collection: str | None
    is_quiz: bool
    linked_sheet_id: str | None
    question_ids: dict[str, str] = field(default_factory=dict)  # questionId → 질문 제목. 응답 해석용으로 저장한다
    revision_id: str | None = None
    questions: list[dict] = field(default_factory=list)  # mapper.question_specs: id·title·kind·options·point_value. 함께 저장해 두면 forms.get 없이 응답을 해석한다


def _form_info(form: dict, drive_file: dict) -> FormInfo:
    settings = form.get("settings") or {}
    state = publish_state(form)
    return FormInfo(
        document=document_from_form(form, drive_file),
        responder_url=form.get("responderUri"),
        published=state["published"],
        accepting_responses=state["accepting_responses"],
        email_collection=settings.get("emailCollectionType"),
        is_quiz=bool((settings.get("quizSettings") or {}).get("isQuiz", False)),
        linked_sheet_id=form.get("linkedSheetId"),
        question_ids=question_ids(form),
        revision_id=form.get("revisionId"),
        questions=question_specs(form),
    )


async def read_form(forms: FormsClient, drive: DriveClient, form_id: str) -> FormInfo:
    form = await forms.get(form_id)
    drive_file = await drive.get_file(form_id)
    return _form_info(form, drive_file)


def build_setup_requests(
    description: str | None = None,
    items: list[dict] | None = None,
    email_collection: str | None = None,
    quiz: bool = False,
) -> list[dict]:
    """create 직후 보낼 batchUpdate 요청 배열. 순서: 설정(퀴즈가 grading보다 먼저) → 설명 → 질문(인덱스 0부터 차례로)."""
    requests: list[dict] = []
    settings: dict = {}
    masks: list[str] = []
    if quiz:
        settings["quizSettings"] = {"isQuiz": True}
        masks.append("quizSettings.isQuiz")
    if email_collection:
        if email_collection not in EMAIL_COLLECTION_TYPES:
            raise ValueError(f"email_collection은 {sorted(EMAIL_COLLECTION_TYPES)} 중 하나")
        settings["emailCollectionType"] = email_collection
        masks.append("emailCollectionType")
    if settings:
        requests.append({"updateSettings": {"settings": settings, "updateMask": ",".join(masks)}})
    if description:
        requests.append({"updateFormInfo": {"info": {"description": description}, "updateMask": "description"}})
    for i, item in enumerate(items or []):
        requests.append({"createItem": {"item": item, "location": {"index": i}}})
    return requests


async def create_form(
    forms: FormsClient,
    drive: DriveClient,
    title: str,
    folder_id: str | None = None,
    description: str | None = None,
    items: list[dict] | None = None,
    email_collection: str | None = None,
    quiz: bool = False,
    publish: bool = True,
) -> FormInfo:
    """유즈케이스 1·2·8. create → batchUpdate 1회(설정+설명+질문) → (publish면) setPublishSettings → 폴더 이동 → FormInfo.
    질문을 다 넣은 뒤 게시해야 학생이 미완성 폼을 보지 않는다. publish=False는 8번(수업 시각에 열기)용.
    질문 추가가 실패하면 빈 폼을 휴지통으로 보내고 FormsApiError를 올린다.
    응답자 제한(5)은 하지 않는다. 만들어진 폼에는 "링크가 있는 모든 사용자" 응답자 권한이 자동으로 붙어 있다."""
    requests = build_setup_requests(description, items, email_collection, quiz)  # 잘못된 입력은 생성 전에 거른다
    # forms.create는 파라미터 없이 부르면 게시·응답 받기 상태로 만들어진다(2026-10-06 실측, 공식 문서와 다름).
    # 질문을 넣기 전에 학생이 링크로 들어오지 않도록 항상 미게시로 만들고, 다 넣은 뒤 게시한다.
    form = await forms.create(title, document_title=title, unpublished=True)
    form_id = form["formId"]
    try:
        if requests:
            await forms.batch_update(form_id, requests)
    except FormsApiError:
        # batchUpdate는 원자적이라 질문이 하나도 안 들어간 빈 폼이 남는다. 지우고 에러를 올린다.
        await drive.trash_file(form_id)
        raise
    if publish:
        await forms.set_publish_settings(form_id, is_published=True, is_accepting_responses=True)
    if folder_id:
        await drive.move_file(form_id, to_folder_id=folder_id)
    return await read_form(forms, drive, form_id)


async def set_publish_state(
    forms: FormsClient, drive: DriveClient, form_id: str, published: bool, accepting_responses: bool
) -> FormInfo:
    """유즈케이스 7·8. 마감 = (True, False), 재개·열기 = (True, True), 게시 취소 = (False, False)."""
    await forms.set_publish_settings(form_id, is_published=published, is_accepting_responses=accepting_responses)
    return await read_form(forms, drive, form_id)


ANYONE_WITH_LINK_PERMISSION_ID = "anyoneWithLink"  # 생성 시 자동으로 붙는 응답자 권한의 고정 id


@dataclass
class ResponderResult:
    email: str | None  # None = 링크가 있는 모든 사용자
    ok: bool
    permission: dict | None = None
    error: str | None = None


async def restrict_responders(
    drive: DriveClient, form_id: str, emails: list[str], remove_link_access: bool = True
) -> list[ResponderResult]:
    """유즈케이스 5. 학생마다 Drive permissions.create(role=reader, view=published) → "링크가 있는 모든 사용자" 권한 삭제.

    폼은 만들 때 anyoneWithLink 응답자 권한이 자동으로 붙고, 이게 남아 있으면 학생을 추가해도 누구나 응답할 수 있다
    (2026-10-06 실측). 그래서 기본으로 지운다. 한 명도 추가하지 못했으면 지우지 않는다(아무도 응답 못 하는 폼 방지).
    이메일 단위로 부분 실패해도 계속하고, 마지막 원소로 링크 권한 삭제 결과(email=None)를 붙인다.
    """
    results: list[ResponderResult] = []
    for email in emails:
        try:
            results.append(ResponderResult(email, True, await drive.share_as_responder(form_id, email)))
        except DriveApiError as e:
            results.append(ResponderResult(email, False, error=f"{e.status} {e.reason}: {e.message}"))
    if remove_link_access and any(r.ok for r in results):
        try:
            await drive.delete_permission(form_id, ANYONE_WITH_LINK_PERMISSION_ID)
            results.append(ResponderResult(None, True, {"removed": ANYONE_WITH_LINK_PERMISSION_ID}))
        except DriveApiError as e:
            if e.status == 404:  # 이미 지워진 경우. 재실행 안전
                results.append(ResponderResult(None, True, {"removed": None}))
            else:
                results.append(ResponderResult(None, False, error=f"{e.status} {e.reason}: {e.message}"))
    return results


async def allow_anyone_with_link(drive: DriveClient, form_id: str) -> dict:
    """응답자 = 링크가 있는 모든 사용자. permissions.create(type=anyone, role=reader, view=published)."""
    return await drive.share_as_responder(form_id, None)


async def remove_anyone_with_link(drive: DriveClient, form_id: str) -> None:
    """"링크가 있는 모든 사용자" 응답자 권한 삭제. 폼은 생성 시 이 권한이 자동으로 붙는다(2026-10-06 실측)."""
    await drive.delete_permission(form_id, ANYONE_WITH_LINK_PERMISSION_ID)


async def update_settings(forms: FormsClient, drive: DriveClient, form_id: str, email_collection: str | None = None, quiz: bool | None = None) -> FormInfo:
    """생성 후 설정 변경(이메일 수집 방식, 퀴즈 여부). 퀴즈를 False로 바꾸면 모든 문항의 grading이 삭제된다."""
    settings: dict = {}
    masks: list[str] = []
    if quiz is not None:
        settings["quizSettings"] = {"isQuiz": quiz}
        masks.append("quizSettings.isQuiz")
    if email_collection:
        if email_collection not in EMAIL_COLLECTION_TYPES:
            raise ValueError(f"email_collection은 {sorted(EMAIL_COLLECTION_TYPES)} 중 하나")
        settings["emailCollectionType"] = email_collection
        masks.append("emailCollectionType")
    if settings:
        await forms.batch_update(form_id, [{"updateSettings": {"settings": settings, "updateMask": ",".join(masks)}}])
    return await read_form(forms, drive, form_id)


async def list_permissions(drive: DriveClient, form_id: str) -> dict[str, list[dict]]:
    """응답자(view=published)와 그 외(소유자·편집자)를 나눠 돌려준다."""
    perms = await drive.list_permissions(form_id, include_published_view=True)
    return {
        "responders": [p for p in perms if p.get("view") == "published"],
        "others": [p for p in perms if p.get("view") != "published"],
    }


async def copy_form(forms: FormsClient, drive: DriveClient, form_id: str, name: str, folder_id: str | None = None) -> FormInfo:
    """유즈케이스 4의 뒷부분. Drive files.copy → 복사본 FormInfo(게시 상태·질문 ID 확인용). 원본은 수정하지 않는다."""
    copied = await drive.copy_file(form_id, name, folder_id)
    return await read_form(forms, drive, copied["id"])


# ---------- 유즈케이스 7·8: 열기·마감·재개 ----------


async def open_form(forms: FormsClient, drive: DriveClient, form_id: str) -> FormInfo:
    """8. 미리 만들어 둔(publish=False) 폼을 수업 시각에 연다. 게시 + 응답 받기."""
    return await set_publish_state(forms, drive, form_id, published=True, accepting_responses=True)


async def close_form(forms: FormsClient, drive: DriveClient, form_id: str) -> FormInfo:
    """7·8. 마감. 게시는 유지하고 응답 받기만 끈다. 학생이 링크를 열면 '더 이상 응답을 받지 않습니다'. 재실행 안전."""
    return await set_publish_state(forms, drive, form_id, published=True, accepting_responses=False)


async def reopen_form(forms: FormsClient, drive: DriveClient, form_id: str) -> FormInfo:
    """7. 마감 연장. 폼 단위라 학생 개인별 연장은 안 된다."""
    return await open_form(forms, drive, form_id)


# ---------- 유즈케이스 3: 조별 동료평가 폼 ----------


@dataclass
class Member:
    name: str  # 격자 행 제목으로 보인다
    email: str  # 응답자 권한·자기 평가 판별에 쓴다


@dataclass
class PeerGroup:
    team_name: str
    members: list[Member]


@dataclass
class GroupFormResult:
    team_name: str
    form: FormInfo | None = None
    responders: list[ResponderResult] = field(default_factory=list)
    reviewees: dict[str, str] = field(default_factory=dict)  # 격자 행 질문 ID → 피평가자 이메일. 11번 집계에 쓰므로 저장한다
    error: str | None = None


def member_labels(members: list[Member]) -> list[str]:
    """격자 행 제목. 같은 이름이 있으면 이메일 앞부분을 붙여 구분한다(행 제목이 같으면 응답을 구분할 수 없다)."""
    names = [m.name for m in members]
    return [m.name if names.count(m.name) == 1 else f"{m.name} ({m.email.split('@')[0]})" for m in members]


def peer_review_items(members: list[Member], criteria: list[str], scale: list[str]) -> list[dict]:
    """평가 항목마다 격자 질문 하나: 행 = 조원, 열 = 척도(단일 선택). 모든 행 필수."""
    labels = member_labels(members)
    return [
        {
            "title": criterion,
            "questionGroupItem": {
                "grid": {"columns": {"type": "RADIO", "options": [{"value": v} for v in scale]}},
                "questions": [{"required": True, "rowQuestion": {"title": label}} for label in labels],
            },
        }
        for criterion in criteria
    ]


async def create_group_forms(
    forms: FormsClient,
    drive: DriveClient,
    folder_id: str,
    activity_name: str,
    groups: list[PeerGroup],
    criteria: list[str],
    scale: list[str] | None = None,
    title_template: str = "{{activity_name}} 동료평가 - {{team_name}}",
    description: str | None = None,
    extra_items: list[dict] | None = None,
) -> list[GroupFormResult]:
    """3. 조마다 동료평가 폼(방식 A): create_form(VERIFIED, 게시) → restrict_responders(조원만). 그룹 단위로 부분 실패해도 계속.

    응답자 제한을 먼저 걸고 싶어도 게시 전에는 의미가 없고, 게시와 제한 사이 몇 초 동안 링크가 열려 있다.
    링크를 학생에게 보내기 전이라 실무상 문제는 없다. 링크는 반드시 이 함수가 끝난 뒤에 보낸다.
    """
    scale = scale or ["1", "2", "3", "4", "5"]
    results: list[GroupFormResult] = []
    for g in groups:
        variables = {"activity_name": activity_name, "team_name": g.team_name}
        result = GroupFormResult(team_name=g.team_name)
        try:
            items = peer_review_items(g.members, criteria, scale) + list(extra_items or [])
            info = await create_form(
                forms, drive, render_template(title_template, variables), folder_id=folder_id,
                description=render_template(description, variables) if description else None,
                items=items, email_collection="VERIFIED", publish=True,
            )
            result.form = info
            label_to_email = dict(zip(member_labels(g.members), (m.email for m in g.members)))
            result.reviewees = {
                q["id"]: label_to_email[q["row_title"]]
                for q in info.questions
                if q["kind"] == "grid_row" and q.get("group_title") in criteria and q.get("row_title") in label_to_email
            }
            result.responders = await restrict_responders(drive, info.document.id, [m.email for m in g.members])
        except (FormsApiError, DriveApiError) as e:
            result.error = str(e)
        results.append(result)
    return results


# ---------- 유즈케이스 9: 응답 수집·집계 ----------


@dataclass
class CollectResult:
    form_id: str
    submissions: list[FormSubmission]
    cursor: str | None  # 다음 증분 조회에 넘길 값(가장 늦은 lastSubmittedTime, RFC3339 원문). 응답이 없으면 since 그대로


async def _list_all_responses(forms: FormsClient, form_id: str, filter: str | None = None, fields: str | None = None) -> list[dict]:
    """responses.list 전 페이지(pageSize 5000). expensive read 쿼터라 페이지마다 1회씩 든다."""
    out: list[dict] = []
    token: str | None = None
    while True:
        page = await forms.list_responses(form_id, filter=filter, page_token=token, fields=fields)
        out.extend(page.get("responses", []))
        token = page.get("nextPageToken")
        if not token:
            return out


async def collect_responses(
    forms: FormsClient, form_id: str, since: str | None = None, graded: dict[str, float] | None = None
) -> CollectResult:
    """9. 응답을 FormSubmission으로. since를 주면 `timestamp >= since` 증분 조회.
    `>=`라 경계의 응답이 다시 올 수 있으므로 저장할 때 submission.id로 멱등 처리한다.
    graded(채점 대상 질문 ID → 배점)를 주면 틀린 문항도 0점으로 grades에 들어간다."""
    raw = await _list_all_responses(forms, form_id, filter=f"timestamp >= {since}" if since else None)
    subs = [submission_from_response(r, form_id, graded) for r in raw]
    subs.sort(key=lambda x: (x.submitted_at is None, x.submitted_at))
    times = [r.get("lastSubmittedTime") for r in raw if r.get("lastSubmittedTime")]
    return CollectResult(form_id=form_id, submissions=subs, cursor=max(times) if times else since)


@dataclass
class QuestionSummary:
    id: str
    title: str
    kind: str
    response_count: int  # 이 질문에 답한 응답 수
    counts: dict[str, int] = field(default_factory=dict)  # 선택지·척도 값 → 선택 수(선택지 순서, 0 포함)
    other_answers: list[str] = field(default_factory=list)  # 객관식 '기타'에 쓴 문구
    average: float | None = None  # 척도·별점·숫자형 격자
    text_answers: list[str] = field(default_factory=list)  # 단답·장문·날짜·시간


_COUNTED = {"choice_radio", "choice_checkbox", "choice_drop_down", "scale", "rating", "grid_row"}
_NUMERIC = {"scale", "rating", "grid_row"}


def summarize(questions: list[dict], submissions: list[FormSubmission]) -> list[QuestionSummary]:
    """문항별 집계(순수 함수). questions는 FormInfo.questions(저장본)."""
    out: list[QuestionSummary] = []
    for q in questions:
        values = [v for s in submissions for v in s.answers.get(q["id"], [])]
        summary = QuestionSummary(
            id=q["id"], title=q["title"], kind=q["kind"],
            response_count=sum(1 for s in submissions if s.answers.get(q["id"])),
        )
        if q["kind"] in _COUNTED:
            known = [o for o in q.get("options", []) if o != "(기타)"]
            summary.counts = {o: 0 for o in known}
            for v in values:
                if v in summary.counts:
                    summary.counts[v] += 1
                else:
                    summary.counts["(기타)"] = summary.counts.get("(기타)", 0) + 1
                    summary.other_answers.append(v)
            if q["kind"] in _NUMERIC:
                nums = [float(v) for v in values if _is_number(v)]
                summary.average = round(sum(nums) / len(nums), 3) if nums else None
        else:
            summary.text_answers = values
        out.append(summary)
    return out


def _is_number(v: str) -> bool:
    try:
        float(v)
        return True
    except ValueError:
        return False


async def summarize_responses(forms: FormsClient, form_id: str) -> list[QuestionSummary]:
    """9. forms.get 1 + responses.list 1 → 문항별 집계. 저장해 둔 FormInfo.questions가 있으면 summarize()를 직접 쓴다."""
    form = await forms.get(form_id)
    collected = await collect_responses(forms, form_id)
    return summarize(question_specs(form), collected.submissions)


# ---------- 유즈케이스 6: 제출 현황 ----------


@dataclass
class SubmissionStatus:
    form_id: str
    submitted: list[str]  # 명단 중 제출한 이메일
    missing: list[str]  # 명단 중 미제출 → Synsory가 독촉 알림
    not_in_roster: list[str]  # 명단에 없는데 제출한 이메일(응답자 제한을 안 걸었거나 소유자·조교)
    without_email: int  # 이메일 없이 들어온 응답 수(이메일 수집을 안 켠 폼)
    resubmitted: dict[str, int] = field(default_factory=dict)  # 같은 이메일로 2건 이상(응답 1회 제한은 UI 설정이라 API로 못 막는다)


async def get_submission_status(forms: FormsClient, form_id: str, roster_emails: list[str]) -> SubmissionStatus:
    """6. responses.list(필요한 필드만) → 명단과 대조. 이메일은 대소문자 무시."""
    raw = await _list_all_responses(forms, form_id, fields="responses(responseId,respondentEmail,lastSubmittedTime),nextPageToken")
    counts: dict[str, int] = {}
    without_email = 0
    for r in raw:
        email = (r.get("respondentEmail") or "").strip().lower()
        if email:
            counts[email] = counts.get(email, 0) + 1
        else:
            without_email += 1
    roster = [e.strip().lower() for e in roster_emails]
    return SubmissionStatus(
        form_id=form_id,
        submitted=[e for e in roster if e in counts],
        missing=[e for e in roster if e not in counts],
        not_in_roster=sorted(e for e in counts if e not in roster),
        without_email=without_email,
        resubmitted={e: n for e, n in counts.items() if n > 1},
    )


# ---------- 유즈케이스 10: 퀴즈 점수 ----------


@dataclass
class QuizScore:
    response_id: str
    respondent_email: str | None
    submitted_at: datetime | None
    total_score: float  # 자동 채점 + 교수자가 UI에서 고친 점수
    max_score: float  # 채점 문항 배점 합
    grades: dict[str, AnswerGrade]


async def collect_quiz_scores(forms: FormsClient, form_id: str) -> list[QuizScore]:
    """10. forms.get(배점) + responses.list **필터 없이 전체**. lastSubmittedTime은 채점 변경을 반영하지 않아
    증분 조회로는 교수자가 고친 점수를 놓친다. 점수 반영(성적 DB)은 호출자 책임."""
    form = await forms.get(form_id)
    graded = graded_questions(form)
    collected = await collect_responses(forms, form_id, graded=graded)
    max_score = sum(graded.values())
    return [
        QuizScore(
            response_id=s.id, respondent_email=s.respondent_email, submitted_at=s.submitted_at,
            total_score=s.total_score or 0.0, max_score=max_score, grades=s.grades,
        )
        for s in collected.submissions
    ]


# ---------- 유즈케이스 11: 동료평가 집계 ----------


@dataclass
class PeerScore:
    reviewee: str  # 피평가자 이메일(reviewees를 준 경우) 또는 격자 행 제목
    criterion: str  # 평가 항목(격자 질문 제목). "(전체)"는 항목 평균의 평균이 아니라 모든 점수의 평균
    average: float | None
    count: int  # 반영된 평가 수
    self_excluded: int = 0  # 자기 평가라 뺀 수


def summarize_peer_reviews(
    questions: list[dict], submissions: list[FormSubmission], reviewees: dict[str, str] | None = None, exclude_self: bool = True
) -> list[PeerScore]:
    """11. 격자 행 질문 → 피평가자, 열 값 → 점수(숫자만). 순수 함수.
    reviewees(행 질문 ID → 이메일, create_group_forms 결과)를 주면 평가자 이메일과 비교해 자기 평가를 뺄 수 있다."""
    scores: dict[tuple[str, str], list[float]] = {}
    excluded: dict[tuple[str, str], int] = {}
    for q in questions:
        if q["kind"] != "grid_row":
            continue
        reviewee = (reviewees or {}).get(q["id"], q.get("row_title") or q["title"])
        key = (reviewee, q.get("group_title") or q["title"])
        scores.setdefault(key, [])
        for s in submissions:
            for v in s.answers.get(q["id"], []):
                if not _is_number(v):
                    continue
                if exclude_self and reviewees and s.respondent_email and s.respondent_email.lower() == reviewee.lower():
                    excluded[key] = excluded.get(key, 0) + 1
                    continue
                scores[key].append(float(v))
    out: list[PeerScore] = []
    for (reviewee, criterion), vals in scores.items():
        out.append(PeerScore(reviewee, criterion, round(sum(vals) / len(vals), 3) if vals else None, len(vals), excluded.get((reviewee, criterion), 0)))
    for reviewee in dict.fromkeys(r for r, _ in scores):
        vals = [v for (r, _), vs in scores.items() if r == reviewee for v in vs]
        ex = sum(n for (r, _), n in excluded.items() if r == reviewee)
        out.append(PeerScore(reviewee, "(전체)", round(sum(vals) / len(vals), 3) if vals else None, len(vals), ex))
    return out


async def collect_peer_reviews(
    forms: FormsClient, form_id: str, reviewees: dict[str, str] | None = None, exclude_self: bool = True
) -> list[PeerScore]:
    """11. forms.get 1 + responses.list 1 → summarize_peer_reviews. 조마다 폼이면 폼마다 호출한다."""
    form = await forms.get(form_id)
    collected = await collect_responses(forms, form_id)
    return summarize_peer_reviews(question_specs(form), collected.submissions, reviewees, exclude_self)


# ---------- 유즈케이스 12·13: 표로 펴기, 파일·시트로 내보내기 ----------


def response_table(
    questions: list[dict], submissions: list[FormSubmission], tz: str = "Asia/Seoul", include_email: bool = True
) -> list[list[str]]:
    """헤더 + 응답 행(모두 문자열). 열: 제출 시각, 이메일, 점수(퀴즈일 때), 질문별 한 열.
    체크박스는 ", "로 잇고 격자는 행마다 한 열("질문 [행]"). 파일 업로드는 Drive 파일 ID를 잇는다."""
    is_quiz = any(q.get("point_value") is not None for q in questions)
    zone = ZoneInfo(tz)
    header = ["제출 시각"] + (["이메일"] if include_email else []) + (["점수"] if is_quiz else []) + [q["title"] for q in questions]
    rows = [header]
    for s in submissions:
        when = s.submitted_at.astimezone(zone).strftime("%Y-%m-%d %H:%M:%S") if s.submitted_at else ""
        row = [when]
        if include_email:
            row.append(s.respondent_email or "")
        if is_quiz:
            row.append("" if s.total_score is None else f"{s.total_score:g}")
        for q in questions:
            row.append(", ".join(s.answers.get(q["id"], []) or s.file_ids.get(q["id"], [])))
        rows.append(row)
    return rows


async def export_responses(forms: FormsClient, form_id: str, fmt: str = "csv", tz: str = "Asia/Seoul") -> ExportedFile:
    """12. responses.list → Synsory 서버가 CSV·xlsx를 만든다(Google 내보내기 아님. 폼은 Drive 내보내기 불가).
    CSV는 Excel 한글 깨짐 방지로 UTF-8 BOM. xlsx는 모든 셀을 텍스트로 넣어 학번 앞자리 0을 지킨다."""
    form = await forms.get(form_id)
    collected = await collect_responses(forms, form_id)
    table = response_table(question_specs(form), collected.submissions, tz)
    base = (form.get("info") or {}).get("title") or form_id
    if fmt == "csv":
        buf = io.StringIO()
        csv.writer(buf).writerows(table)
        return ExportedFile(form_id, f"{base} 응답.csv", "text/csv", buf.getvalue().encode("utf-8-sig"))
    if fmt == "xlsx":
        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        ws.title = "응답"
        for row in table:
            ws.append(row)
        for col in ws.iter_cols():
            for cell in col:
                cell.number_format = "@"
        ws.freeze_panes = "A2"
        out = io.BytesIO()
        wb.save(out)
        return ExportedFile(form_id, f"{base} 응답.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", out.getvalue())
    raise ValueError("fmt는 csv | xlsx")


@dataclass
class SheetExportResult:
    spreadsheet_id: str
    sheet_title: str
    rows_written: int  # 헤더 제외
    columns: int
    created: bool  # 이번에 새로 만들었는지. 처음이면 spreadsheet_id를 폼 ID와 함께 저장한다
    spreadsheet: Document | None = None


async def export_responses_to_sheet(
    forms: FormsClient,
    drive: DriveClient,
    sheets,  # google_sheets.client.SheetsClient
    form_id: str,
    spreadsheet_id: str | None = None,
    folder_id: str | None = None,
    title: str | None = None,
    previous_columns: int | None = None,
    tz: str = "Asia/Seoul",
) -> SheetExportResult:
    """13. 응답을 교수자 Drive의 스프레드시트로(한 방향 사본, 동기화 아님).
    처음: Sheets create(시트 "응답") + Drive 폴더 이동 → values.update 1(RAW).
    다시: 첫 시트 이름 확인(spreadsheets.get) → Synsory가 쓴 열 범위만 values.clear → values.update.
    지울 범위는 max(이번 열 수, previous_columns)다. previous_columns는 지난번 결과의 columns를 서비스가 저장해 두고 넘긴다.
    1행 너비로 추정하지 않는 이유: 교수자가 오른쪽에 덧붙인 메모 열까지 지우게 된다."""
    from app.services.google_sheets import usecases as sheets_uc
    from app.services.google_sheets.mapper import a1, column_letter

    form = await forms.get(form_id)
    collected = await collect_responses(forms, form_id)
    table = response_table(question_specs(form), collected.submissions, tz)
    width = len(table[0])
    created = spreadsheet_id is None
    document: Document | None = None
    if created:
        name = title or f"{(form.get('info') or {}).get('title') or form_id} 응답"
        document = await sheets_uc.create_empty_spreadsheet(sheets, drive, name, folder_id, sheet_names=["응답"])
        spreadsheet_id = document.id
        sheet_title = "응답"
    else:
        sheet_title = (await sheets_uc.list_sheets(sheets, spreadsheet_id))[0].title
        clear_width = max(width, previous_columns or 0)
        await sheets.clear_values(spreadsheet_id, a1(sheet_title, f"A:{column_letter(clear_width - 1)}"))
    await sheets_uc.write_values(sheets, spreadsheet_id, sheet_title, "A1", table)
    return SheetExportResult(spreadsheet_id, sheet_title, len(table) - 1, width, created, document)


# ---------- 유즈케이스 4: 기존 폼(앱이 만든 것 또는 Picker로 고른 것)을 템플릿으로 ----------


@dataclass
class TemplateCopyResult:
    form: FormInfo
    responders: list[ResponderResult] = field(default_factory=list)


async def create_form_from_template(
    forms: FormsClient,
    drive: DriveClient,
    template_form_id: str,
    name: str,
    folder_id: str | None = None,
    title: str | None = None,
    responder_emails: list[str] | None = None,
    publish: bool = True,
) -> TemplateCopyResult:
    """4. Drive files.copy → (title이면) updateFormInfo → 게시 → (responder_emails면) 응답자 제한.
    원본은 수정하지 않는다. 복사본은 미게시·응답자 제한 없음·응답 0건으로 생기고 질문 ID는 원본과 같다(2026-10-06 실측).
    교수자가 Forms UI에서 만든 폼은 Picker로 고른 뒤에만 복사할 수 있다(고르기 전 404)."""
    copied = await drive.copy_file(template_form_id, name, folder_id)
    form_id = copied["id"]
    if title:
        await forms.batch_update(form_id, [{"updateFormInfo": {"info": {"title": title}, "updateMask": "title"}}])
    if publish:
        await forms.set_publish_settings(form_id, is_published=True, is_accepting_responses=True)
    responders = await restrict_responders(drive, form_id, responder_emails) if responder_emails else []
    return TemplateCopyResult(await read_form(forms, drive, form_id), responders)


# ---------- 12절 실측용 배관 ----------


async def create_raw(forms: FormsClient, title: str, unpublished: bool | None = None) -> dict:
    """forms.create만 호출하고 응답을 그대로 돌려준다. 기본 게시 상태·unpublished 파라미터 효과 확인용."""
    return await forms.create(title, document_title=title, unpublished=unpublished)


async def create_via_drive(forms: FormsClient, drive: DriveClient, title: str, folder_id: str | None = None) -> FormInfo:
    """Drive files.create(mimeType=form, parents)로 폴더 안에 바로 만들 수 있는지 확인용."""
    created = await drive.create_empty_native_file(title, MIME_FORM, folder_id)
    return await read_form(forms, drive, created["id"])
