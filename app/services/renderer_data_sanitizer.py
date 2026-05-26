from __future__ import annotations

import re
from copy import deepcopy
from typing import Any


EXECUTOR_MARKERS = (
    "маршал",
    "marshal",
    "маршалтим",
    "marshalteam",
    "экспедитор",
    "исполнитель",
)

CLIENT_ROLE_MARKERS = (
    "клиент",
    "заказчик",
    "грузовладелец",
    "грузоотправитель",
    "грузополучатель",
)


class RendererDataSanitizer:
    """Guardrails for side attribution before deterministic DOCX rendering."""

    def sanitize(self, payload: dict[str, object]) -> tuple[dict[str, object], list[str]]:
        clean = deepcopy(payload)
        warnings: list[str] = []

        for field in ("client_name", "contract_legal_entity"):
            value = self._text(clean.get(field))
            if self._looks_like_executor(value):
                clean[field] = ""
                warnings.append(f"{field}: удалено значение, похожее на Экспедитора/Исполнителя: {value}")

        rows = clean.get("communication_rows")
        if isinstance(rows, list):
            filtered = []
            removed = 0
            for row in rows:
                if not isinstance(row, dict):
                    continue
                haystack = " ".join(self._text(row.get(key)) for key in ("full_name", "role", "contacts", "responsibility"))
                if self._looks_like_executor_contact(haystack):
                    removed += 1
                    continue
                filtered.append(row)
            clean["communication_rows"] = filtered
            if removed:
                warnings.append(f"communication_rows: удалены контакты исполнителя/Маршал: {removed}")

        self._normalize_section_routing(clean, warnings)
        self._fill_client_document_contacts(clean, warnings)
        self._ensure_driver_briefing(clean, warnings)
        return clean, warnings

    def _normalize_section_routing(self, payload: dict[str, object], warnings: list[str]) -> None:
        penalties = self._str_list(payload.get("penalties"))
        incidents = self._str_list(payload.get("incident_actions"))
        document_requirements = self._str_list(payload.get("document_format_requirements"))

        loading = []
        moved_from_loading = 0
        for item in self._str_list(payload.get("loading_requirements")):
            lowered = item.casefold()
            if self._is_document_flow_item(lowered):
                self._append_unique(document_requirements, item)
                moved_from_loading += 1
                continue
            if self._is_penalty_item(lowered) and "просто" not in lowered:
                self._append_unique(penalties, item)
                moved_from_loading += 1
                continue
            loading.append(self._operationalize_loading_item(item))
        if moved_from_loading:
            warnings.append(f"loading_requirements: перенесены неоперационные пункты: {moved_from_loading}")

        unloading = [self._operationalize_unloading_item(item) for item in self._str_list(payload.get("unloading_requirements"))]

        special = []
        moved_from_special = 0
        for item in self._str_list(payload.get("special_conditions")):
            lowered = item.casefold()
            if self._is_document_flow_item(lowered):
                self._append_unique(document_requirements, item)
                moved_from_special += 1
                continue
            if self._is_damage_or_incident_item(lowered):
                self._append_unique(incidents, item)
                moved_from_special += 1
                continue
            if self._is_penalty_item(lowered):
                self._append_unique(penalties, item)
                moved_from_special += 1
                continue
            special.append(item)
        if moved_from_special:
            warnings.append(f"special_conditions: перенесены штрафы/документы/инциденты: {moved_from_special}")

        payload["loading_requirements"] = self._dedupe(loading)
        payload["unloading_requirements"] = self._dedupe(unloading)
        payload["special_conditions"] = self._dedupe(special)
        payload["penalties"] = self._dedupe(penalties)
        payload["incident_actions"] = self._dedupe(incidents)
        payload["document_format_requirements"] = self._dedupe(document_requirements)

    def _fill_client_document_contacts(self, payload: dict[str, object], warnings: list[str]) -> None:
        client_contact = self._text(payload.get("client_document_contact"))
        copies_email = self._text(payload.get("copies_email"))
        if client_contact and copies_email:
            return

        email = self._find_client_email(payload)
        if not email:
            return
        if not client_contact:
            payload["client_document_contact"] = f"Общий адрес клиента: {email}"
            warnings.append("client_document_contact: заполнено из контактов/реквизитов клиента")
        if not copies_email:
            payload["copies_email"] = email
            warnings.append("copies_email: заполнено из контактов/реквизитов клиента")

    def _ensure_driver_briefing(self, payload: dict[str, object], warnings: list[str]) -> None:
        current = self._str_list(payload.get("driver_briefing"))
        if current:
            payload["driver_briefing"] = self._dedupe(current)
            return

        platform_rows = payload.get("platform_rows")
        platform_rules = []
        if isinstance(platform_rows, list):
            platform_rules = [
                self._text(row.get("bidding_rules"))
                for row in platform_rows
                if isinstance(row, dict)
            ]
        haystack = "\n".join(
            [
                *self._str_list(payload.get("loading_requirements")),
                *self._str_list(payload.get("unloading_requirements")),
                *self._str_list(payload.get("incident_actions")),
                *self._str_list(payload.get("special_conditions")),
                *self._str_list(payload.get("penalties")),
                *platform_rules,
            ]
        ).casefold()
        briefing: list[str] = []
        if "доверен" in haystack:
            briefing.append("До погрузки проверить наличие доверенности/заявки и передать документы Клиенту в установленный срок.")
        if any(marker in haystack for marker in ("упаков", "уклад", "креп", "ось", "размещ")):
            briefing.append("На погрузке проверить упаковку, укладку, крепление и рациональное размещение груза; замечания зафиксировать в товаросопроводительных документах.")
        if any(marker in haystack for marker in ("задерж", "авари", "прост", "проблем")):
            briefing.append("При задержке, простое, аварии или проблеме на погрузке/выгрузке сразу сообщить логисту и зафиксировать подтверждающие документы.")
        if "склад" in haystack or "водител" in haystack:
            briefing.append("На территории склада соблюдать правила Клиента и не допускать действий, которые могут привести к претензии или штрафу.")
        if any(marker in haystack for marker in ("таймслот", "срок", "прибыт")):
            briefing.append("Контролировать время прибытия/убытия и соблюдение таймслота; отклонения сразу передавать логисту.")

        if briefing:
            payload["driver_briefing"] = self._dedupe(briefing)
            warnings.append("driver_briefing: сформирован операционный чек-лист из условий договора")

    def _operationalize_loading_item(self, item: str) -> str:
        lowered = item.casefold()
        if "своевременную передачу груза" in lowered or "надлежащей таре" in lowered:
            return "Проверить, что груз передан к перевозке в надлежащей таре и упаковке."
        if "норматив" in lowered and "прост" in lowered:
            return "Контролировать нормативный простой на погрузке/разгрузке 24 часа; при превышении зафиксировать время простоя и передать логисту."
        if "содейств" in lowered and ("ось" in lowered or "размещ" in lowered):
            return "Проконтролировать рациональное размещение груза и нагрузку по осям подвижного состава."
        return item

    def _operationalize_unloading_item(self, item: str) -> str:
        lowered = item.casefold()
        if "норматив" in lowered and "прост" in lowered:
            return "На выгрузке контролировать нормативный простой 24 часа; при превышении зафиксировать простой и передать логисту."
        return item

    def _looks_like_executor_contact(self, text: str) -> bool:
        lowered = text.casefold()
        if not lowered:
            return False
        if self._looks_like_executor(lowered):
            return True
        if "info@marshalteam" in lowered or "marshalteam.ru" in lowered:
            return True
        if re.search(r"генеральн(?:ый|ого)\s+директор", lowered) and "маршал" in lowered:
            return True
        return False

    def _looks_like_executor(self, text: str) -> bool:
        lowered = text.casefold()
        if not lowered:
            return False
        has_executor = any(marker in lowered for marker in EXECUTOR_MARKERS)
        has_client = any(marker in lowered for marker in CLIENT_ROLE_MARKERS)
        if "маршал" in lowered or "marshal" in lowered:
            return True
        return has_executor and not has_client

    def _is_document_flow_item(self, lowered: str) -> bool:
        if any(marker in lowered for marker in ("замечан", "отмет", "запись")) and any(
            marker in lowered for marker in ("ттн", "товаросопровод")
        ):
            return False
        return any(
            marker in lowered
            for marker in (
                "документ",
                "реестр",
                "счет",
                "счёт",
                "упд",
                "акт",
                "эдо",
                "электронн",
                "оригинал",
                "копи",
                "отчетн",
                "отчётн",
                "закрыва",
            )
        )

    def _is_penalty_item(self, lowered: str) -> bool:
        return any(
            marker in lowered
            for marker in (
                "штраф",
                "пен",
                "неустой",
                "удерж",
                "санкц",
                "500 000",
                "50%",
                "20%",
                "0,1%",
                "1000 руб",
            )
        )

    def _is_damage_or_incident_item(self, lowered: str) -> bool:
        return any(marker in lowered for marker in ("возмещает ущерб", "ущерб от действий", "госорган", "претенз"))

    def _find_client_email(self, payload: dict[str, object]) -> str:
        candidates: list[str] = []
        for field in ("client_document_contact", "copies_email"):
            candidates.append(self._text(payload.get(field)))
        rows = payload.get("communication_rows")
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, dict):
                    candidates.append(self._text(row.get("contacts")))
        candidates.append(self._text(payload.get("originals_postal_address")))
        for candidate in candidates:
            for email in re.findall(r"[\w.\-+]+@[\w.\-]+\.\w+", candidate):
                if not self._looks_like_executor_contact(email):
                    return email
        return ""

    def _str_list(self, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [self._text(item) for item in value if self._text(item)]
        text = self._text(value)
        return [text] if text else []

    def _append_unique(self, target: list[str], item: str) -> None:
        if item and item not in target:
            target.append(item)

    def _dedupe(self, values: list[str]) -> list[str]:
        result: list[str] = []
        for value in values:
            self._append_unique(result, value)
        return result

    def _text(self, value: Any) -> str:
        if value is None:
            return ""
        return str(value).strip()
