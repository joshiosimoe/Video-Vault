import json

import aws_cdk as cdk
from aws_cdk.assertions import Template

from infra.pipeline_stack import VideoVaultStack

CONTEXT = {
    "playlist_id": "PL123",
    "vault_repo_owner": "me",
    "vault_repo_name": "vault",
    "bedrock_region": "us-east-1",
}


def _template() -> Template:
    app = cdk.App(context=CONTEXT)
    return Template.from_stack(VideoVaultStack(app, "TestStack"))


def test_creates_one_standard_state_machine():
    template = _template()
    template.resource_count_is("AWS::StepFunctions::StateMachine", 1)
    machine = next(iter(template.find_resources("AWS::StepFunctions::StateMachine").values()))
    assert machine["Properties"].get("StateMachineType", "STANDARD") == "STANDARD"


def _definition_text(template: Template) -> str:
    machine = next(iter(template.find_resources("AWS::StepFunctions::StateMachine").values()))
    body = machine["Properties"]["DefinitionString"]
    return "".join(part for part in body["Fn::Join"][1] if isinstance(part, str))


def test_definition_unwraps_the_pipes_batch_array():
    # EventBridge Pipes always delivers the target payload as an ARRAY of
    # transformed events -- batch_size=1 yields a single-element array, not a bare
    # object. Every handler expects an object, so without unwrapping the first
    # Lambda dies with "list indices must be integers or slices, not str", and the
    # MarkFailed catch then fails too: its result_path "$.error" is applied to the
    # state's RAW input, which is still the array, giving
    # States.ReferencePathConflict. Normalizing must therefore happen BEFORE any
    # state that carries a catch, which is why it is its own first state rather
    # than an InputPath on FetchTranscript.
    text = _definition_text(_template()).replace(" ", "")
    assert '"StartAt":"NormalizeBatch"' in text
    assert '"InputPath":"$[0]"' in text


def _definition_states(template: Template) -> set[str]:
    machine = next(iter(template.find_resources("AWS::StepFunctions::StateMachine").values()))
    body = machine["Properties"]["DefinitionString"]
    joined = "".join(part for part in body["Fn::Join"][1] if isinstance(part, str))
    return set(part for part in joined.split('"') if part)


def test_definition_includes_all_pipeline_states():
    states = _definition_states(_template())
    for name in [
        "FetchTranscript",
        "HasTranscript",
        "Summarize",
        "RenderAndCommit",
        "WriteStubNote",
        "MarkFailed",
    ]:
        assert name in states


def _definition(template: Template) -> dict:
    machine = next(iter(template.find_resources("AWS::StepFunctions::StateMachine").values()))
    parts = machine["Properties"]["DefinitionString"]["Fn::Join"][1]
    return json.loads(
        "".join(part if isinstance(part, str) else "ARN_PLACEHOLDER" for part in parts)
    )


def test_caught_failures_end_the_execution_as_failed():
    """ExecutionsFailed is the spec's primary failure signal, so a caught failure
    must not end the execution in success: MarkFailed hands off to a Fail state."""
    states = _definition(_template())["States"]
    assert states["MarkFailed"]["Next"] == "PipelineFailed"
    assert states["PipelineFailed"]["Type"] == "Fail"


def test_mark_failed_records_the_error():
    """Design spec: MarkFailed 'sets status: failed, records the error, increments
    attempts'. The DynamoDB update must actually write an error attribute, not just
    status and attempts."""
    params = _definition(_template())["States"]["MarkFailed"]["Parameters"]
    names = params["ExpressionAttributeNames"]
    values = params["ExpressionAttributeValues"]
    name_placeholder = next(key for key, value in names.items() if value == "error")
    value_placeholder = ":" + name_placeholder.lstrip("#")
    assert value_placeholder in values
