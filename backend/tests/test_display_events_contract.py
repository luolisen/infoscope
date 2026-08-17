"""Contract v1 validation for the MQTT display snapshot."""

from __future__ import annotations

import json
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker, ValidationError

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPOSITORY_ROOT / "contracts" / "mqtt" / "display-events-v1.schema.json"
FIXTURE_PATH = REPOSITORY_ROOT / "contracts" / "mqtt" / "examples" / "display-events-v1.json"
MAX_PAYLOAD_BYTES = 4096


def load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def serialized_size(document: dict[str, object]) -> int:
    return len(json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


@pytest.fixture
def validator() -> Draft202012Validator:
    return Draft202012Validator(load_json(SCHEMA_PATH), format_checker=FormatChecker())


def test_canonical_fixture_validates_and_fits_device_limit(
    validator: Draft202012Validator,
) -> None:
    fixture = load_json(FIXTURE_PATH)

    validator.validate(fixture)
    assert serialized_size(fixture) <= MAX_PAYLOAD_BYTES


Mutator = Callable[[dict[str, object]], None]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda document: document.pop("revision"),
        lambda document: document.__setitem__("schema", "infoscope.display.events.v0"),
        lambda document: document.__setitem__("events", [{}] * 13),
        lambda document: document["events"][0].__setitem__("title", "x" * 121),  # type: ignore[index]
        lambda document: document.__setitem__("unexpected", True),
    ],
)
def test_contract_rejects_invalid_snapshots(
    validator: Draft202012Validator,
    mutate: Mutator,
) -> None:
    document = deepcopy(load_json(FIXTURE_PATH))
    mutate(document)

    with pytest.raises(ValidationError):
        validator.validate(document)


def test_contract_payload_boundary_is_4096_utf8_bytes(
    validator: Draft202012Validator,
) -> None:
    fixture = load_json(FIXTURE_PATH)
    event = fixture["events"][0]  # type: ignore[index]
    fixture["events"] = [deepcopy(event) for _ in range(12)]

    fields: list[tuple[dict[str, object], str, int]] = [(fixture, "revision", 128)]
    for item in fixture["events"]:  # type: ignore[union-attr]
        fields.extend([(item, "id", 128), (item, "title", 120), (item, "state", 64)])

    for document, key, maximum in fields:
        current = document[key]
        assert isinstance(current, str)
        remaining = MAX_PAYLOAD_BYTES - serialized_size(fixture)
        if remaining <= 0:
            break
        document[key] = current + ("x" * min(remaining, maximum - len(current)))

    validator.validate(fixture)
    assert serialized_size(fixture) == MAX_PAYLOAD_BYTES
