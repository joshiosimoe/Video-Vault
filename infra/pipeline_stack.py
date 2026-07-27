from aws_cdk import BundlingOptions, Duration, RemovalPolicy, Stack
from aws_cdk import aws_cloudwatch as cloudwatch
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_events as events
from aws_cdk import aws_events_targets as targets
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_pipes as pipes
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_sqs as sqs
from aws_cdk import aws_ssm as ssm
from aws_cdk import aws_stepfunctions as sfn
from aws_cdk import aws_stepfunctions_tasks as tasks
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

        playlist_id = self.node.try_get_context("playlist_id") or "REPLACE_ME"
        repo_owner = self.node.try_get_context("vault_repo_owner") or "REPLACE_ME"
        repo_name = self.node.try_get_context("vault_repo_name") or "REPLACE_ME"
        bedrock_region = self.node.try_get_context("bedrock_region") or self.region

        param_prefix = f"arn:aws:ssm:{self.region}:{self.account}:parameter/video-vault"

        code = lambda_.Code.from_asset(
            "src",
            bundling=BundlingOptions(
                image=lambda_.Runtime.PYTHON_3_12.bundling_image,
                command=[
                    "bash",
                    "-c",
                    "pip install -r requirements.txt -t /asset-output "
                    "&& mkdir -p /asset-output/src "
                    "&& cp -au . /asset-output/src",
                ],
            ),
        )

        common_env = {
            "STATE_TABLE": self.state_table.table_name,
            "CONTENT_BUCKET": self.content_bucket.bucket_name,
        }

        def make_function(name: str, handler: str, env: dict, timeout_min: int):
            fn = lambda_.Function(
                self,
                name,
                runtime=lambda_.Runtime.PYTHON_3_12,
                handler=handler,
                code=code,
                timeout=Duration.minutes(timeout_min),
                memory_size=512,
                environment={**common_env, **env},
            )
            self.state_table.grant_read_write_data(fn)
            return fn

        def grant_ssm(fn: lambda_.Function, names: list[str]) -> None:
            fn.add_to_role_policy(
                iam.PolicyStatement(
                    actions=["ssm:GetParameter"],
                    resources=[f"{param_prefix}/{n}" for n in names],
                )
            )

        self.fn_poller = make_function(
            "PollerFunction",
            "src.handlers.poller.handler",
            {
                "QUEUE_URL": self.queue.queue_url,
                "PLAYLIST_ID": playlist_id,
                "GOOGLE_CLIENT_ID_PARAM": "/video-vault/google-client-id",
                "GOOGLE_CLIENT_SECRET_PARAM": "/video-vault/google-client-secret",
                "GOOGLE_REFRESH_TOKEN_PARAM": "/video-vault/google-refresh-token",
            },
            timeout_min=5,
        )
        self.queue.grant_send_messages(self.fn_poller)
        grant_ssm(
            self.fn_poller,
            ["google-client-id", "google-client-secret", "google-refresh-token"],
        )

        self.fn_fetch = make_function(
            "FetchTranscriptFunction",
            "src.handlers.fetch_transcript.handler",
            {"TRANSCRIPT_API_KEY_PARAM": "/video-vault/transcript-api-key"},
            timeout_min=2,
        )
        self.content_bucket.grant_read_write(self.fn_fetch)
        grant_ssm(self.fn_fetch, ["transcript-api-key"])

        self.fn_summarize = make_function(
            "SummarizeFunction",
            "src.handlers.summarize.handler",
            {"BEDROCK_REGION": bedrock_region},
            timeout_min=10,
        )
        self.content_bucket.grant_read(self.fn_summarize)
        self.fn_summarize.add_to_role_policy(
            iam.PolicyStatement(
                actions=["bedrock:InvokeModel"],
                resources=[
                    f"arn:aws:bedrock:{bedrock_region}::foundation-model/anthropic.claude-sonnet-5"
                ],
            )
        )

        commit_env = {
            "GITHUB_TOKEN_PARAM": "/video-vault/github-token",
            "VAULT_REPO_OWNER": repo_owner,
            "VAULT_REPO_NAME": repo_name,
        }

        self.fn_commit = make_function(
            "RenderCommitFunction", "src.handlers.render_commit.handler", commit_env, 2
        )
        grant_ssm(self.fn_commit, ["github-token"])
        # Writes summaries/{video_id}.json for downstream consumers.
        self.content_bucket.grant_put(self.fn_commit)

        # The stub handler writes no summary artifact, so it gets no S3 grant.
        self.fn_stub = make_function(
            "StubNoteFunction", "src.handlers.render_commit.stub_handler", commit_env, 2
        )
        grant_ssm(self.fn_stub, ["github-token"])

        mark_failed = tasks.DynamoUpdateItem(
            self,
            "MarkFailed",
            table=self.state_table,
            key={
                "video_id": tasks.DynamoAttributeValue.from_string(
                    sfn.JsonPath.string_at("$.video_id")
                )
            },
            update_expression="SET #s = :s, #e = :e, #u = :u ADD #a :one",
            expression_attribute_names={
                "#s": "status",
                "#e": "error",
                "#u": "updated_at",
                "#a": "attempts",
            },
            expression_attribute_values={
                ":s": tasks.DynamoAttributeValue.from_string("failed"),
                ":e": tasks.DynamoAttributeValue.from_string(
                    sfn.JsonPath.json_to_string(sfn.JsonPath.object_at("$.error"))
                ),
                ":u": tasks.DynamoAttributeValue.from_string(
                    sfn.JsonPath.string_at("$$.State.EnteredTime")
                ),
                ":one": tasks.DynamoAttributeValue.from_number(1),
            },
        )

        # MarkFailed must not end the execution in success: ExecutionsFailed is the
        # primary failure signal (see the spec's failure-handling table) and Task 19's
        # PipelineFailures alarm is built on it.
        mark_failed.next(
            sfn.Fail(
                self,
                "PipelineFailed",
                error="VideoVaultPipelineFailed",
                cause="See the DynamoDB status and error fields for this video_id.",
            )
        )

        retry_props = {
            "errors": ["States.ALL"],
            "interval": Duration.seconds(2),
            "max_attempts": 3,
            "backoff_rate": 2.0,
        }

        fetch = tasks.LambdaInvoke(
            self,
            "FetchTranscript",
            lambda_function=self.fn_fetch,
            payload_response_only=True,
        )
        fetch.add_retry(**retry_props)
        fetch.add_catch(mark_failed, result_path="$.error")

        summarize = tasks.LambdaInvoke(
            self,
            "Summarize",
            lambda_function=self.fn_summarize,
            payload_response_only=True,
        )
        summarize.add_retry(**retry_props)
        summarize.add_catch(mark_failed, result_path="$.error")

        commit = tasks.LambdaInvoke(
            self,
            "RenderAndCommit",
            lambda_function=self.fn_commit,
            payload_response_only=True,
        )
        commit.add_retry(**retry_props)
        commit.add_catch(mark_failed, result_path="$.error")

        stub = tasks.LambdaInvoke(
            self,
            "WriteStubNote",
            lambda_function=self.fn_stub,
            payload_response_only=True,
        )
        stub.add_retry(**retry_props)
        stub.add_catch(mark_failed, result_path="$.error")

        choice = (
            sfn.Choice(self, "HasTranscript")
            .when(
                sfn.Condition.boolean_equals("$.has_transcript", True),
                summarize.next(commit),
            )
            .otherwise(stub)
        )

        self.state_machine = sfn.StateMachine(
            self,
            "VideoPipeline",
            definition_body=sfn.DefinitionBody.from_chainable(fetch.next(choice)),
            state_machine_type=sfn.StateMachineType.STANDARD,
            timeout=Duration.minutes(30),
        )

        events.Rule(
            self,
            "PollSchedule",
            schedule=events.Schedule.rate(Duration.minutes(15)),
            targets=[targets.LambdaFunction(self.fn_poller)],
        )

        pipe_role = iam.Role(
            self,
            "PipeRole",
            assumed_by=iam.ServicePrincipal("pipes.amazonaws.com"),
        )
        self.queue.grant_consume_messages(pipe_role)
        self.state_machine.grant_start_execution(pipe_role)

        pipes.CfnPipe(
            self,
            "QueueToPipeline",
            role_arn=pipe_role.role_arn,
            source=self.queue.queue_arn,
            target=self.state_machine.state_machine_arn,
            source_parameters=pipes.CfnPipe.PipeSourceParametersProperty(
                sqs_queue_parameters=pipes.CfnPipe.PipeSourceSqsQueueParametersProperty(
                    batch_size=1
                )
            ),
            target_parameters=pipes.CfnPipe.PipeTargetParametersProperty(
                step_function_state_machine_parameters=(
                    pipes.CfnPipe.PipeTargetStateMachineParametersProperty(
                        invocation_type="FIRE_AND_FORGET"
                    )
                ),
                input_template='{"video_id": <$.body.video_id>}',
            ),
        )

        cloudwatch.Alarm(
            self,
            "PipelineFailures",
            metric=self.state_machine.metric_failed(period=Duration.minutes(15)),
            threshold=1,
            evaluation_periods=1,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
            alarm_description="A Video Vault pipeline execution failed.",
        )

        cloudwatch.Alarm(
            self,
            "DlqNotEmpty",
            metric=self.dlq.metric_approximate_number_of_messages_visible(
                period=Duration.minutes(15)
            ),
            threshold=1,
            evaluation_periods=1,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
            alarm_description="Pipes could not start an execution for a queued video.",
        )

        cloudwatch.Alarm(
            self,
            "PollerErrors",
            metric=self.fn_poller.metric_errors(period=Duration.minutes(30)),
            threshold=1,
            evaluation_periods=1,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
            alarm_description=(
                "The poller failed. Most likely cause: the Google OAuth refresh token "
                "expired because the consent screen is in Testing status."
            ),
        )

        # CloudWatch caps an alarm's Period * EvaluationPeriods at 604,800s (7 days),
        # so the alarm cannot watch a 30-day window. The dashboard widget can.
        transcript_calls_weekly = cloudwatch.Metric(
            namespace="VideoVault",
            metric_name="TranscriptCalls",
            statistic="Sum",
            period=Duration.days(7),
        )

        transcript_calls_monthly = cloudwatch.Metric(
            namespace="VideoVault",
            metric_name="TranscriptCalls",
            statistic="Sum",
            period=Duration.days(30),
        )

        cloudwatch.Alarm(
            self,
            "TranscriptBudget",
            metric=transcript_calls_weekly,
            threshold=20,
            evaluation_periods=1,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
            alarm_description=(
                "20 transcript API calls in the last 7 days, which is the weekly "
                "run rate that exhausts the roughly 100-per-month free tier. "
                "Switch TRANSCRIPT_PROVIDER to the proxy provider or upgrade the "
                "plan before it runs out."
            ),
        )

        dashboard = cloudwatch.Dashboard(self, "VideoVaultDashboard")
        dashboard.add_widgets(
            cloudwatch.GraphWidget(
                title="Pipeline executions",
                left=[
                    self.state_machine.metric_succeeded(),
                    self.state_machine.metric_failed(),
                ],
            ),
            cloudwatch.SingleValueWidget(
                title="Transcript calls (30d)", metrics=[transcript_calls_monthly]
            ),
            cloudwatch.GraphWidget(
                title="Poller invocations and errors",
                left=[self.fn_poller.metric_invocations(), self.fn_poller.metric_errors()],
            ),
        )
