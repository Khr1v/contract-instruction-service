from __future__ import annotations

import json
import re
from typing import Any

import orjson
from langchain_core.utils.json import parse_partial_json


def parse_json_object(text: str) -> dict[str, Any]:
    """Parse a JSON object from raw LLM output."""

    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
    try:
        payload = orjson.loads(cleaned)
    except orjson.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if match:
            candidate = match.group(0)
        elif "{" in cleaned:
            candidate = cleaned[cleaned.find("{") :]
        else:
            raise
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            payload = parse_partial_json(candidate)
    if not isinstance(payload, dict):
        raise ValueError("Expected a JSON object")
    return payload
