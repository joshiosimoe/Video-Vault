import aws_cdk as cdk
from aws_cdk.assertions import Template

from infra.pipeline_stack import VideoVaultStack


def test_stack_synthesizes():
    app = cdk.App()
    stack = VideoVaultStack(app, "TestStack")
    template = Template.from_stack(stack)
    assert template.to_json() is not None
