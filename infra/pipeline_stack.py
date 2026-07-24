from aws_cdk import Duration, RemovalPolicy, Stack
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_sqs as sqs
from aws_cdk import aws_ssm as ssm
from constructs import Construct


class VideoVaultStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.state_table = dynamodb.Table(
            self,
            "StateTable",
            partition_key=dynamodb.Attribute(name="video_id", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.RETAIN,
            point_in_time_recovery_specification=dynamodb.PointInTimeRecoverySpecification(
                point_in_time_recovery_enabled=True
            ),
        )

        self.content_bucket = s3.Bucket(
            self,
            "ContentBucket",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            versioned=False,
            removal_policy=RemovalPolicy.RETAIN,
        )

        self.dlq = sqs.Queue(
            self,
            "VideoDlq",
            retention_period=Duration.days(14),
            enforce_ssl=True,
        )

        self.queue = sqs.Queue(
            self,
            "VideoQueue",
            visibility_timeout=Duration.minutes(5),
            enforce_ssl=True,
            dead_letter_queue=sqs.DeadLetterQueue(max_receive_count=3, queue=self.dlq),
        )

        # Discovery seam for downstream stacks (see the RAG note in the spec).
        ssm.StringParameter(
            self,
            "ContentBucketName",
            parameter_name="/video-vault/content-bucket",
            string_value=self.content_bucket.bucket_name,
        )
