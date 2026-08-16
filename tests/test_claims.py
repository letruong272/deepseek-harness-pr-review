import json

import pytest

from claims import extract_claims


FIXTURE_RESPONSE = """```json
[
  {"id": "C1", "text": "Adds checkout", "category": "feature",
   "files": ["src/checkout.py"], "docs": []},
  {"id": "C2", "text": "Fixes payment retry", "category": "bugfix",
   "files": ["src/payment.py"], "docs": ["docs/payment.md"]}
]
```"""


def test_extract_claims(tmp_path):
    snapshot = {
        "title": "Add checkout flow",
        "body": "Adds checkout. Fixes payment retry.",
        "files": [{"filename": "src/checkout.py"}, {"filename": "src/payment.py"}],
    }
    session_dir = tmp_path / "s"
    claims = extract_claims(
        snapshot,
        {"model": "m", "api_key": "k", "base_url": "http://x/v1"},
        session_dir,
        chat=lambda messages, **kw: FIXTURE_RESPONSE,
    )
    assert claims[0]["id"] == "C1"
    assert claims[1]["category"] == "bugfix"
    assert claims[1]["docs"] == ["docs/payment.md"]
    saved = json.loads((session_dir / "claims.json").read_text())
    assert len(saved) == 2


def test_extract_claims_invalid_response(tmp_path):
    session_dir = tmp_path / "s"
    with pytest.raises(RuntimeError, match="invalid claims response"):
        extract_claims(
            {"title": "t", "body": "b", "files": []},
            {"model": "m", "api_key": "k", "base_url": "http://x/v1"},
            session_dir,
            chat=lambda messages, **kw: "not json at all",
        )
