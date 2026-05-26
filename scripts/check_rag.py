from __future__ import annotations

from pathlib import Path
import sys

import chromadb

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.config import get_settings


if __name__ == "__main__":
    settings = get_settings()
    vectorstore_dir = settings.vectorstore_dir
    print(f"Vectorstore dir: {vectorstore_dir}")
    print(f"Exists: {vectorstore_dir.exists()}")

    files = sorted(path.relative_to(vectorstore_dir) for path in vectorstore_dir.rglob("*") if path.is_file())
    print(f"Files: {len(files)}")
    for path in files[:20]:
        print(f"- {path}")

    if not (vectorstore_dir / "chroma.sqlite3").exists():
        print("Chroma DB not found. Run scripts/index_rag.py first.")
        raise SystemExit(1)

    client = chromadb.PersistentClient(path=str(vectorstore_dir))
    collection = client.get_or_create_collection("contract_instruction_rag")
    print(f"Chroma collection count: {collection.count()}")

