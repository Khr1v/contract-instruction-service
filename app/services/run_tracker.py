from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Iterator


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class StageMetric:
    name: str
    started_at: str
    finished_at: str | None = None
    duration_seconds: float | None = None
    status: str = "running"
    error: str | None = None


@dataclass
class RunTracker:
    document_id: str
    filename: str
    source_channel: str
    external_user_id: str
    external_entity_id: str | None = None
    started_at: str = field(default_factory=utc_now_iso)
    finished_at: str | None = None
    status: str = "running"
    error: str | None = None
    source_format: str | None = None
    page_count: int | None = None
    quality_score: float | None = None
    human_review_required: bool = True
    warnings: list[str] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)
    artifacts: dict[str, str | None] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)
    stages: list[StageMetric] = field(default_factory=list)

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        metric = StageMetric(name=name, started_at=utc_now_iso())
        started = time.perf_counter()
        self.stages.append(metric)
        try:
            yield
        except Exception as exc:
            metric.status = "failed"
            metric.error = str(exc)
            raise
        finally:
            metric.finished_at = utc_now_iso()
            metric.duration_seconds = round(time.perf_counter() - started, 3)
            if metric.status != "failed":
                metric.status = "completed"

    def finish(self, status: str, *, error: str | None = None) -> None:
        self.status = status
        self.error = error
        self.finished_at = utc_now_iso()

    def to_dict(self) -> dict[str, Any]:
        started = datetime.fromisoformat(self.started_at)
        finished = datetime.fromisoformat(self.finished_at) if self.finished_at else datetime.now(UTC)
        return {
            "document_id": self.document_id,
            "filename": self.filename,
            "source_channel": self.source_channel,
            "external_user_id": self.external_user_id,
            "external_entity_id": self.external_entity_id,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_seconds": round((finished - started).total_seconds(), 3),
            "source_format": self.source_format,
            "page_count": self.page_count,
            "quality_score": self.quality_score,
            "human_review_required": self.human_review_required,
            "warnings": self.warnings,
            "risk_flags": self.risk_flags,
            "artifacts": self.artifacts,
            "extra": self.extra,
            "stages": [stage.__dict__ for stage in self.stages],
            "error": self.error,
        }

