"""
GAM retriever script that loads A-mem exports and uses A-mem LLMService.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List
from dotenv import load_dotenv
load_dotenv()

from GAM_root.gam import (
    ResearchAgent,
    InMemoryMemoryStore,
    InMemoryPageStore,
    IndexRetriever,
    IndexRetrieverConfig,
    DenseRetriever,
    DenseRetrieverConfig,
)
from GAM_root.gam.generator import AMemGenerator
from GAM_root.gam.schemas import Page

import config

def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


_amem_root = _repo_root() / "A-mem-main"
if str(_amem_root) not in sys.path:
    sys.path.insert(0, str(_amem_root))

from A_mem.agent.agent_class import LLMService

def load_amem_records(path: Path) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
    return records


def make_card_text(record: Dict[str, Any]) -> str:
    tags = ", ".join(record.get("tags", []) or [])
    keywords = ", ".join(record.get("keywords", []) or [])
    links = record.get("links", []) or []
    parts = [
        f"content: {record.get('content', '')}",
        f"context: {record.get('context', '')}",
        f"category: {record.get('category', '')}",
        f"keywords: {keywords}",
        f"tags: {tags}",
        f"timestamp: {record.get('timestamp', '')}",
        f"links: {links}",
    ]
    return "\n".join(parts)


def build_gam_store(records: List[Dict[str, Any]], store_dir: Path):
    memory_store = InMemoryMemoryStore(dir_path=str(store_dir))
    page_store = InMemoryPageStore(dir_path=str(store_dir))

    existing_pages = page_store.load()
    existing_ids = {
        (p.meta or {}).get("amem_id")
        for p in existing_pages
        if isinstance(p.meta, dict)
    }

    added = 0
    for rec in records:
        rid = rec.get("id")
        if rid in existing_ids:
            continue
        card = make_card_text(rec)
        abstract = rec.get("content") or card
        memory_store.add(abstract)
        header = f"[A-MEM] {rid}" if rid else "[A-MEM]"
        page_store.add(Page(header=header, content=card, meta={"amem_id": rid, "amem": rec}))
        added += 1
    return memory_store, page_store, added


def build_retrievers(page_store: InMemoryPageStore, index_dir: Path):
    retrievers = {}

    try:
        index_config = IndexRetrieverConfig(index_dir=str(index_dir / "page_index"))
        index_retriever = IndexRetriever(index_config.__dict__)
        index_retriever.build(page_store)
        retrievers["page_index"] = index_retriever
        print("✅ Index retriever ready")
    except Exception as e:
        print(f"[WARN] Index retriever failed: {e}")

    try:
        dense_config = DenseRetrieverConfig(
            index_dir=str(index_dir / "dense_index"),
            model_name=config.GAM_DENSE_RETRIEVER_MODEL_NAME,
            devices=["cpu"],
        )
        dense_retriever = DenseRetriever(dense_config.__dict__)
        dense_retriever.build(page_store)
        retrievers["vector"] = dense_retriever
        print("✅ Dense retriever ready")
    except Exception as e:
        print(f"[WARN] Dense retriever failed: {e}")

    return retrievers


def main():
    export_file = Path("amem_exports/amem_memories.jsonl")
    # if export_path:
    #     export_file = Path(export_path)
    # else:
    #     export_file = _repo_root()  / "amem_memories.jsonl"

    if not export_file.exists():
        raise FileNotFoundError(f"A-mem export not found: {export_file}")

    records = load_amem_records(export_file)
    if not records:
        raise RuntimeError("A-mem export is empty.")

    store_dir = _repo_root() / "gam_shared" / "amem_store"
    store_dir.mkdir(parents=True, exist_ok=True)
    memory_store, page_store, added = build_gam_store(records, store_dir)
    print(f"Loaded {len(records)} A-mem records, added {added} new pages.")

    llm_service = LLMService(
        service=config.OPENROUTER_SERVICE,
        model_name=config.OPENROUTER_MODEL_NAME,
        api_key=config.OPENROUTER_API_KEY,
        temperature=0.0,
        max_tokens=2048,
    )
    generator = AMemGenerator({"llm_service": llm_service})

    retrievers = build_retrievers(page_store, store_dir / "indexes")
    research_agent = ResearchAgent(
        page_store=page_store,
        memory_store=memory_store,
        retrievers=retrievers,
        generator=generator,
        max_iters=3,
    )

    question = os.getenv("AMEM_QUESTION", "What changes improved min_area the most and why?")
    print(f"\nResearch question: {question}\n")
    result = research_agent.research(question)
    print("Research result:\n")
    print(result.integrated_memory)


if __name__ == "__main__":
    main()
