from __future__ import annotations

import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W = f"{{{W_NS}}}"


class DocxTemplateConverter:
    """Convert a DOCX instruction template to Markdown while preserving table layout."""

    def convert_file(self, source_path: str | Path) -> str:
        source = Path(source_path)
        with zipfile.ZipFile(source) as archive:
            document_xml = archive.read("word/document.xml")
        root = ET.fromstring(document_xml)
        body = root.find(f"{W}body")
        if body is None:
            raise ValueError(f"DOCX has no word/document.xml body: {source}")

        blocks: list[str] = []
        for child in body:
            tag = self._local_name(child.tag)
            if tag == "p":
                blocks.append(self._paragraph_to_markdown(child))
            elif tag == "tbl":
                table = self._table_to_markdown(child)
                if table.strip():
                    blocks.append(table)

        return self._normalize_markdown("\n\n".join(blocks))

    def _paragraph_to_markdown(self, paragraph: ET.Element) -> str:
        text = self._paragraph_text(paragraph)
        if not text.strip():
            return ""

        style = self._paragraph_style(paragraph)
        normalized = self._compact_spaces(text)
        if style and "Heading" in style and not normalized.startswith("#"):
            level_match = re.search(r"Heading(\d+)", style)
            level = int(level_match.group(1)) if level_match else 2
            return f"{'#' * min(max(level, 1), 6)} {normalized}"
        return normalized

    def _paragraph_text(self, paragraph: ET.Element) -> str:
        parts: list[str] = []
        for run in paragraph.findall(f"{W}r"):
            run_text_parts: list[str] = []
            for child in run:
                tag = self._local_name(child.tag)
                if tag == "t" and child.text:
                    run_text_parts.append(child.text)
                elif tag == "tab":
                    run_text_parts.append(" ")
                elif tag in {"br", "cr"}:
                    run_text_parts.append("\n")
            parts.append("".join(run_text_parts))
        return "".join(parts)

    def _paragraph_style(self, paragraph: ET.Element) -> str | None:
        style = paragraph.find(f"{W}pPr/{W}pStyle")
        if style is None:
            return None
        return style.attrib.get(f"{W}val")

    def _table_to_markdown(self, table: ET.Element) -> str:
        rows: list[list[str]] = []
        for row in table.findall(f"{W}tr"):
            cells = [self._cell_to_markdown(cell) for cell in row.findall(f"{W}tc")]
            if cells:
                rows.append(cells)
        if not rows:
            return ""

        max_columns = max(len(row) for row in rows)
        normalized = [row + [""] * (max_columns - len(row)) for row in rows]
        header = [cell or " " for cell in normalized[0]]
        separator = ["---"] * max_columns
        body = normalized[1:]

        lines = [
            "| " + " | ".join(header) + " |",
            "| " + " | ".join(separator) + " |",
        ]
        for row in body:
            lines.append("| " + " | ".join(cell or " " for cell in row) + " |")
        return "\n".join(lines)

    def _cell_to_markdown(self, cell: ET.Element) -> str:
        paragraphs = []
        for paragraph in cell.findall(f"{W}p"):
            text = self._compact_spaces(self._paragraph_text(paragraph).replace("\n", "<br>"))
            if text:
                paragraphs.append(text)
        return "<br>".join(paragraphs).replace("|", "\\|")

    def _compact_spaces(self, text: str) -> str:
        lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
        return "\n".join(line for line in lines if line)

    def _normalize_markdown(self, markdown: str) -> str:
        markdown = re.sub(r"\n{4,}", "\n\n\n", markdown)
        return markdown.strip() + "\n"

    def _local_name(self, tag: str) -> str:
        return tag.rsplit("}", 1)[-1]
