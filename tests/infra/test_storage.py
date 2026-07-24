import aws_cdk as cdk
from aws_cdk.assertions import Match, Template

from infra.pipeline_stack import VideoVaultStack


def _template() -> Template:
    return Template.from_stack(VideoVaultStack(cdk.App(), "TestStack"))


def test_state_table_is_on_demand_with_video_id_key():
    _template().has_resource_properties(
        "AWS::DynamoDB::Table",
        {
            "BillingMode": "PAY_PER_REQUEST",
            "KeySchema": [{"AttributeName": "video_id", "KeyType": "HASH"}],
        },
    )


def test_content_bucket_blocks_public_access_and_encrypts():
    _template().has_resource_properties(
        "AWS::S3::Bucket",
        {
            "PublicAccessBlockConfiguration": {
                "BlockPublicAcls": True,
                "BlockPublicPolicy": True,
                "IgnorePublicAcls": True,
                "RestrictPublicBuckets": True,
            },
            "BucketEncryption": Match.any_value(),
        },
    )


def test_queue_has_dead_letter_queue_with_three_receives():
    _template().has_resource_properties(
        "AWS::SQS::Queue",
        {"RedrivePolicy": Match.object_like({"maxReceiveCount": 3})},
    )


def test_creates_exactly_two_queues():
    _template().resource_count_is("AWS::SQS::Queue", 2)


def test_publishes_content_bucket_name_to_ssm():
    _template().has_resource_properties(
        "AWS::SSM::Parameter",
        {"Name": "/video-vault/content-bucket", "Type": "String"},
    )
