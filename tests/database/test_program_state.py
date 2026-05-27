"""Tests for gigaevo/programs/program_state.py"""

import pytest

from gigaevo.programs.program_state import (
    COMPLETE_STATES,
    INCOMPLETE_STATES,
    STATES_WITH_METRICS,
    TERMINAL_STATES,
    VALID_TRANSITIONS,
    ProgramState,
    has_metrics,
    is_complete,
    is_incomplete,
    is_terminal,
    is_valid_transition,
    merge_states,
    validate_transition,
)


class TestProgramStateEnum:
    def test_all_states_exist(self):
        assert ProgramState.QUEUED == "queued"
        assert ProgramState.RUNNING == "running"
        assert ProgramState.DONE == "done"
        assert ProgramState.DISCARDED == "discarded"
        assert ProgramState.QUARANTINED == "quarantined"

    def test_is_str_enum(self):
        for state in ProgramState:
            assert isinstance(state, str)
            assert isinstance(state.value, str)

    def test_exactly_five_states(self):
        assert len(ProgramState) == 5


class TestStateCategories:
    def test_incomplete_states(self):
        assert INCOMPLETE_STATES == {ProgramState.QUEUED, ProgramState.RUNNING}

    def test_complete_states(self):
        assert COMPLETE_STATES == {ProgramState.DONE}

    def test_terminal_states(self):
        assert TERMINAL_STATES == {ProgramState.DISCARDED, ProgramState.QUARANTINED}

    def test_disjoint(self):
        all_sets = [INCOMPLETE_STATES, COMPLETE_STATES, TERMINAL_STATES]
        for i, a in enumerate(all_sets):
            for b in all_sets[i + 1 :]:
                assert a.isdisjoint(b), f"{a} and {b} overlap"

    def test_union_covers_all_states(self):
        assert INCOMPLETE_STATES | COMPLETE_STATES | TERMINAL_STATES == set(
            ProgramState
        )

    def test_states_with_metrics(self):
        assert STATES_WITH_METRICS == {ProgramState.DONE}


class TestValidTransitions:
    @pytest.mark.parametrize(
        "src,dst",
        [
            (ProgramState.QUEUED, ProgramState.RUNNING),
            (ProgramState.QUEUED, ProgramState.DISCARDED),
            (ProgramState.QUEUED, ProgramState.QUARANTINED),
            (ProgramState.RUNNING, ProgramState.QUEUED),
            (ProgramState.RUNNING, ProgramState.DONE),
            (ProgramState.RUNNING, ProgramState.DISCARDED),
            (ProgramState.RUNNING, ProgramState.QUARANTINED),
            (ProgramState.DONE, ProgramState.DISCARDED),
            (ProgramState.DONE, ProgramState.QUARANTINED),
        ],
    )
    def test_valid_transitions(self, src, dst):
        assert is_valid_transition(src, dst) is True

    @pytest.mark.parametrize(
        "src,dst",
        [
            (ProgramState.QUEUED, ProgramState.DONE),
            (ProgramState.DONE, ProgramState.QUEUED),
            (ProgramState.DONE, ProgramState.RUNNING),
            (ProgramState.DISCARDED, ProgramState.QUEUED),
            (ProgramState.DISCARDED, ProgramState.RUNNING),
            (ProgramState.DISCARDED, ProgramState.DONE),
            (ProgramState.QUARANTINED, ProgramState.QUEUED),
            (ProgramState.QUARANTINED, ProgramState.RUNNING),
            (ProgramState.QUARANTINED, ProgramState.DONE),
        ],
    )
    def test_invalid_transitions(self, src, dst):
        assert is_valid_transition(src, dst) is False

    def test_self_transition_always_valid(self):
        for state in ProgramState:
            assert is_valid_transition(state, state) is True

    def test_discarded_has_no_outgoing(self):
        assert VALID_TRANSITIONS[ProgramState.DISCARDED] == set()
        assert VALID_TRANSITIONS[ProgramState.QUARANTINED] == set()


class TestValidateTransition:
    def test_valid_no_error(self):
        validate_transition(ProgramState.QUEUED, ProgramState.RUNNING)

    def test_invalid_raises_valueerror(self):
        with pytest.raises(ValueError, match="Invalid state transition"):
            validate_transition(ProgramState.QUEUED, ProgramState.DONE)

    def test_error_message_contains_states(self):
        with pytest.raises(ValueError, match="queued.*done"):
            validate_transition(ProgramState.QUEUED, ProgramState.DONE)


class TestPredicates:
    @pytest.mark.parametrize(
        "state,expected",
        [
            (ProgramState.QUEUED, True),
            (ProgramState.RUNNING, True),
            (ProgramState.DONE, False),
            (ProgramState.DISCARDED, False),
            (ProgramState.QUARANTINED, False),
        ],
    )
    def test_is_incomplete(self, state, expected):
        assert is_incomplete(state) is expected

    @pytest.mark.parametrize(
        "state,expected",
        [
            (ProgramState.QUEUED, False),
            (ProgramState.RUNNING, False),
            (ProgramState.DONE, True),
            (ProgramState.DISCARDED, False),
            (ProgramState.QUARANTINED, False),
        ],
    )
    def test_is_complete(self, state, expected):
        assert is_complete(state) is expected

    @pytest.mark.parametrize(
        "state,expected",
        [
            (ProgramState.QUEUED, False),
            (ProgramState.RUNNING, False),
            (ProgramState.DONE, False),
            (ProgramState.DISCARDED, True),
            (ProgramState.QUARANTINED, True),
        ],
    )
    def test_is_terminal(self, state, expected):
        assert is_terminal(state) is expected

    @pytest.mark.parametrize(
        "state,expected",
        [
            (ProgramState.QUEUED, False),
            (ProgramState.RUNNING, False),
            (ProgramState.DONE, True),
            (ProgramState.DISCARDED, False),
            (ProgramState.QUARANTINED, False),
        ],
    )
    def test_has_metrics(self, state, expected):
        assert has_metrics(state) is expected


class TestMergeStates:
    def test_same_state(self):
        for state in ProgramState:
            assert merge_states(state, state) == state

    def test_terminal_wins_as_incoming(self):
        for state in [ProgramState.QUEUED, ProgramState.RUNNING, ProgramState.DONE]:
            assert merge_states(state, ProgramState.DISCARDED) == ProgramState.DISCARDED
            assert (
                merge_states(state, ProgramState.QUARANTINED)
                == ProgramState.QUARANTINED
            )

    def test_terminal_wins_as_current(self):
        for state in [ProgramState.QUEUED, ProgramState.RUNNING, ProgramState.DONE]:
            assert merge_states(ProgramState.DISCARDED, state) == ProgramState.DISCARDED
            assert (
                merge_states(ProgramState.QUARANTINED, state)
                == ProgramState.QUARANTINED
            )

    def test_forward_transition(self):
        # QUEUED -> RUNNING is a valid transition, so incoming wins
        assert (
            merge_states(ProgramState.QUEUED, ProgramState.RUNNING)
            == ProgramState.RUNNING
        )

    def test_backward_transition(self):
        # RUNNING -> QUEUED is the lease-retry transition, so incoming wins.
        assert (
            merge_states(ProgramState.RUNNING, ProgramState.QUEUED)
            == ProgramState.QUEUED
        )

    def test_done_to_running_merge_keeps_done(self):
        assert merge_states(ProgramState.DONE, ProgramState.RUNNING) == ProgramState.DONE

    def test_done_to_queued_incompatible_raises(self):
        with pytest.raises(ValueError, match="Cannot merge incompatible states"):
            merge_states(ProgramState.DONE, ProgramState.QUEUED)

    def test_valid_non_terminal_pairs_merge_no_crash(self):
        for s1, s2 in [
            (ProgramState.QUEUED, ProgramState.RUNNING),
            (ProgramState.RUNNING, ProgramState.QUEUED),
            (ProgramState.RUNNING, ProgramState.DONE),
        ]:
            result = merge_states(s1, s2)
            assert isinstance(result, ProgramState)

    def test_merge_is_commutative_for_same_state(self):
        """merge_states(s, s) == s for all states."""
        for s in ProgramState:
            assert merge_states(s, s) == s
