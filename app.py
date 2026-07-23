#!/usr/bin/env python3
import aws_cdk as cdk

from infra.pipeline_stack import VideoVaultStack

app = cdk.App()
VideoVaultStack(app, "VideoVaultStack")
app.synth()
