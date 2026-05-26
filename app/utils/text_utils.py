from __future__ import annotations

import re


def compact_whitespace(text: str) -> str:
    return re.sub(r"[ \t]+", " ", text).strip()


def trim_for_prompt(text: str, max_chars: int = 120_000) -> str:
    if len(text) <= max_chars:
        return text
    head = text[: max_chars // 2]
    tail = text[-max_chars // 2 :]
    return f"{head}\n\n[...ТЕКСТ СОКРАЩЕН ДЛЯ PROMPT...]\n\n{tail}"

