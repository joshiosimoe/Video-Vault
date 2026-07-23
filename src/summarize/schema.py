SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {
            "type": "string",
            "description": (
                "One sentence: is this worth watching, and if only partly, "
                "which timestamp range matters."
            ),
        },
        "tldr": {
            "type": "string",
            "description": "Exactly three sentences covering the argument and audience.",
        },
        "takeaways": {
            "type": "array",
            "description": "Five to eight concrete takeaways.",
            "items": {"type": "string"},
        },
        "sections": {
            "type": "array",
            "description": "Chronological outline of the video.",
            "items": {
                "type": "object",
                "properties": {
                    "start_seconds": {
                        "type": "integer",
                        "description": "Start offset in whole seconds from video start.",
                    },
                    "title": {"type": "string"},
                    "summary": {"type": "string"},
                },
                "required": ["start_seconds", "title", "summary"],
                "additionalProperties": False,
            },
        },
        "tags": {
            "type": "array",
            "description": "Three to six lowercase topic tags, no spaces.",
            "items": {"type": "string"},
        },
    },
    "required": ["verdict", "tldr", "takeaways", "sections", "tags"],
    "additionalProperties": False,
}
