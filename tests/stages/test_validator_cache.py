from __future__ import annotations

from gigaevo.programs.program import Program
from gigaevo.programs.stages.common import ProgramPayload
from gigaevo.programs.stages.python_executors.execution import CallValidatorFunction


def _validator_stage(tmp_path):
    path = tmp_path / "validate.py"
    path.write_text(
        "def validate(payload):\n"
        "    return {'fitness': 1.0, 'valid': 1.0}, None\n",
        encoding="utf-8",
    )
    return CallValidatorFunction(path=path, timeout=10)


def test_validator_hash_uses_payload_hash_not_payload_object(tmp_path):
    stage = _validator_stage(tmp_path)

    first = stage.compute_hash_for_inputs(
        {
            "payload": ProgramPayload(data={"opaque": object()}, payload_hash="abc123"),
            "context": None,
        }
    )
    second = stage.compute_hash_for_inputs(
        {
            "payload": ProgramPayload(data={"opaque": "different"}, payload_hash="abc123"),
            "context": None,
        }
    )
    third = stage.compute_hash_for_inputs(
        {
            "payload": ProgramPayload(data={"opaque": "different"}, payload_hash="def456"),
            "context": None,
        }
    )

    assert first == second
    assert first != third


def test_validator_provenance_written_to_program_metadata(tmp_path):
    stage = _validator_stage(tmp_path)
    payload = ProgramPayload(data={"result": 1}, payload_hash="payload-1")
    stage.attach_inputs({"payload": payload, "context": None})
    program = Program(code="def entrypoint(): return 1")

    stage._build_call(program)

    provenance = program.get_metadata("validation_provenance")
    assert provenance["payload_hash"] == "payload-1"
    assert provenance["function_name"] == "validate"
    assert "validator_hash" in provenance
