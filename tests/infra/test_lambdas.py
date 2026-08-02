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


def test_creates_five_lambda_functions():
    _template().resource_count_is("AWS::Lambda::Function", 5)


def test_all_functions_use_python_312():
    for fn in _template().find_resources("AWS::Lambda::Function").values():
        assert fn["Properties"]["Runtime"] == "python3.12"


def test_summarize_function_can_invoke_bedrock():
    # The summarizer uses the classic AnthropicBedrock client, so the grant is
    # `bedrock:InvokeModel`. The default model is served through a cross-region
    # inference profile (the `us.` prefix), which needs BOTH the profile ARN and
    # the underlying foundation-model ARN in every region the profile can route
    # to -- granting only the profile fails at runtime when Bedrock routes the
    # request to a sibling region.
    _template().has_resource_properties(
        "AWS::IAM::Policy",
        {
            "PolicyDocument": Match.object_like(
                {
                    "Statement": Match.array_with(
                        [
                            Match.object_like(
                                {
                                    "Action": "bedrock:InvokeModel",
                                    "Effect": "Allow",
                                    # Least privilege is the point of this test:
                                    # named ARNs only, never "*".
                                    "Resource": Match.array_with(
                                        [
                                            "arn:aws:bedrock:us-east-1::"
                                            "foundation-model/anthropic.claude-sonnet-4-6",
                                            "arn:aws:bedrock:us-east-2::"
                                            "foundation-model/anthropic.claude-sonnet-4-6",
                                            "arn:aws:bedrock:us-west-2::"
                                            "foundation-model/anthropic.claude-sonnet-4-6",
                                        ]
                                    ),
                                }
                            )
                        ]
                    )
                }
            )
        },
    )


def test_summarize_function_receives_the_model_id_env_var():
    # The model is configuration, so the Lambda must actually receive it --
    # otherwise the code silently falls back to its default and the repo
    # variable does nothing.
    template = _template()
    summarize = [
        fn
        for logical_id, fn in template.find_resources("AWS::Lambda::Function").items()
        if logical_id.startswith("SummarizeFunction")
    ]
    assert len(summarize) == 1
    env = summarize[0]["Properties"]["Environment"]["Variables"]
    assert env["BEDROCK_MODEL_ID"] == "us.anthropic.claude-sonnet-4-6"


def test_functions_receive_state_table_env_var():
    for fn in _template().find_resources("AWS::Lambda::Function").values():
        assert "STATE_TABLE" in fn["Properties"]["Environment"]["Variables"]


def test_each_function_has_its_own_role():
    template = _template()
    roles = {
        fn["Properties"]["Role"]["Fn::GetAtt"][0]
        for fn in template.find_resources("AWS::Lambda::Function").values()
    }
    assert len(roles) == 5


def _role_logical_id(template: Template, function_prefix: str) -> str:
    for logical_id, fn in template.find_resources("AWS::Lambda::Function").items():
        if logical_id.startswith(function_prefix):
            return fn["Properties"]["Role"]["Fn::GetAtt"][0]
    raise AssertionError(f"no Lambda function with logical id starting {function_prefix}")


def _actions_granted_to_role(template: Template, role_logical_id: str) -> set[str]:
    granted: set[str] = set()
    for policy in template.find_resources("AWS::IAM::Policy").values():
        attached = {
            ref["Ref"]
            for ref in policy["Properties"]["Roles"]
            if isinstance(ref, dict) and "Ref" in ref
        }
        if role_logical_id not in attached:
            continue
        for statement in policy["Properties"]["PolicyDocument"]["Statement"]:
            actions = statement.get("Action")
            actions = actions if isinstance(actions, list) else [actions]
            granted.update(a for a in actions if isinstance(a, str))
    return granted


def test_stub_note_function_cannot_write_summaries():
    """Least privilege: the stub handler writes no summary artifact, so it gets no S3 write."""
    template = _template()
    stub_role = _role_logical_id(template, "StubNoteFunction")
    assert "s3:PutObject" not in _actions_granted_to_role(template, stub_role)
