import pytest

from infoscope.services.demo_data import validate_demo_data_manifest


def _manifest(*, personalization: int = 1, brief: int = 1):
    return {
        "fact_layer": {
            "events": 2,
            "claims": 0,
            "timeline_entries": 0,
            "conflicts": 0,
            "base_analysis": 2,
        },
        "completed_personalization_artifacts": personalization,
        "completed_brief_artifacts": brief,
    }


def test_demo_manifest_accepts_complete_controlled_fact_layer() -> None:
    validate_demo_data_manifest(_manifest(), require_complete=True)


def test_demo_manifest_fails_closed_without_user_snapshots() -> None:
    with pytest.raises(RuntimeError, match="DEMO_PERSONALIZATION_OR_BRIEF_INCOMPLETE"):
        validate_demo_data_manifest(_manifest(personalization=0), require_complete=True)


def test_demo_manifest_fails_closed_without_events_or_base_analysis() -> None:
    manifest = _manifest()
    manifest["fact_layer"]["events"] = 0
    with pytest.raises(RuntimeError, match="DEMO_FACT_LAYER_INCOMPLETE"):
        validate_demo_data_manifest(manifest, require_complete=False)
