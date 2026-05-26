# Contract Instruction Service

Backend-сервис для обработки клиентских договоров и генерации внутренних инструкций для сотрудников на основе договора, шаблона инструкции, внутренних правил и примеров.

Telegram в этом проекте — только тестовая среда и быстрый интерфейс. Основной будущий production-канал — Bitrix24, но core pipeline уже сделан channel-agnostic: тот же `ContractPipeline` может вызываться из Telegram, Bitrix webhook, REST API или другого интерфейса.

## Архитектура Pipeline

Поток обработки:

```text
Файл договора
↓
Document Router
↓
Extractor
↓
CanonicalDocument
↓
Contract Facts JSON
↓
Validation
↓
Instruction Generation
↓
Instruction Validation
↓
Human Review Result
```

Такой workflow нужен, чтобы видеть, где возникла ошибка: в OCR, извлечении фактов, генерации или validation. Для важных фактов используются `source_ref`, `source_quote`, `confidence` и `needs_human_review`.

## PDF/DOCX Обработка

DOCX:
- читается через `python-docx`;
- извлекаются параграфы и таблицы;
- таблицы переводятся в Markdown;
- изображения, comments/tracked changes помечаются warnings.

Digital PDF:
- читается через PyMuPDF;
- текст извлекается постранично;
- страницы получают refs `page_1`, `page_2`, ...

Mixed PDF:
- текстовые страницы читаются напрямую;
- страницы без достаточного текста отправляются в OCR/VLM provider;
- если OCR provider не подключен, результат получает warning и `human_review_required`.

Scanned PDF:
- определяется router;
- страницы рендерятся в изображения;
- OCR/VLM provider вынесен интерфейсом;
- `OCR_PROVIDER=yandex_vlm` отправляет страницы в Yandex OpenAI-compatible image input;
- если OCR не подключен или не смог извлечь текст, pipeline не должен генерировать пустую инструкцию.

## RAG

Файлы:
- `data/templates/instruction_template.md`
- `data/templates/internal_rules.md`
- `data/templates/examples.md`

Шаблон индексируется в Chroma, но финальная генерация всегда получает полный актуальный шаблон из `instruction_template.md`. Retrieval используется для внутренних правил и похожих примеров.

Переиндексация:

```bash
python scripts/index_rag.py
```

## Настройка

```bash
cp .env.example .env
```

Заполните:
- `YANDEX_CLOUD_API_KEY`
- `TELEGRAM_BOT_TOKEN`, если нужен Telegram test adapter
- `ADMIN_IDS`, если нужны `/reindex_templates` и админские отчеты после каждого прогона

Yandex LLM используется через OpenAI SDK:
- `base_url=https://ai.api.cloud.yandex.net/v1`
- модель `qwen3.6-35b-a3b/latest`
- default temperature `0.2`

## PyCharm Запуск

Откройте папку `contract_instruction_service` как проект PyCharm.

Рекомендуемые Run Configurations:
- `Index RAG`: script `scripts/index_rag.py`, working directory `contract_instruction_service`.
- `Run API`: script `scripts/run_api.py`, working directory `contract_instruction_service`.
- `Run Bot`: script `scripts/run_bot.py`, working directory `contract_instruction_service`.
- `Process Local File`: script `scripts/process_file.py`, parameters `/path/to/contract.pdf`, working directory `contract_instruction_service`.

Environment variables можно брать из файла `.env`. В него нужно вставить реальные значения:
- `YANDEX_CLOUD_API_KEY`;
- `TELEGRAM_BOT_TOKEN`, если запускается Telegram bot;
- `ADMIN_IDS`, если нужна команда `/reindex_templates`.
- `DEFAULT_CONTRACT_FILE`, если хотите запускать `scripts/process_file.py` без параметров.
- `OCR_PROVIDER=yandex_vlm`, если нужно обрабатывать сканированные PDF.
- `YANDEX_GENERATION_MODEL_MODE=auto`, чтобы сначала пробовать основную 35B модель для DOCX-данных и вызывать 235B только при плохом результате.
- `YANDEX_DATA_LOGGING_ENABLED=false`, чтобы отправлять в Yandex AI Studio header `x-data-logging-enabled: false` и отключать сохранение данных запросов на стороне Yandex Cloud.

Режимы `YANDEX_GENERATION_MODEL_MODE`:
- `primary` — всегда использовать `YANDEX_CLOUD_MODEL`;
- `premium` — всегда использовать `YANDEX_GENERATION_MODEL`;
- `auto` — сначала `YANDEX_CLOUD_MODEL`, fallback на `YANDEX_GENERATION_MODEL`, если критичные поля для DOCX-рендера не заполнены.

По умолчанию локальный тестовый договор берется отсюда:

```text
./sdogovory/D-okazaniya-TEU (1).docx
```

## Первый Прогон RAG

RAG индексирует постоянные материалы, а не каждый договор клиента:
- полный шаблон `data/templates/instruction_template.md`;
- внутренние правила `data/templates/internal_rules.md`;
- примеры `data/templates/examples.md`.

Если исходный DOCX-шаблон изменился, сначала импортируйте его в Markdown:

```bash
python scripts/import_instruction_template.py --source "../шаблон инструкции/_Шаблон_инструкции_по_работе_с_клиентом_1.docx"
```

Importer сохраняет порядок блоков и переводит таблицы DOCX в Markdown-таблицы. После этого нужно переиндексировать RAG.

Запуск:

```bash
python scripts/index_rag.py
```

После запуска chunks сохраняются в `data/vectorstore`. Договоры клиентов не кладутся в RAG: каждый договор обрабатывается отдельно через `ContractPipeline`, а результаты сохраняются в `data/processed/<document_id>/`.

## Запуск Telegram Bot

```bash
python scripts/run_bot.py
```

Команды:
- `/start`
- `/help`
- `/status`
- `/reindex_templates` только для `ADMIN_IDS`

Bot принимает PDF/DOCX и вызывает backend pipeline. В handlers нет бизнес-логики договора.
Результат отправляется как `.docx`; Markdown сохраняется как промежуточный артефакт в `data/processed`.

Если заполнен `ADMIN_IDS`, после каждого прогона бот отправляет администратору короткий отчет:
- статус обработки;
- длительность;
- тип документа и количество страниц/секций;
- количество LLM-вызовов, токены и примерную стоимость в рублях;
- количество warnings/risk flags;
- путь к DOCX и `run_report.json`.

Полный machine-readable отчет сохраняется в `data/processed/<document_id>/run_report.json`. Этот же отчет можно использовать в Bitrix24: писать summary в комментарий сделки, сохранять путь к артефактам и обновлять статус обработки.

## Запуск FastAPI

```bash
python scripts/run_api.py
```

Endpoints:
- `GET /api/health`
- `POST /api/reindex-templates`
- `POST /api/bitrix/webhook/document`

Bitrix webhook payload:

```json
{
  "bitrix_deal_id": "123",
  "bitrix_company_id": "456",
  "bitrix_user_id": "789",
  "file_url": "https://...",
  "filename": "contract.pdf",
  "metadata": {}
}
```

## Docker

```bash
docker compose up --build api
docker compose up --build bot
```

`./data` монтируется как volume.

## Где Лежат Результаты

Для каждого документа создается каталог:

```text
data/processed/<document_id>/
  extracted_text.txt
  canonical_document.json
  contract_facts.json
  instruction.md
  <filename>_instruction.docx
  validation_result.json
  run_report.json
```

Исходные файлы сохраняются в `data/uploads`.

SQLite DB:

```text
data/app.db
```

Таблицы:
- `documents`
- `processing_results`

## Будущая Интеграция Bitrix24

Сейчас есть scaffold:
- `app/api/bitrix_routes.py`
- `app/integrations/bitrix_adapter.py`

Что нужно добавить для production:
- проверку подписи/авторизацию webhook;
- Bitrix REST client;
- скачивание файлов из сделки;
- upload `instruction.md`;
- upload `<filename>_instruction.docx`;
- комментарий в timeline;
- custom status field;
- обработку retries/idempotency.

Core pipeline менять не нужно.

## Минимальный Production Checklist

Перед переносом на сервер для пилота:
- хранить `.env` только на сервере, без секретов в git;
- держать `YANDEX_DATA_LOGGING_ENABLED=false` для договоров с персональными/конфиденциальными данными;
- проверить `ADMIN_IDS`, `OCR_PROVIDER`, `OCR_CONCURRENCY`, `YANDEX_GENERATION_MODEL`;
- запустить `python scripts/check_rag.py` и убедиться, что Chroma не пустой;
- сделать тест на DOCX, digital PDF и scanned PDF;
- проверить, что в `run_report.json` есть LLM usage, стоимость, warnings и артефакты;
- включить backup каталога `data/` и SQLite;
- запускать bot/api под process manager или Docker Compose с restart policy;
- добавить внешнее логирование/ошибки: Sentry, Grafana/Prometheus или хотя бы сбор stdout logs.

## Ограничения MVP

- OCR/VLM для scanned PDF зависит от выбранного provider и сейчас представлен stub-интерфейсом.
- Все инструкции по договорам нужно проверять человеком.
- Модель может ошибаться, поэтому validation и `source_ref` обязательны.
- Нельзя использовать итоговую инструкцию как юридическое заключение без ручной проверки.
- Если данных нет, итоговая инструкция должна содержать `Уточнить у человека`.
- Штрафы, пени, ответственность и сроки обрабатываются как критичные поля.
