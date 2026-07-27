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


def _logical_id(template: Template, cfn_type: str, prefix: str) -> str:
    for logical_id in template.find_resources(cfn_type):
        if logical_id.startswith(prefix):
            return logical_id
    raise AssertionError(f"no {cfn_type} with logical id starting {prefix}")


def test_schedule_runs_every_fifteen_minutes():
    template = _template()
    template.has_resource_properties(
        "AWS::Events::Rule", {"ScheduleExpression": "rate(15 minutes)"}
    )

    poller_id = _logical_id(template, "AWS::Lambda::Function", "PollerFunction")
    rule = next(iter(template.find_resources("AWS::Events::Rule").values()))
    targets = rule["Properties"]["Targets"]
    assert any(t["Arn"] == {"Fn::GetAtt": [poller_id, "Arn"]} for t in targets)


def test_pipe_connects_queue_to_state_machine():
    template = _template()

    # Note: VideoDlq is a separate queue in the same template, so the prefix matters.
    queue_id = _logical_id(template, "AWS::SQS::Queue", "VideoQueue")
    machine_id = _logical_id(template, "AWS::StepFunctions::StateMachine", "VideoPipeline")

    pipe = next(iter(template.find_resources("AWS::Pipes::Pipe").values()))
    props = pipe["Properties"]

    assert props["Source"] == {"Fn::GetAtt": [queue_id, "Arn"]}
    assert props["Target"] == {"Ref": machine_id}
    assert (
        props["TargetParameters"]["StepFunctionStateMachineParameters"]["InvocationType"]
        == "FIRE_AND_FORGET"
    )


def test_exactly_one_pipe_exists():
    _template().resource_count_is("AWS::Pipes::Pipe", 1)
