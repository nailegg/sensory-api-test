"""Forms 응답 dict (+ Drive 메타데이터) → core/models 순수 변환. 네트워크 호출도 client import도 없다."""

from app.core.models import AnswerGrade, Document, FormSubmission
from app.services.google_drive.mapper import document_from_drive_file


def document_from_form(form: dict, drive_file: dict) -> Document:
    """forms.get + Drive files.get → Document(kind=form).
    title은 응답자에게 보이는 info.title 우선. url은 Drive webViewLink(편집 화면)이고 응답 링크(responderUri)가 아니다."""
    doc = document_from_drive_file(drive_file)
    title = (form.get("info") or {}).get("title")
    if title:
        doc.title = title
    return doc


def publish_state(form: dict) -> dict:
    """publishSettings.publishState → {published, accepting_responses}. 레거시 폼은 publishSettings가 없어 None."""
    state = (form.get("publishSettings") or {}).get("publishState")
    if state is None:
        return {"published": None, "accepting_responses": None}
    return {
        "published": bool(state.get("isPublished", False)),
        "accepting_responses": bool(state.get("isAcceptingResponses", False)),
    }


def question_ids(form: dict) -> dict[str, str]:
    """items[] → {questionId: 질문 제목}. 격자 질문은 행마다 "제목 [행]"."""
    out: dict[str, str] = {}
    for item in form.get("items") or []:
        title = item.get("title", "")
        if "questionItem" in item:
            qid = item["questionItem"]["question"].get("questionId")
            if qid:
                out[qid] = title
        elif "questionGroupItem" in item:
            for q in item["questionGroupItem"].get("questions") or []:
                row = (q.get("rowQuestion") or {}).get("title", "")
                if q.get("questionId"):
                    out[q["questionId"]] = f"{title} [{row}]" if row else title
    return out


def question_specs(form: dict) -> list[dict]:
    """items[] → 질문 목록(폼 순서). 각 원소: id, title, kind, options, point_value.
    kind: choice_radio | choice_checkbox | choice_drop_down | text | paragraph | scale | rating | date | time | grid_row | file_upload.
    격자 질문은 행마다 하나(kind=grid_row, title="질문 [행]", options=열 값)."""
    specs: list[dict] = []
    for item in form.get("items") or []:
        title = item.get("title", "")
        if "questionItem" in item:
            q = item["questionItem"].get("question", {})
            kind, options = _question_kind(q)
            specs.append({
                "id": q.get("questionId"), "title": title, "kind": kind, "options": options,
                "point_value": (q.get("grading") or {}).get("pointValue"),
            })
        elif "questionGroupItem" in item:
            group = item["questionGroupItem"]
            columns = [o.get("value", "") for o in ((group.get("grid") or {}).get("columns") or {}).get("options", [])]
            for q in group.get("questions") or []:
                row = (q.get("rowQuestion") or {}).get("title", "")
                specs.append({
                    "id": q.get("questionId"), "title": f"{title} [{row}]" if row else title, "kind": "grid_row",
                    "options": columns, "point_value": None, "group_title": title, "row_title": row,
                })
    return [s for s in specs if s["id"]]


def _question_kind(q: dict) -> tuple[str, list[str]]:
    if "choiceQuestion" in q:
        c = q["choiceQuestion"]
        opts = ["(기타)" if o.get("isOther") else o.get("value", "") for o in c.get("options", [])]
        return f"choice_{c.get('type', 'RADIO').lower()}", opts
    if "textQuestion" in q:
        return ("paragraph" if q["textQuestion"].get("paragraph") else "text"), []
    if "scaleQuestion" in q:
        s = q["scaleQuestion"]
        return "scale", [str(v) for v in range(int(s.get("low", 1)), int(s.get("high", 5)) + 1)]
    if "ratingQuestion" in q:
        return "rating", [str(v) for v in range(1, int(q["ratingQuestion"].get("ratingScaleLevel", 5)) + 1)]
    for key, kind in (("dateQuestion", "date"), ("timeQuestion", "time"), ("fileUploadQuestion", "file_upload")):
        if key in q:
            return kind, []
    return "unknown", []


def graded_questions(form: dict) -> dict[str, float]:
    """퀴즈 폼에서 채점 대상 질문 ID → 배점. 퀴즈가 아니면 빈 dict."""
    return {s["id"]: float(s["point_value"]) for s in question_specs(form) if s.get("point_value") is not None}


def submission_from_response(response: dict, form_id: str, graded: dict[str, float] | None = None) -> FormSubmission:
    """FormResponse → FormSubmission.

    채점: 퀴즈 폼은 모든 답에 `grade`가 붙는데, 채점 대상이 아닌 문항과 **틀린 문항이 똑같이 빈 객체 `{}`** 로 온다
    (2026-10-06 실측). 그래서 graded(채점 대상 질문 ID → 배점)를 받아 그 질문만 grades에 넣고, 빈 grade는 0점·오답으로 본다.
    graded를 안 주면 score가 있는 문항만 넣는다(틀린 문항은 빠진다).
    """
    answers: dict[str, list[str]] = {}
    file_ids: dict[str, list[str]] = {}
    grades: dict[str, AnswerGrade] = {}
    for qid, a in (response.get("answers") or {}).items():
        if "textAnswers" in a:
            answers[qid] = [t.get("value", "") for t in a["textAnswers"].get("answers", [])]
        if "fileUploadAnswers" in a:
            file_ids[qid] = [f.get("fileId", "") for f in a["fileUploadAnswers"].get("answers", [])]
        g = a.get("grade")
        if graded is not None:
            if qid in graded:
                g = g or {}
                grades[qid] = AnswerGrade(score=g.get("score", 0), correct=bool(g.get("correct", False)), max_score=graded[qid])
        elif g and "score" in g:
            grades[qid] = AnswerGrade(score=g.get("score", 0), correct=bool(g.get("correct", False)))
    if graded is not None:  # 답하지 않은(선택) 채점 문항도 0점으로 남긴다
        for qid, point in graded.items():
            grades.setdefault(qid, AnswerGrade(score=0, correct=False, max_score=point))
    return FormSubmission(
        id=response["responseId"],
        form_id=form_id,
        respondent_email=response.get("respondentEmail"),
        created_at=response.get("createTime"),
        submitted_at=response.get("lastSubmittedTime"),
        answers=answers,
        file_ids=file_ids,
        total_score=response.get("totalScore"),
        grades=grades,
    )
