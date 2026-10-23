"""Write the OpenAPI schema to docs/openapi.json.

Run from the repository root:  python -m app.openapi_export
"""

from __future__ import annotations

import json
from pathlib import Path

from app.main import create_app


def main() -> None:
    schema = create_app().openapi()
    out = Path(__file__).resolve().parents[1] / "docs" / "openapi.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
