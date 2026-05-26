from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
import sys

import orjson

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.logging_config import configure_logging
from app.services.contract_pipeline import ContractPipeline


async def main() -> None:
    parser = argparse.ArgumentParser(description="Process one local contract file through ContractPipeline.")
    parser.add_argument(
        "file_path",
        nargs="?",
        default=None,
        help="Path to PDF or DOCX contract. If omitted, DEFAULT_CONTRACT_FILE from .env is used.",
    )
    parser.add_argument("--user-id", default="local-user")
    parser.add_argument("--channel", default="api")
    parser.add_argument("--entity-id", default=None)
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(settings)
    path = settings.resolve_project_path(args.file_path) if args.file_path else settings.default_contract_file
    if not path.exists():
        raise FileNotFoundError(
            f"Contract file not found: {path}. "
            "Pass file_path argument or set DEFAULT_CONTRACT_FILE in .env."
        )

    result = await ContractPipeline(settings=settings).process_contract(
        file_path=str(path),
        original_filename=path.name,
        external_user_id=args.user_id,
        source_channel=args.channel,
        external_entity_id=args.entity_id,
    )
    print(orjson.dumps(result.model_dump(mode="json"), option=orjson.OPT_INDENT_2).decode("utf-8"))
    if result.instruction_docx_path:
        print(f"\nDOCX instruction: {result.instruction_docx_path}")


if __name__ == "__main__":
    asyncio.run(main())
