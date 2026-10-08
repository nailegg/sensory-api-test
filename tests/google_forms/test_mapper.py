from app.services.google_forms.mapper import document_from_form, publish_state, question_ids

DRIVE_FILE = {
    "id": "f1",
    "name": "Drive 파일명",
    "mimeType": "application/vnd.google-apps.form",
    "webViewLink": "https://docs.google.com/forms/d/f1/edit",
    "owners": [{"displayName": "교수자"}],
    "parents": ["folder1"],
}


def test_document_uses_info_title_and_edit_url():
    doc = document_from_form({"info": {"title": "응답자에게 보이는 제목"}}, DRIVE_FILE)
    assert doc.kind == "form"
    assert doc.title == "응답자에게 보이는 제목"
    assert doc.url.endswith("/edit")  # 응답 링크(responderUri)가 아니다
    assert doc.parent_folder_id == "folder1"


def test_publish_state_variants():
    assert publish_state({"publishSettings": {"publishState": {"isPublished": True, "isAcceptingResponses": True}}}) == {
        "published": True,
        "accepting_responses": True,
    }
    # unpublished=true로 만든 폼: publishState가 빈 객체로 온다(2026-10-06 실측)
    assert publish_state({"publishSettings": {"publishState": {}}}) == {"published": False, "accepting_responses": False}
    # 레거시 폼: publishSettings 자체가 없다
    assert publish_state({}) == {"published": None, "accepting_responses": None}


def test_question_ids_flattens_grid_rows():
    form = {
        "items": [
            {"title": "학번", "questionItem": {"question": {"questionId": "q1"}}},
            {"title": "섹션", "pageBreakItem": {}},
            {
                "title": "동료 평가",
                "questionGroupItem": {
                    "questions": [
                        {"questionId": "r1", "rowQuestion": {"title": "학생 A"}},
                        {"questionId": "r2", "rowQuestion": {"title": "학생 B"}},
                    ]
                },
            },
        ]
    }
    assert question_ids(form) == {"q1": "학번", "r1": "동료 평가 [학생 A]", "r2": "동료 평가 [학생 B]"}


from app.services.google_forms.mapper import graded_questions, question_specs, submission_from_response  # noqa: E402

QUIZ_FORM = {
    "items": [
        {"title": "학번", "questionItem": {"question": {"questionId": "sid", "textQuestion": {}}}},
        {"title": "404?", "questionItem": {"question": {"questionId": "q404", "grading": {"pointValue": 2},
            "choiceQuestion": {"type": "RADIO", "options": [{"value": "권한 없음"}, {"value": "찾을 수 없음"}, {"isOther": True}]}}}},
        {"title": "REST의 R", "questionItem": {"question": {"questionId": "qr", "grading": {"pointValue": 1}, "textQuestion": {}}}},
        {"title": "만족도", "questionItem": {"question": {"questionId": "sc", "scaleQuestion": {"low": 1, "high": 3}}}},
    ]
}


def test_question_specs_kinds_and_options():
    specs = {s["id"]: s for s in question_specs(QUIZ_FORM)}
    assert specs["q404"]["kind"] == "choice_radio"
    assert specs["q404"]["options"] == ["권한 없음", "찾을 수 없음", "(기타)"]
    assert specs["sc"]["options"] == ["1", "2", "3"]
    assert graded_questions(QUIZ_FORM) == {"q404": 2.0, "qr": 1.0}


def test_submission_empty_grade_means_wrong_only_for_graded_questions():
    # 2026-10-06 실측 형태: 틀린 문항과 채점 대상 아닌 문항이 똑같이 grade {}
    response = {
        "responseId": "r1", "respondentEmail": "a@example.com", "lastSubmittedTime": "2026-10-05T17:38:44.478332Z",
        "totalScore": 2,
        "answers": {
            "sid": {"grade": {}, "textAnswers": {"answers": [{"value": "0123"}]}},
            "q404": {"grade": {"score": 2, "correct": True}, "textAnswers": {"answers": [{"value": "찾을 수 없음"}]}},
            "qr": {"grade": {}, "textAnswers": {"answers": [{"value": "resources"}]}},
        },
    }
    sub = submission_from_response(response, "f1", graded_questions(QUIZ_FORM))
    assert sub.answers["sid"] == ["0123"]  # 문자열 그대로(앞자리 0 유지)
    assert set(sub.grades) == {"q404", "qr"}
    assert sub.grades["q404"].correct and sub.grades["q404"].score == 2
    assert sub.grades["qr"].score == 0 and not sub.grades["qr"].correct and sub.grades["qr"].max_score == 1
    # graded 없이 변환하면 점수가 있는 문항만
    assert set(submission_from_response(response, "f1").grades) == {"q404"}


def test_scale_without_low_starts_at_zero():
    # 2026-10-09 실측: low 0으로 만든 척도를 forms.get하면 {"high": 3}만 온다
    form = {"items": [{"title": "난이도", "questionItem": {"question": {"questionId": "s", "scaleQuestion": {"high": 3}}}}]}
    assert question_specs(form)[0]["options"] == ["0", "1", "2", "3"]
