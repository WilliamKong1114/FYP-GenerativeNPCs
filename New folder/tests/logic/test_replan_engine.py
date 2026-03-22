import pytest

from commitment_manager import (
    CommitmentState,
    build_impacted_slice,
    compute_impact_window,
    decide_commitment,
    extract_unperformed_steps,
    find_impacted_indices,
    rewrite_steps_for_event,
)


def test_compute_impact_window_requires_explicit_buffers():
    with pytest.raises(ValueError):
        compute_impact_window({"start_time": "20:00", "end_time": "22:00"})


def test_compute_impact_window_includes_buffers():
    event = {
        "start_time": "20:00",
        "end_time": "22:00",
        "prep_buffer_min": 30,
        "travel_to_min": 15,
        "travel_from_min": 20,
    }
    start, end = compute_impact_window(event)
    assert start == (20 * 60) - 45
    assert end == (22 * 60) + 20


def test_find_impacted_indices_only_overlaps_window():
    steps = [
        ("18:00", "Cook dinner"),
        ("19:00", "Read at home"),
        ("20:00", "Fix fence"),
        ("21:00", "Clean tools"),
        ("22:00", "Sleep prep"),
    ]
    impacted = find_impacted_indices(steps, impact_start=19 * 60 + 30, impact_end=21 * 60 + 15)
    assert impacted == [1, 2, 3]


def test_decide_commitment_declined_when_low_score_and_busy():
    decision = decide_commitment(
        {"event_id": "party-1", "title": "Village Party"},
        relationship_score=3.0,
        conflict_count=0,
        is_busy=True,
    )
    assert decision.state == CommitmentState.declined


def test_decide_commitment_declines_on_conflict_for_accept_decline_mode():
    decision = decide_commitment(
        {"event_id": "party-2", "title": "Village Party"},
        relationship_score=8.0,
        conflict_count=2,
        is_busy=False,
    )
    assert decision.state == CommitmentState.declined


def test_decide_commitment_calls_llm_for_ambiguous_case():
    def _mock_llm(_: dict):
        return "accepted"

    decision = decide_commitment(
        {"event_id": "party-4", "title": "Village Party"},
        relationship_score=5.8,
        conflict_count=0,
        is_busy=False,
        invitation_confidence=0.5,
        llm_decider=_mock_llm,
    )

    assert decision.state == CommitmentState.accepted
    assert decision.llm_used is True


def test_rewrite_steps_for_event_inserts_optional_when_conditional():
    steps = [
        ("18:00", "Cook dinner"),
        ("19:00", "Read at home"),
        ("20:00", "Fix fence"),
        ("21:00", "Clean tools"),
    ]
    event = {
        "event_id": "party-3",
        "title": "Village Party",
        "start_time": "20:00",
        "end_time": "21:00",
        "prep_buffer_min": 15,
        "travel_to_min": 10,
        "travel_from_min": 10,
    }
    updated, impacted = rewrite_steps_for_event(steps, event, optional=True)

    assert impacted
    assert any("[OPTIONAL] Attend Village Party" in action for _, action in updated)
    assert all(action != "Fix fence" for _, action in updated)


def test_extract_unperformed_steps_from_pointer():
    steps = [
        ("18:00", "Cook dinner"),
        ("19:00", "Read at home"),
        ("20:00", "Fix fence"),
        ("21:00", "Clean tools"),
    ]

    result = extract_unperformed_steps(steps, current_step=2, max_items=2)
    assert result == [("20:00", "Fix fence"), ("21:00", "Clean tools")]


def test_build_impacted_slice_returns_neighbors_within_future_steps():
    steps = [
        ("18:00", "Cook dinner"),
        ("19:00", "Read at home"),
        ("20:00", "Fix fence"),
        ("21:00", "Clean tools"),
        ("22:00", "Sleep prep"),
    ]

    impacted_slice, indices = build_impacted_slice(
        steps,
        current_step=1,
        impact_start=19 * 60 + 30,
        impact_end=21 * 60 + 15,
        neighbor_count=1,
    )

    assert indices == [1, 2, 3, 4]
    assert impacted_slice[0] == ("19:00", "Read at home")
    assert impacted_slice[-1] == ("22:00", "Sleep prep")
