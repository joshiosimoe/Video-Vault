from __future__ import annotations

import json
import time

NAMESPACE = "VideoVault"


def emit_count(name: str, value: int = 1, **properties) -> None:
    """Write a CloudWatch Embedded Metric Format record to stdout.

    CloudWatch Logs extracts this into a real metric with no PutMetricData
    call and no additional IAM permission.
    """
    record = {
        "_aws": {
            "Timestamp": int(time.time() * 1000),
            "CloudWatchMetrics": [
                {
                    "Namespace": NAMESPACE,
                    "Dimensions": [[]],
                    "Metrics": [{"Name": name, "Unit": "Count"}],
                }
            ],
        },
        name: value,
        **properties,
    }
    print(json.dumps(record))
