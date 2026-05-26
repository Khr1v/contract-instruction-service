from __future__ import annotations

import logging
import time
from typing import Any
import base64
from contextvars import ContextVar, Token

from openai import OpenAI, OpenAIError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)


class EmptyLLMResponseError(RuntimeError):
    """Raised when the provider returns HTTP 200 but no usable text."""


class YandexLLMClient:
    """OpenAI-compatible client for Yandex Cloud foundation models."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._client: OpenAI | None = None
        self.usage_records: list[dict[str, Any]] = []
        self._usage_scope: ContextVar[list[dict[str, Any]] | None] = ContextVar(
            "yandex_usage_scope",
            default=None,
        )

    @property
    def client(self) -> OpenAI:
        if not self.settings.yandex_cloud_api_key:
            raise RuntimeError("YANDEX_CLOUD_API_KEY is not configured")
        if self._client is None:
            self._client = OpenAI(
                api_key=self.settings.yandex_cloud_api_key,
                base_url=self.settings.yandex_base_url,
                project=self.settings.yandex_cloud_folder,
                default_headers={
                    "x-data-logging-enabled": "true" if self.settings.yandex_data_logging_enabled else "false",
                },
            )
        return self._client

    @retry(
        retry=retry_if_exception_type((OpenAIError, TimeoutError, ConnectionError, EmptyLLMResponseError)),
        wait=wait_exponential(multiplier=1, min=1, max=20),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    def generate_text(
        self,
        *,
        instructions: str,
        input: str,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
        model_name: str | None = None,
    ) -> str:
        model = f"gpt://{self.settings.yandex_cloud_folder}/{model_name or self.settings.yandex_cloud_model}"
        request_temperature = self.settings.llm_temperature if temperature is None else temperature
        request_max_tokens = self.settings.llm_max_output_tokens if max_output_tokens is None else max_output_tokens
        started = time.perf_counter()
        try:
            response = self.client.responses.create(
                model=model,
                temperature=request_temperature,
                instructions=instructions,
                input=input,
                max_output_tokens=request_max_tokens,
            )
        except Exception:
            duration = time.perf_counter() - started
            logger.exception("Yandex LLM request failed after %.2fs", duration)
            raise
        text = self._extract_response_text(response).strip()
        duration = time.perf_counter() - started
        self._record_usage(response, model_name or self.settings.yandex_cloud_model, duration, "text")
        if not text:
            logger.warning(
                "Yandex LLM returned HTTP 200 but empty text after %.2fs model=%s response=%s",
                duration,
                self.settings.yandex_cloud_model,
                self._response_debug_summary(response),
            )
            raise EmptyLLMResponseError("Yandex LLM returned empty text")
        logger.info("Yandex LLM request completed in %.2fs model=%s", duration, model_name or self.settings.yandex_cloud_model)
        return text

    @retry(
        retry=retry_if_exception_type((OpenAIError, TimeoutError, ConnectionError, EmptyLLMResponseError)),
        wait=wait_exponential(multiplier=1, min=1, max=20),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    def generate_text_from_image(
        self,
        *,
        instructions: str,
        prompt: str,
        image_bytes: bytes,
        mime_type: str = "image/png",
        temperature: float | None = None,
        max_output_tokens: int | None = None,
    ) -> str:
        model = f"gpt://{self.settings.yandex_cloud_folder}/{self.settings.yandex_cloud_model}"
        request_temperature = self.settings.llm_temperature if temperature is None else temperature
        request_max_tokens = self.settings.llm_max_output_tokens if max_output_tokens is None else max_output_tokens
        image_base64 = base64.b64encode(image_bytes).decode("ascii")
        data_url = f"data:{mime_type};base64,{image_base64}"
        started = time.perf_counter()
        try:
            response = self.client.responses.create(
                model=model,
                temperature=request_temperature,
                instructions=instructions,
                input=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": prompt},
                            {"type": "input_image", "image_url": data_url},
                        ],
                    }
                ],
                max_output_tokens=request_max_tokens,
            )
        except Exception:
            duration = time.perf_counter() - started
            logger.exception("Yandex image LLM request failed after %.2fs", duration)
            raise
        text = self._extract_response_text(response).strip()
        duration = time.perf_counter() - started
        self._record_usage(response, self.settings.yandex_cloud_model, duration, "image")
        if not text:
            logger.warning(
                "Yandex image LLM returned HTTP 200 but empty text after %.2fs model=%s response=%s",
                duration,
                self.settings.yandex_cloud_model,
                self._response_debug_summary(response),
            )
            raise EmptyLLMResponseError("Yandex image LLM returned empty text")
        logger.info("Yandex image LLM request completed in %.2fs model=%s", duration, self.settings.yandex_cloud_model)
        return text

    def _extract_response_text(self, response: Any) -> str:
        """Extract text from OpenAI SDK Responses objects and compatible provider variants."""

        output_text = getattr(response, "output_text", None)
        if isinstance(output_text, str) and output_text.strip():
            return output_text

        parts: list[str] = []
        output = getattr(response, "output", None)
        if output:
            self._collect_text(output, parts)

        if not parts and hasattr(response, "model_dump"):
            self._collect_text(response.model_dump(mode="json"), parts)
        elif not parts and isinstance(response, dict):
            self._collect_text(response, parts)

        return "\n".join(part for part in parts if part.strip())

    def _collect_text(self, value: Any, parts: list[str]) -> None:
        if value is None:
            return
        if isinstance(value, str):
            if value.strip():
                parts.append(value)
            return
        if isinstance(value, (list, tuple)):
            for item in value:
                self._collect_text(item, parts)
            return
        if isinstance(value, dict):
            for key in ("output_text", "output", "choices", "text", "content"):
                if key in value:
                    self._collect_text(value[key], parts)
            if "message" in value:
                self._collect_text(value["message"], parts)
            return

        for attr in ("text", "content", "message"):
            if hasattr(value, attr):
                self._collect_text(getattr(value, attr), parts)

    def _response_debug_summary(self, response: Any) -> str:
        if not self.settings.yandex_data_logging_enabled:
            return "<redacted: YANDEX_DATA_LOGGING_ENABLED=false>"
        try:
            if hasattr(response, "model_dump"):
                payload = response.model_dump(mode="json")
            elif isinstance(response, dict):
                payload = response
            else:
                payload = {"type": type(response).__name__, "repr": repr(response)}
            return str(self._truncate_debug_payload(payload))[:2000]
        except Exception as exc:
            return f"<failed to summarize response: {exc}>"

    def _truncate_debug_payload(self, value: Any, max_string: int = 400) -> Any:
        if isinstance(value, str):
            return value[:max_string]
        if isinstance(value, list):
            return [self._truncate_debug_payload(item, max_string) for item in value[:5]]
        if isinstance(value, dict):
            return {
                key: self._truncate_debug_payload(item, max_string)
                for key, item in list(value.items())[:20]
                if key not in {"api_key", "authorization"}
            }
        return value

    def start_usage_scope(self) -> Token[list[dict[str, Any]] | None]:
        """Start per-run usage accounting while keeping global records for logs/debug."""

        return self._usage_scope.set([])

    def finish_usage_scope(self, token: Token[list[dict[str, Any]] | None]) -> dict[str, Any]:
        records = self._usage_scope.get() or []
        summary = self.usage_summary(records)
        self._usage_scope.reset(token)
        return summary

    def reset_usage(self) -> None:
        self.usage_records.clear()

    def usage_summary(self, records: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        scoped_records = records
        if scoped_records is None:
            scoped_records = self._usage_scope.get()
        records_to_summarize = scoped_records if scoped_records is not None else self.usage_records
        totals = {
            "input_tokens": 0,
            "cached_tokens": 0,
            "output_tokens": 0,
            "reasoning_tokens": 0,
            "total_tokens": 0,
            "estimated_cost_usd": 0.0,
            "estimated_cost_rub": 0.0,
        }
        by_model: dict[str, dict[str, float | int]] = {}
        for record in records_to_summarize:
            usage = record.get("usage") or {}
            model = str(record.get("model") or "unknown")
            model_totals = by_model.setdefault(
                model,
                {
                    "requests": 0,
                    "input_tokens": 0,
                    "cached_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": 0,
                    "estimated_cost_rub": 0.0,
                    "estimated_cost_usd": 0.0,
                },
            )
            model_totals["requests"] = int(model_totals["requests"]) + 1
            model_totals["input_tokens"] = int(model_totals["input_tokens"]) + int(usage.get("input_tokens") or 0)
            model_totals["cached_tokens"] = int(model_totals["cached_tokens"]) + int(usage.get("cached_tokens") or 0)
            model_totals["output_tokens"] = int(model_totals["output_tokens"]) + int(usage.get("output_tokens") or 0)
            model_totals["total_tokens"] = int(model_totals["total_tokens"]) + int(usage.get("total_tokens") or 0)
            model_totals["estimated_cost_rub"] = float(model_totals["estimated_cost_rub"]) + float(
                record.get("estimated_cost_rub") or 0.0
            )
            model_totals["estimated_cost_usd"] = float(model_totals["estimated_cost_usd"]) + float(
                record.get("estimated_cost_usd") or 0.0
            )
            totals["input_tokens"] += int(usage.get("input_tokens") or 0)
            totals["cached_tokens"] += int(usage.get("cached_tokens") or 0)
            totals["output_tokens"] += int(usage.get("output_tokens") or 0)
            totals["reasoning_tokens"] += int(usage.get("reasoning_tokens") or 0)
            totals["total_tokens"] += int(usage.get("total_tokens") or 0)
            totals["estimated_cost_usd"] += float(record.get("estimated_cost_usd") or 0.0)
            totals["estimated_cost_rub"] += float(record.get("estimated_cost_rub") or 0.0)
        totals["estimated_cost_usd"] = round(totals["estimated_cost_usd"], 6)
        totals["estimated_cost_rub"] = round(totals["estimated_cost_rub"], 2)
        for model_totals in by_model.values():
            model_totals["estimated_cost_rub"] = round(float(model_totals["estimated_cost_rub"]), 2)
            model_totals["estimated_cost_usd"] = round(float(model_totals["estimated_cost_usd"]), 6)
        return {"requests": records_to_summarize, "totals": totals, "by_model": by_model}

    def _record_usage(self, response: Any, model_name: str, duration_seconds: float, request_type: str) -> None:
        usage = self._extract_usage(response)
        estimated_cost = self._estimate_cost_usd(model_name, usage)
        estimated_cost_rub = self._estimate_cost_rub(model_name, usage)
        record = {
            "model": model_name,
            "request_type": request_type,
            "duration_seconds": round(duration_seconds, 3),
            "usage": usage,
            "estimated_cost_usd": estimated_cost,
            "estimated_cost_rub": estimated_cost_rub,
        }
        self.usage_records.append(record)
        scoped_records = self._usage_scope.get()
        if scoped_records is not None:
            scoped_records.append(record)
        if usage:
            logger.info(
                "Yandex usage model=%s type=%s input=%s cached=%s output=%s total=%s estimated_cost_rub=%s estimated_cost_usd=%s",
                model_name,
                request_type,
                usage.get("input_tokens"),
                usage.get("cached_tokens"),
                usage.get("output_tokens"),
                usage.get("total_tokens"),
                estimated_cost_rub,
                estimated_cost,
            )

    def _extract_usage(self, response: Any) -> dict[str, int | None]:
        payload: dict[str, Any]
        if hasattr(response, "model_dump"):
            payload = response.model_dump(mode="json")
        elif isinstance(response, dict):
            payload = response
        else:
            return {}
        usage = payload.get("usage")
        if not isinstance(usage, dict):
            return {}
        input_details = usage.get("input_tokens_details") if isinstance(usage.get("input_tokens_details"), dict) else {}
        output_details = usage.get("output_tokens_details") if isinstance(usage.get("output_tokens_details"), dict) else {}
        return {
            "input_tokens": usage.get("input_tokens"),
            "cached_tokens": input_details.get("cached_tokens", 0),
            "output_tokens": usage.get("output_tokens"),
            "reasoning_tokens": output_details.get("reasoning_tokens", 0),
            "total_tokens": usage.get("total_tokens"),
        }

    def _estimate_cost_usd(self, model_name: str, usage: dict[str, int | None]) -> float | None:
        if not usage:
            return None
        rates = self._pricing_rates(model_name)
        input_tokens = int(usage.get("input_tokens") or 0)
        cached_tokens = int(usage.get("cached_tokens") or 0)
        output_tokens = int(usage.get("output_tokens") or 0)
        billable_input = max(input_tokens - cached_tokens, 0)
        cost = (
            billable_input * rates["input_per_1k"] / 1000
            + cached_tokens * rates["cached_per_1k"] / 1000
            + output_tokens * rates["output_per_1k"] / 1000
        )
        return round(cost, 6)

    def _estimate_cost_rub(self, model_name: str, usage: dict[str, int | None]) -> float | None:
        if not usage:
            return None
        rates = self._pricing_rates_rub(model_name)
        input_tokens = int(usage.get("input_tokens") or 0)
        cached_tokens = int(usage.get("cached_tokens") or 0)
        output_tokens = int(usage.get("output_tokens") or 0)
        billable_input = max(input_tokens - cached_tokens, 0)
        cost = (
            billable_input * rates["input_per_1k"] / 1000
            + cached_tokens * rates["cached_per_1k"] / 1000
            + output_tokens * rates["output_per_1k"] / 1000
        )
        return round(cost, 2)

    def _pricing_rates_rub(self, model_name: str) -> dict[str, float]:
        normalized = model_name.lower()
        if "235b" in normalized:
            return {"input_per_1k": 0.5, "cached_per_1k": 0.5, "output_per_1k": 0.5}
        if "qwen3.6" in normalized and "35b" in normalized:
            return {"input_per_1k": 0.2, "cached_per_1k": 0.05, "output_per_1k": 0.3}
        return {"input_per_1k": 0.2, "cached_per_1k": 0.05, "output_per_1k": 0.3}

    def _pricing_rates(self, model_name: str) -> dict[str, float]:
        normalized = model_name.lower()
        if "235b" in normalized:
            return {"input_per_1k": 0.00409836, "cached_per_1k": 0.00409836, "output_per_1k": 0.00409836}
        if "qwen3.6" in normalized and "35b" in normalized:
            return {"input_per_1k": 0.001639344, "cached_per_1k": 0.000409836, "output_per_1k": 0.002459016}
        return {"input_per_1k": 0.001639344, "cached_per_1k": 0.000409836, "output_per_1k": 0.002459016}
