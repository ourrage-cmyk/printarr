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
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

logger = logging.getLogger("printarr.templates")

Recipient = Literal["yannic", "wife"]
RECIPIENTS: dict[str, str] = {"yannic": "Yannic", "wife": "Wife"}
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
) -> Choice:
    """Pick a template. Raises ValueError only for an explicit template outside the group."""
    if template_id is not None:
        return explicit_choice(recipient, template_id)
    if model is not None:
        try:
            chosen_id, decorations = model.choose(templates_for(recipient), recipient, title, message)
            template = next(t for t in templates_for(recipient) if t.id == chosen_id)
            picked = tuple(d for d in DECORATIONS if d in decorations and d in template.allowed)
            return Choice(template, picked, "model")
        except Exception as exc:  # any model problem falls back to the rules
            logger.warning("decision model unusable, using rules: %s", exc)
    return rule_choice(recipient, title)


class OpenAICompatibleModel:
    """Calls any OpenAI-compatible chat endpoint, such as Ollama's /v1 or OpenRouter."""

    def __init__(self, base_url: str, model: str, timeout: float) -> None:
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.model = model
        self.timeout = timeout

    def choose(
        self, options: Sequence[Template], recipient: str, title: str | None, message: str
    ) -> tuple[int, list[str]]:
        menu = "\n".join(
            f"{t.id}: {t.name}, title align {t.title_align}, rule {t.rule!r}, "
            f"optional decorations {', '.join(t.allowed) or 'none'}"
            for t in options
        )
        system = (
            "You choose a receipt template for a thermal printer. Reply with only a JSON object "
            '{"template": <id>, "decorations": [<names>]}. Use an id from the list. '
            "Only use decorations listed for that template, or an empty list."
        )
        user = f"Templates:\n{menu}\n\nRecipient: {recipient}\nTitle: {title or '(none)'}\nMessage: {message}"
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
        content = reply["choices"][0]["message"]["content"]
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if match is None:
            raise ValueError("model reply contained no JSON object")
        data = json.loads(match.group(0))
        return int(data["template"]), [str(d) for d in data.get("decorations", [])]
