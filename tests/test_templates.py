import pytest

from app.templates import (
    RECIPIENTS,
    TEMPLATES,
    resolve_choice,
    rule_choice,
    templates_for,
)


class FakeModel:
    def __init__(self, answer=None, error=None):
        self.answer = answer
        self.error = error

    def choose(self, options, recipient, title, message):
        if self.error:
            raise self.error
        return self.answer


def test_every_recipient_has_a_group():
    assert set(RECIPIENTS) == {t.group for t in TEMPLATES}
    for recipient in RECIPIENTS:
        assert templates_for(recipient)


def test_explicit_template_is_used():
    choice = resolve_choice("yannic", None, "hi", template_id=3)
    assert choice.template.id == 3 and choice.selection == "explicit"


def test_explicit_template_outside_group_is_rejected():
    with pytest.raises(ValueError):
        resolve_choice("wife", None, "hi", template_id=1)


def test_rule_choice_is_deterministic_without_model():
    first = resolve_choice("yannic", "Title", "hi")
    second = resolve_choice("yannic", "Title", "hi")
    assert first == second
    assert first.selection == "rule"
    assert first.template.tall_title


def test_model_choice_is_validated_against_group():
    choice = resolve_choice("yannic", None, "hi", model=FakeModel(answer=(3, ["stars", "footer"])))
    assert choice.selection == "model"
    assert choice.template.id == 3
    # "footer" is not allowed on template 3, so it is dropped.
    assert choice.decorations == ("stars",)


def test_model_choice_outside_group_falls_back_to_rules():
    choice = resolve_choice("yannic", None, "hi", model=FakeModel(answer=(5, [])))
    assert choice.selection == "rule"
    assert choice.template.group == "yannic"


def test_model_failure_falls_back_to_rules():
    choice = resolve_choice("wife", None, "hi", model=FakeModel(error=TimeoutError("slow")))
    assert choice.selection == "rule"
    assert choice == rule_choice("wife", None)


def test_systemone_picks_the_template_with_the_highest_score(monkeypatch):
    import io
    import json

    from app import templates

    scores = {name: 0.0 for name in templates.QUESTIONS}
    scores["is_alert"] = 0.92
    reply = {"answers": {name: {"type": "noul", "noul": value} for name, value in scores.items()}}

    def fake_urlopen(request, timeout):
        assert request.full_url == "http://ollama:11434/v1/systemone"
        body = json.loads(request.data)
        assert "images" not in body and body["questions"]["is_alert"]["type"] == "noul"
        return io.BytesIO(json.dumps(reply).encode())

    monkeypatch.setattr(templates.urllib.request, "urlopen", fake_urlopen)
    model = templates.SystemOneModel("http://ollama:11434/v1", "d1", 5)
    choice = resolve_choice("wife", None, "Boiler fault", model=model)
    assert choice.selection == "model" and choice.template.id == 5
    assert choice.decorations == ("frame",)


def test_systemone_low_scores_fall_back_to_rules(monkeypatch):
    import io
    import json

    from app import templates

    reply = {"answers": {name: {"type": "noul", "noul": 0.1} for name in templates.QUESTIONS}}
    monkeypatch.setattr(
        templates.urllib.request, "urlopen", lambda request, timeout: io.BytesIO(json.dumps(reply).encode())
    )
    model = templates.SystemOneModel("http://ollama:11434", "d1", 5)
    choice = resolve_choice("yannic", "Plans", "hi", model=model)
    assert choice.selection == "rule"


def test_systemone_url_accepts_base_with_or_without_v1():
    from app.templates import SystemOneModel

    assert SystemOneModel("http://h:11434/v1/", "d1", 5).url == "http://h:11434/v1/systemone"
    assert SystemOneModel("http://h:11434", "d1", 5).url == "http://h:11434/v1/systemone"


def test_systemone_rejects_a_missing_or_out_of_range_score(monkeypatch):
    import io
    import json

    import pytest

    from app import templates

    reply = {"answers": {"is_alert": {"type": "noul", "noul": 1.7}}}
    monkeypatch.setattr(
        templates.urllib.request, "urlopen", lambda request, timeout: io.BytesIO(json.dumps(reply).encode())
    )
    with pytest.raises(ValueError):
        templates.SystemOneModel("http://h:11434", "d1", 5).scores("yannic", None, "hi")


def test_every_recipient_group_has_all_six_kinds():
    from app import templates

    for recipient in ("yannic", "wife"):
        kinds = sorted(t.kind for t in templates.templates_for(recipient))
        assert kinds == ["alert", "evening", "list", "morning", "note", "plain"]


def test_kind_is_decided_before_the_template_so_briefings_stay_briefings(monkeypatch):
    import io
    import json

    from app import templates

    scores = {name: 0.0 for name in templates.QUESTIONS}
    scores["is_morning_briefing"] = 0.7
    scores["has_numbers_or_stats"] = 0.98  # would have won under raw highest-score picking
    scores["is_short_note"] = 0.89
    reply = {"answers": {name: {"type": "noul", "noul": value} for name, value in scores.items()}}
    monkeypatch.setattr(
        templates.urllib.request, "urlopen", lambda request, timeout: io.BytesIO(json.dumps(reply).encode())
    )
    model = templates.SystemOneModel("http://h:11434", "d1", 5)
    choice = resolve_choice("wife", None, "Breakfast 8:00, bins out", model=model)
    assert choice.selection == "model"
    assert choice.template.kind == "morning" and choice.template.id == 10


def test_alert_wins_over_briefing_when_both_score(monkeypatch):
    import io
    import json

    from app import templates

    scores = {name: 0.0 for name in templates.QUESTIONS}
    scores["is_alert"] = 0.9
    scores["is_morning_briefing"] = 0.95
    reply = {"answers": {name: {"type": "noul", "noul": value} for name, value in scores.items()}}
    monkeypatch.setattr(
        templates.urllib.request, "urlopen", lambda request, timeout: io.BytesIO(json.dumps(reply).encode())
    )
    model = templates.SystemOneModel("http://h:11434", "d1", 5)
    choice = resolve_choice("yannic", None, "Smoke alarm in the hall", model=model)
    assert choice.template.kind == "alert" and choice.template.id == 8
