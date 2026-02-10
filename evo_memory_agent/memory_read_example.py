from dotenv import load_dotenv
load_dotenv()

import os
from pathlib import Path

import config
from shared_memory.memory import AmemGamMemory


MEMORY_DIR = Path(__file__).resolve().parent / "memory_usage_store" / "exp4"
USE_BM25 = True


def main():
    if not config.OPENROUTER_API_KEY:
        raise RuntimeError(
            "Missing OPENROUTER_API_KEY env var. "
            "Set it first, e.g.: export OPENROUTER_API_KEY='...'"
        )

    export_file = MEMORY_DIR / "amem_exports" / "amem_memories.jsonl"
    if not export_file.exists() or export_file.stat().st_size == 0:
        raise FileNotFoundError(
            f"A-mem export not found or empty at: {export_file}. "
            "Run memory_formation_example.py first."
        )

    memory = AmemGamMemory(
        checkpoint_path=str(MEMORY_DIR),
        rebuild_interval=1000,
        enable_bm25=USE_BM25,
    )

    print("\n==============================")
    print("A-MEM + GAM Demo: Memory search")
    print("==============================\n")

    memory_state = ""

    q1 = "Find ideas that can help to solve this problem:  **OBJECTIVE**: Write a Python function that arranges exactly **9 non-overlapping circles with variable radii** inside a unit square [0, 1] × [0, 1] to **maximize the total sum of their radii**."
    print(f">>> QUERY Q1: {q1!r}")

    result = memory.search(q1, memory_state=memory_state)
    print("\nResult Q1:\n")
    print(result)

    print("\nDone.\n")


if __name__ == "__main__":
    main()
