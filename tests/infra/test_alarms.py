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


def test_creates_four_alarms():
    _template().resource_count_is("AWS::CloudWatch::Alarm", 4)


def test_alarms_on_transcript_budget():
    _template().has_resource_properties(
        "AWS::CloudWatch::Alarm",
        {
            "MetricName": "TranscriptCalls",
            "Namespace": "VideoVault",
            "Statistic": "Sum",
            "Threshold": 20,
            "Period": 604800,
        },
    )


def test_creates_a_dashboard():
    _template().resource_count_is("AWS::CloudWatch::Dashboard", 1)


def test_alarms_on_failed_executions():
    _template().has_resource_properties(
        "AWS::CloudWatch::Alarm",
        {
            "MetricName": "ExecutionsFailed",
            "Namespace": "AWS/States",
            "Threshold": 1,
        },
    )


def test_alarms_on_dlq_depth():
    _template().has_resource_properties(
        "AWS::CloudWatch::Alarm",
        {
            "MetricName": "ApproximateNumberOfMessagesVisible",
            "Namespace": "AWS/SQS",
            "Threshold": 1,
        },
    )


def test_alarms_on_poller_errors():
    _template().has_resource_properties(
        "AWS::CloudWatch::Alarm",
        {"MetricName": "Errors", "Namespace": "AWS/Lambda", "Threshold": 1},
    )
