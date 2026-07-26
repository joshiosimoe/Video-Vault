import aws_cdk as cdk
from aws_cdk.assertions import Match, Template

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


def test_schedule_runs_every_fifteen_minutes():
    _template().has_resource_properties(
        "AWS::Events::Rule", {"ScheduleExpression": "rate(15 minutes)"}
    )


def test_pipe_connects_queue_to_state_machine():
    _template().has_resource_properties(
        "AWS::Pipes::Pipe",
        {
            "Source": Match.any_value(),
            "Target": Match.any_value(),
            "TargetParameters": Match.object_like(
                {"StepFunctionStateMachineParameters": {"InvocationType": "FIRE_AND_FORGET"}}
            ),
        },
    )


def test_exactly_one_pipe_exists():
    _template().resource_count_is("AWS::Pipes::Pipe", 1)
