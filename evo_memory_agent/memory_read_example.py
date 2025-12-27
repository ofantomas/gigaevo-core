from dotenv import load_dotenv
load_dotenv()

from pathlib import Path

import config
from memory import AmemGamMemory


MEMORY_DIR = Path(__file__).resolve().parent / "memory_usage_store" / "exp1"


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

    memory = AmemGamMemory(checkpoint_path=str(MEMORY_DIR), rebuild_interval=1000)

    print("\n==============================")
    print("A-MEM + GAM Demo: Memory search")
    print("==============================\n")

    memory_state = "This task is heilborn packing task"

    q1 = "What is most important thing in memory?"
    print(f">>> QUERY Q1: {q1!r}")
    result = memory.search(q1, memory_state=memory_state)
    print("\nResult Q1:\n")
    print(result)

    print("\nDone.\n")


if __name__ == "__main__":
    main()
