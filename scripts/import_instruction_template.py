from __future__ import annotations

import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.rag.docx_template_converter import DocxTemplateConverter


def main() -> None:
    default_source = "/Users/ivanharitonov/Desktop/instructions_agent_marshal/contract_instruction_service/shablon/_Шаблон_инструкции_по_работе_с_клиентом_1.docx"
    parser = argparse.ArgumentParser(description="Import DOCX instruction template into Markdown template file.")
    parser.add_argument("--source", default=str(default_source), help="Path to source DOCX template")
    parser.add_argument(
        "--output",
        default=str(PROJECT_ROOT / "data" / "templates" / "instruction_template.md"),
        help="Path to output Markdown template",
    )
    args = parser.parse_args()

    markdown = DocxTemplateConverter().convert_file(args.source)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(markdown, encoding="utf-8")
    print(f"Imported template: {args.source} -> {output}")


if __name__ == "__main__":
    main()
