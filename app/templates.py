"""Receipt templates, grouped by recipient, and the rules that pick one.

A ticket names a fixed recipient. That recipient's template group is the only set of
templates a ticket may use. A request can name a template explicitly. If it does not,
an optional decision model may choose one. Without the model, or if the model fails or
answers with something invalid, a fixed rule chooses instead.
"""

from __future__ import annotations

import json
import logging
import re
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

logger = logging.getLogger("printarr.templates")

Recipient = Literal["yannic", "wife"]
RECIPIENTS: dict[str, str] = {"yannic": "Yannic", "wife": "Allyson"}
Selection = Literal["explicit", "model", "rule"]

DECORATIONS = ("stars", "frame", "footer")


@dataclass(frozen=True)
class Template:
    id: int
    name: str
    group: str
    tall_title: bool
    title_align: Literal["left", "center"]
    rule: str
    allowed: tuple[str, ...]  # decorations the model may pick from
    default: tuple[str, ...]  # decorations the rule-based path uses


TEMPLATES: tuple[Template, ...] = (
    Template(1, "Classic", "yannic", True, "center", "-", ("footer",), ()),
    Template(2, "Memo", "yannic", True, "left", "=", ("footer",), ("footer",)),
    Template(3, "Celebration", "yannic", True, "center", "*", ("stars", "frame"), ("stars",)),
    Template(4, "Note", "wife", True, "left", "-", ("footer", "stars"), ()),
    Template(5, "Bold", "wife", True, "center", "#", ("frame",), ("frame",)),
    Template(6, "Plain", "wife", False, "left", "-", ("footer",), ()),
)

_BY_ID = {template.id: template for template in TEMPLATES}


def template_by_id(template_id: int) -> Template:
    return _BY_ID[template_id]


def templates_for(recipient: str) -> tuple[Template, ...]:
    return tuple(t for t in TEMPLATES if t.group == recipient)


@dataclass(frozen=True)
class Choice:
    template: Template
    decorations: tuple[str, ...]
    selection: Selection


class DecisionModel(Protocol):
    def choose(
        self, options: Sequence[Template], recipient: str, title: str | None, message: str
    ) -> tuple[int, list[str]]: ...


def rule_choice(recipient: str, title: str | None) -> Choice:
    """Deterministic fallback. Titled tickets get the first template with a tall title."""
    options = templates_for(recipient)
    template = options[0]
    if title:
        template = next((t for t in options if t.tall_title), options[0])
    return Choice(template, template.default, "rule")


def explicit_choice(recipient: str, template_id: int) -> Choice:
    template = _BY_ID.get(template_id)
    if template is None or template.group != recipient:
        allowed = ", ".join(str(t.id) for t in templates_for(recipient))
        raise ValueError(f"template {template_id} is not available for {recipient}; use one of {allowed}")
    return Choice(template, template.default, "explicit")


def resolve_choice(
    recipient: str,
    title: str | None,
    message: str,
    template_id: int | None = None,
    model: DecisionModel | None = None,
    on_model_result: Callable[[Exception | None], None] | None = None,
) -> Choice:
    """Pick a template. Raises ValueError only for an explicit template outside the group.

    on_model_result is called with None after a usable model answer, or with the error when
    the model is down or answers badly. A model problem never fails the request. It falls
    back to the rules and is logged.
    """
    if template_id is not None:
        return explicit_choice(recipient, template_id)
    if model is not None:
        try:
            chosen_id, decorations = model.choose(templates_for(recipient), recipient, title, message)
            template = next(t for t in templates_for(recipient) if t.id == chosen_id)
            picked = tuple(d for d in DECORATIONS if d in decorations and d in template.allowed)
            if on_model_result:
                on_model_result(None)
            return Choice(template, picked, "model")
        except Exception as exc:  # any model problem falls back to the rules
            logger.warning("decision model unusable, using rules: %s", exc)
            if on_model_result:
                on_model_result(exc)
    return rule_choice(recipient, title)


class OpenAICompatibleModel:
    """Calls any OpenAI-compatible chat endpoint, such as Ollama's /v1 or OpenRouter."""

    def __init__(self, base_url: str, model: str, timeout: float) -> None:
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.model = model
        self.timeout = timeout

    def _chat(self, system: str, user: str) -> str:
        body = json.dumps(
            {
                "model": self.model,
                "temperature": 0,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            }
        ).encode()
        request = urllib.request.Request(
            self.url, data=body, headers={"Content-Type": "application/json"}, method="POST"
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            reply = json.loads(response.read())
        return reply["choices"][0]["message"]["content"]

    def rewrite(self, text: str) -> str:
        """Clean up unformatted text, for example speech-to-text. Used by the text model only."""
        system = (
            "You clean up text for a receipt printer. Fix spelling, punctuation and garbled "
            "speech-to-text. Keep the meaning and the language. Reply with only the cleaned text, "
            "no quotes and no commentary."
        )
        cleaned = self._chat(system, text).strip()
        if not cleaned:
            raise ValueError("text model returned nothing")
        return cleaned


# Yes/no-style questions the decision model scores from 0 to 1, one answer each.
QUESTIONS: dict[str, str] = {
    "is_alert": "Is this an alert or warning that needs attention now?",
    "is_urgent": "Is this urgent?",
    "is_morning_briefing": "Is this a morning briefing or plan for the day?",
    "is_evening_briefing": "Is this an evening wrap-up or summary of the day?",
    "is_short_note": "Is this a short personal note?",
    "is_list": "Is this a list of items?",
    "is_personal": "Is this a personal or affectionate message?",
    "has_numbers_or_stats": "Does this contain numbers, times or statistics?",
}

# Which questions speak for each template. A template scores the highest of its questions.
# Edit this table to change the mapping; the template ids are in TEMPLATES above.
TEMPLATE_QUESTIONS: dict[int, tuple[str, ...]] = {
    1: ("is_morning_briefing", "is_evening_briefing"),  # Classic
    2: ("is_list", "has_numbers_or_stats", "is_short_note"),  # Memo
    3: ("is_personal",),  # Celebration
    4: ("is_short_note", "is_personal"),  # Note
    5: ("is_alert", "is_urgent"),  # Bold
    6: ("is_list", "has_numbers_or_stats"),  # Plain
}
MIN_SCORE = 0.5  # below this, no template is trusted and the rules choose


class SystemOneModel:
    """Scores questions about a message with Ollama's structured endpoint, /v1/systemone.

    Text only: no image is sent. The endpoint was built for photos, so its answers on plain
    text are not yet checked. Any failure raises, and the rules choose instead.
    """

    def __init__(self, base_url: str, model: str, timeout: float) -> None:
        root = base_url.rstrip("/")
        if root.endswith("/v1"):
            root = root[: -len("/v1")]
        self.url = root + "/v1/systemone"
        self.model = model
        self.timeout = timeout

    def scores(self, recipient: str, title: str | None, message: str) -> dict[str, float]:
        body = json.dumps(
            {
                "model": self.model,
                "state": (
                    "A printed receipt ticket. Answer each question about the message. "
                    f"Recipient: {RECIPIENTS.get(recipient, recipient)}. "
                    f"Title: {title or '(none)'}. Message: {message}"
                ),
                "questions": {
                    name: {"type": "noul", "instructions": text} for name, text in QUESTIONS.items()
                },
            }
        ).encode()
        request = urllib.request.Request(
            self.url, data=body, headers={"Content-Type": "application/json"}, method="POST"
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            reply = json.loads(response.read())
        answers = reply.get("answers", {})
        result: dict[str, float] = {}
        for name in QUESTIONS:
            value = answers.get(name, {}).get("noul")
            if not isinstance(value, (int, float)) or not 0.0 <= float(value) <= 1.0:
                raise ValueError(f"decision model gave no usable score for {name}")
            result[name] = float(value)
        return result

    def choose(
        self, options: Sequence[Template], recipient: str, title: str | None, message: str
    ) -> tuple[int, list[str]]:
        scores = self.scores(recipient, title, message)
        best_id, best_score = None, -1.0
        for template in options:
            score = max((scores[q] for q in TEMPLATE_QUESTIONS.get(template.id, ())), default=0.0)
            if score > best_score:
                best_id, best_score = template.id, score
        if best_id is None or best_score < MIN_SCORE:
            raise ValueError(f"no template scored at least {MIN_SCORE}")
        # The template's own default decorations; resolve_choice keeps the ones it allows.
        chosen = next(t for t in options if t.id == best_id)
        return best_id, list(chosen.default)
