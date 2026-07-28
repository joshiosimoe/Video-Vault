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


def test_creates_five_alarms():
    _template().resource_count_is("AWS::CloudWatch::Alarm", 5)


def test_alarms_on_transcript_budget():
    _template().has_resource_properties(
        "AWS::CloudWatch::Alarm",
        {
            "MetricName": "TranscriptCalls",
            "Namespace": "VideoVault",
            "Statistic": "Sum",
            "Threshold": 20,
            "Period": 604800,
            "EvaluationPeriods": 1,
            "TreatMissingData": "notBreaching",
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
            "EvaluationPeriods": 1,
            "TreatMissingData": "notBreaching",
        },
    )


def test_alarms_on_timed_out_executions():
    # ExecutionsTimedOut is a separate metric from ExecutionsFailed; the
    # PipelineFailures alarm does not cover a States.Timeout.
    _template().has_resource_properties(
        "AWS::CloudWatch::Alarm",
        {
            "MetricName": "ExecutionsTimedOut",
            "Namespace": "AWS/States",
            "Threshold": 1,
            "EvaluationPeriods": 1,
            "TreatMissingData": "notBreaching",
        },
    )


def test_alarms_on_dlq_depth():
    template = _template()
    # VideoQueue is a *different* queue in the same template and also emits
    # ApproximateNumberOfMessagesVisible/AWS::SQS, so the alarm must be bound
    # to VideoDlq's logical id, not just matched on metric name/namespace.
    dlq_id = _logical_id(template, "AWS::SQS::Queue", "VideoDlq")
    template.has_resource_properties(
        "AWS::CloudWatch::Alarm",
        {
            "MetricName": "ApproximateNumberOfMessagesVisible",
            "Namespace": "AWS/SQS",
            "Threshold": 1,
            "EvaluationPeriods": 1,
            "TreatMissingData": "notBreaching",
            "Dimensions": [
                {
                    "Name": "QueueName",
                    "Value": {"Fn::GetAtt": [dlq_id, "QueueName"]},
                }
            ],
        },
    )


def test_alarms_on_poller_errors():
    template = _template()
    # Four other Lambda functions in the stack also emit Errors/AWS::Lambda,
    # so the alarm must be bound to PollerFunction's logical id.
    poller_id = _logical_id(template, "AWS::Lambda::Function", "PollerFunction")
    template.has_resource_properties(
        "AWS::CloudWatch::Alarm",
        {
            "MetricName": "Errors",
            "Namespace": "AWS/Lambda",
            "Threshold": 1,
            "EvaluationPeriods": 1,
            "TreatMissingData": "notBreaching",
            "Dimensions": [{"Name": "FunctionName", "Value": {"Ref": poller_id}}],
        },
    )
