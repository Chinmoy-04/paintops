"""Pydantic schema validation tests."""

import pytest
from pydantic import ValidationError

from app.schemas.event import InspectionEventCreate


def test_valid_event_passes(sample_event_payload: dict) -> None:
    event = InspectionEventCreate.model_validate(sample_event_payload)
    assert event.event_id == "QC-TEST-00001"
    assert event.defect_type == "orange_peel"
    assert event.model_confidence == 0.94


@pytest.mark.parametrize("confidence", [-0.1, 1.01, 2.0])
def test_confidence_out_of_range_rejected(
    sample_event_payload: dict, confidence: float
) -> None:
    sample_event_payload["model_confidence"] = confidence
    with pytest.raises(ValidationError):
        InspectionEventCreate.model_validate(sample_event_payload)


def test_unsupported_defect_rejected(sample_event_payload: dict) -> None:
    sample_event_payload["defect_type"] = "cratering"
    with pytest.raises(ValidationError):
        InspectionEventCreate.model_validate(sample_event_payload)


def test_missing_required_field_rejected(sample_event_payload: dict) -> None:
    del sample_event_payload["booth_id"]
    with pytest.raises(ValidationError):
        InspectionEventCreate.model_validate(sample_event_payload)
