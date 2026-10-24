"""What a ticket is for, and how it sounds. Stored on every ticket and used in the log.

Fixed products (morning briefing, evening rundown) keep their layouts. Flexible kinds are
chosen by the caller, or by the decision model when the caller leaves them out.
"""

from __future__ import annotations

from typing import Literal

Kind = Literal[
    "morning",
    "evening",
    "note",
    "shopping",
    "todo",
    "alert",
    "fun",
    "reminder",
]
KINDS: tuple[str, ...] = ("morning", "evening", "note", "shopping", "todo", "alert", "fun", "reminder")
FIXED_KINDS: tuple[str, ...] = ("morning", "evening")

Tone = Literal["loving", "neutral", "reminder", "playful", "gentle", "firm", "urgent"]
TONES: tuple[str, ...] = ("loving", "neutral", "reminder", "playful", "gentle", "firm", "urgent")

InboxState = Literal["unread", "delivered", "seen"]
INBOX_STATES: tuple[str, ...] = ("unread", "delivered", "seen")

DEFAULT_KIND = "note"
DEFAULT_TONE = "neutral"
