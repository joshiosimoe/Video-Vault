from __future__ import annotations

from functools import lru_cache

import boto3


@lru_cache(maxsize=32)
def get_parameter(name: str, ssm_client=None) -> str:
    client = ssm_client or boto3.client("ssm")
    response = client.get_parameter(Name=name, WithDecryption=True)
    return response["Parameter"]["Value"]
