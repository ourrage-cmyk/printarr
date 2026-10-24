"""Keeps the docs in step with the live API.

- docs/openapi.json is the generated schema of the code, so it must match it.
- Every route the README and the agent skill name must exist.
- Every local file the README links to or shows must exist.
- The Hermes copy of the agent skill must match the canonical one.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from app.main import create_app

ROOT = Path(__file__).resolve().parents[1]
API = "/api/v1"
NOT_ROUTES = {"/docs"}  # served by FastAPI, not part of the API schema
PREFIX_PATH = re.compile(r"`(?:GET |POST |PUT |DELETE )?(/[^`\s?]*)")


def _normalise(path: str) -> str:
    return re.sub(r"\{[^}]*\}", "{}", path).rstrip("/") or "/"


def _schema_paths() -> set[str]:
    schema = create_app().openapi()
    return {_normalise(p[len(API):] if p.startswith(API) else p) for p in schema["paths"]}


def _named_routes(text: str, *, relative_ok: bool) -> set[str]:
    found = set()
    for match in PREFIX_PATH.finditer(text):
        token = match.group(1)
        if token in NOT_ROUTES or token.startswith(("/mnt", "/data", "/home")):
            continue
        if token.startswith(API):
            found.add(token[len(API):] or "/")
        elif relative_ok and token.startswith("/") and not token.startswith("//"):
            found.add(token)
    return {_normalise(p) for p in found}


def test_openapi_json_matches_the_code():
    committed = json.loads((ROOT / "docs" / "openapi.json").read_text(encoding="utf-8"))
    assert committed == create_app().openapi(), "run: python -m app.openapi_export"


def test_readme_routes_exist():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    known = _schema_paths()
    missing = sorted(r for r in _named_routes(text, relative_ok=False) if r not in known and r != "/")
    assert not missing, f"README names routes that do not exist: {missing}"


def test_skill_routes_exist():
    text = (ROOT / "docs" / "agents" / "hermes-skill" / "SKILL.md").read_text(encoding="utf-8")
    known = _schema_paths()
    missing = sorted(r for r in _named_routes(text, relative_ok=True) if r not in known and r != "/")
    assert not missing, f"SKILL.md names routes that do not exist: {missing}"


def test_skill_copies_match():
    canonical = (ROOT / "docs" / "agents" / "hermes-skill" / "SKILL.md").read_text(encoding="utf-8")
    for copy_path in ("skills/printarr/SKILL.md", "docs/integrations/hermes/SKILL.md"):
        copy = (ROOT / copy_path).read_text(encoding="utf-8")
        assert copy == canonical, f"copy docs/agents/hermes-skill/SKILL.md to {copy_path}"


def test_local_links_and_images_exist():
    for name in ("README.md", "docs/STATUS.md"):
        path = ROOT / name
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        targets = re.findall(r"\]\(([^)\s]+)\)", text) + re.findall(r'src="([^"]+)"', text)
        for target in targets:
            if target.startswith(("http://", "https://", "#", "mailto:")):
                continue
            file_part = target.split("#", 1)[0]
            assert (path.parent / file_part).exists(), f"{name} links to a missing file: {target}"
