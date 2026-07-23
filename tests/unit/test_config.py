import boto3
import pytest
from moto import mock_aws

from src.shared import config


@pytest.fixture(autouse=True)
def clear_cache():
    config.get_parameter.cache_clear()
    yield
    config.get_parameter.cache_clear()


@mock_aws
def test_get_parameter_decrypts_secure_string():
    client = boto3.client("ssm", region_name="us-east-1")
    client.put_parameter(Name="/vv/token", Value="s3cret", Type="SecureString")
    assert config.get_parameter("/vv/token", ssm_client=client) == "s3cret"


@mock_aws
def test_get_parameter_is_cached():
    client = boto3.client("ssm", region_name="us-east-1")
    client.put_parameter(Name="/vv/token", Value="first", Type="SecureString")
    assert config.get_parameter("/vv/token", ssm_client=client) == "first"

    client.put_parameter(Name="/vv/token", Value="second", Type="SecureString", Overwrite=True)
    assert config.get_parameter("/vv/token", ssm_client=client) == "first"
