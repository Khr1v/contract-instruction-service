from __future__ import annotations


def estimate_text_quality(text: str, min_chars: int = 500) -> float:
    stripped = text.strip()
    if not stripped:
        return 0.0
    length_score = min(len(stripped) / min_chars, 1.0)
    replacement_penalty = min(stripped.count("�") / max(len(stripped), 1), 0.5)
    alpha_count = sum(char.isalpha() for char in stripped)
    alpha_score = min(alpha_count / max(len(stripped), 1) * 1.5, 1.0)
    return max(0.0, min((length_score * 0.6 + alpha_score * 0.4) - replacement_penalty, 1.0))

