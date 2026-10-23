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


def test_openai_compatible_client_parses_json_reply(monkeypatch):
    import io
    import json

    from app import templates

    reply = {"choices": [{"message": {"content": 'Sure: {"template": 6, "decorations": []}'}}]}

    def fake_urlopen(request, timeout):
        assert request.full_url == "http://ollama:11434/v1/chat/completions"
        return io.BytesIO(json.dumps(reply).encode())

    monkeypatch.setattr(templates.urllib.request, "urlopen", fake_urlopen)
    model = templates.OpenAICompatibleModel("http://ollama:11434/v1", "d1:latest", 5)
    choice = resolve_choice("wife", None, "hi", model=model)
    assert choice.selection == "model" and choice.template.id == 6
