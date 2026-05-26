# Agents And Components

Сервис строится как channel-agnostic backend. Telegram и Bitrix не содержат бизнес-логику договора; они только передают файл в `ContractPipeline` и возвращают результат пользователю или внешней системе.

## 1. Document Intake Agent

Назначение: принять файл из Telegram, Bitrix или API, сохранить исходник и создать запись в БД.

Ответственность:
- проверить, что файл физически получен;
- сохранить исходник в `data/uploads`;
- создать запись `documents`;
- передать локальный путь в `ContractPipeline`.

Не делает:
- не анализирует договор;
- не извлекает условия;
- не вызывает LLM напрямую.

Основные файлы:
- `app/services/file_storage.py`
- `app/db/repository.py`
- `app/integrations/*`

## 2. Document Router Agent

Назначение: определить тип документа и выбрать extractor.

Типы:
- `docx`;
- `pdf_text`;
- `pdf_scan`;
- `pdf_mixed`;
- `unsupported`.

Правила:
- DOCX определяется по расширению и обрабатывается только DOCX extractor;
- PDF проверяется на наличие извлекаемого текста постранично;
- если текста нет или его слишком мало, выбирается OCR/VLM extractor;
- если часть страниц текстовая, а часть похожа на скан, тип `pdf_mixed` и mixed extractor отправляет низкотекстовые страницы в OCR/VLM.

Основной файл: `app/documents/router.py`.

## 3. DOCX Extraction Agent

Назначение: извлечь текст, параграфы и таблицы из DOCX.

Правила:
- использовать `python-docx`, не OCR;
- сохранять порядок блоков;
- таблицы переводить в Markdown;
- изображения отмечать warning;
- tracked changes/comments отмечать warning;
- вернуть `CanonicalDocument`.

Основной файл: `app/documents/docx_extractor.py`.

## 4. PDF Text Extraction Agent

Назначение: извлечь текст из digital PDF.

Правила:
- использовать PyMuPDF;
- сохранять `page_1`, `page_2`, ...;
- считать quality score;
- если текста мало, добавлять warnings;
- вернуть `CanonicalDocument`.

Основной файл: `app/documents/pdf_text_extractor.py`.

## 5. PDF OCR / VLM Extraction Agent

Назначение: обработать scanned PDF.

Текущее состояние MVP:
- страницы рендерятся через PyMuPDF в PNG bytes;
- OCR/VLM provider выделен интерфейсом `OCRProvider`;
- default provider — stub, который возвращает понятный warning;
- можно подключить Yandex image input, OpenAI-compatible image input, pytesseract или easyocr без изменения pipeline.

Правила:
- каждая страница получает `page_N`;
- плохое качество OCR должно приводить к `human_review_required`;
- OCR не должен придумывать текст.

Основной файл: `app/documents/pdf_ocr_extractor.py`.

## 6. Template RAG Agent

Назначение: хранить и извлекать шаблон инструкции, внутренние правила и примеры.

Критичное правило:
- полный шаблон всегда берется из `data/templates/instruction_template.md`;
- retrieval используется для правил и похожих примеров;
- шаблон индексируется в Chroma для поиска, но финальная генерация получает полный файл шаблона.

Основные файлы:
- `app/rag/index_templates.py`
- `app/rag/retriever.py`
- `app/rag/vectorstore.py`
- `scripts/index_rag.py`

## 7. Contract Facts Extraction Agent

Назначение: извлечь структурированные факты договора в JSON.

Правила:
- использовать только `CanonicalDocument`;
- не придумывать условия;
- для важных полей указывать `source_ref`, `source_quote`, `confidence`, `needs_human_review`;
- штрафы, пени, сроки, оплату, ЭДО, документооборот, ответственность и приложения извлекать особенно внимательно;
- если данных нет, ставить `null` и comment: `Уточнить у человека`;
- возвращать только валидный JSON.

Основные файлы:
- `app/llm/chains.py`
- `app/llm/prompts.py`
- `app/llm/schemas.py`

## 8. Contract Validation Agent

Назначение: проверить JSON до генерации инструкции.

Проверяет:
- номер договора;
- дату;
- клиента;
- исполнителя;
- предмет;
- срок действия;
- оплату;
- ответственность/штрафы/пени или явную пометку, что не найдено;
- ЭДО/документооборот или явную пометку;
- приложения или явную пометку;
- `source_ref` у важных полей;
- большое количество `low confidence`.

Результат:
- warnings;
- problems;
- `human_review_required`.

Основной файл: `app/services/validation_service.py`.

## 9. Instruction Generation Agent

Назначение: создать рабочую инструкцию для сотрудников по полному шаблону.

Правила:
- строго следовать структуре шаблона;
- не добавлять факты вне `contract_facts_json`;
- отсутствующие данные писать как `Уточнить у человека`;
- штрафы, пени и ответственность выносить в отдельный заметный раздел;
- risk_flags включать в раздел рисков;
- писать на русском, четко и без юридических фантазий.

Основные файлы:
- `app/services/instruction_service.py`
- `app/llm/chains.py`

## 10. Instruction Validation Agent

Назначение: проверить готовую инструкцию.

Проверяет:
- наличие всех обязательных разделов;
- наличие раздела "9. Штрафы";
- наличие раздела "11. Документооборот";
- сохранение Markdown-таблиц из DOCX-шаблона;
- наличие "Уточнить у человека", если есть missing_information;
- отсутствие явных потерь санкций.

Может использовать:
- кодовую проверку;
- LLM reviewer через тот же Qwen3.6-35B;
- будущую fallback/reviewer модель.

Основные файлы:
- `app/services/validation_service.py`
- `app/llm/chains.py`

## 11. Human Review Agent

Назначение: сформировать финальный флаг и предупреждения для человека.

Ставит `human_review_required = true`, если:
- extraction quality низкий;
- OCR/VLM не подключен для scanned PDF;
- есть critical validation problems;
- есть risk_flags;
- много low confidence;
- инструкция не прошла validation.

Результат возвращается в `ProcessingResult` и сохраняется в `validation_result.json`.

Основной файл: `app/services/contract_pipeline.py`.

## 12. Telegram Test Adapter

Назначение: быстрый тестовый интерфейс.

Поведение:
- принимает PDF/DOCX;
- скачивает файл;
- вызывает `ContractPipeline`;
- отправляет статусы и результат;
- отправляет итоговую инструкцию `.docx`;
- отправляет администратору краткий отчет по `run_report.json`, если заполнен `ADMIN_IDS`;
- если `human_review_required`, явно пишет, что нужна проверка человеком.

Не делает:
- не содержит бизнес-логику;
- не парсит договор;
- не формирует инструкцию сам.

Основные файлы:
- `app/bot/handlers.py`
- `app/integrations/telegram_adapter.py`

## 13. Bitrix Future Adapter

Назначение: будущий production-интерфейс для Bitrix24.

Планируемый поток:
- принять договор из сделки;
- скачать файл договора;
- запустить `ContractPipeline`;
- вернуть инструкцию в сделку;
- прикрепить файл `<filename>_instruction.docx`;
- написать комментарий в timeline;
- приложить краткую сводку из `run_report.json`;
- поставить статус обработки в поле сделки.

Текущее состояние:
- FastAPI webhook scaffold уже есть;
- глубокая авторизация, Bitrix REST client, upload и timeline API оставлены как TODO;
- pipeline не зависит от Bitrix.

Основные файлы:
- `app/api/bitrix_routes.py`
- `app/integrations/bitrix_adapter.py`

## End-To-End Flow

1. Adapter получает файл.
2. `ContractPipeline.process_contract()` сохраняет upload и создает запись БД.
3. `DocumentRouter` выбирает extractor.
4. Extractor возвращает `CanonicalDocument`.
5. Pipeline сохраняет `canonical_document.json` и `extracted_text.txt`.
6. `TemplateRAGAgent` возвращает полный шаблон и релевантные правила/примеры.
7. `ContractFactExtractor` возвращает `ContractFacts`.
8. `ValidationService` проверяет JSON.
9. `InstructionGenerator` создает Markdown-инструкцию.
10. `InstructionValidator` и LLM reviewer проверяют результат.
11. Pipeline сохраняет `contract_facts.json`, `instruction.md`, DOCX, `validation_result.json` и `run_report.json`.
12. Adapter возвращает результат во внешний канал.

## Run Tracking / Observability

Назначение: фиксировать технический результат каждого прогона так, чтобы его можно было отправить в Telegram, Bitrix или мониторинг.

Что сохраняется:
- общий статус, длительность, тип документа, количество страниц/секций;
- длительность каждого stage pipeline;
- LLM calls, tokens, примерная стоимость;
- warnings, risk_flags, human_review_required;
- пути к артефактам: upload, canonical document, facts JSON, renderer data, DOCX, validation.

Основной файл: `app/services/run_tracker.py`.

Выходной файл: `data/processed/<document_id>/run_report.json`.
