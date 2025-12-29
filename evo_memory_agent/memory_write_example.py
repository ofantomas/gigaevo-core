from dotenv import load_dotenv
load_dotenv()

from pathlib import Path

import config
from shared_memory.memory import AmemGamMemory
from shared_memory.a_mem_memory_creation import pretty_print_memory
from ideas_for_memory import test_ideas


MEMORY_DIR = Path(__file__).resolve().parent / "memory_usage_store" / "exp4"
ENABLE_MEMORY_EVOLUTION = False


def main():
    if not config.OPENROUTER_API_KEY:
        raise RuntimeError(
            "Missing OPENROUTER_API_KEY env var. "
            "Set it first, e.g.: export OPENROUTER_API_KEY='...'"
        )

    memory = AmemGamMemory(checkpoint_path=str(MEMORY_DIR), rebuild_interval=1000)
    if not ENABLE_MEMORY_EVOLUTION:
        # Skip the evolution step during note ingestion.
        memory.memory_system.process_memory = lambda note: (False, note)

    print("\n==============================")
    print("A-MEM + GAM Demo: Memory formation")
    print("==============================\n")

    memories = []
    for task in test_ideas:
        task_name = (task.get("task_name") or "").strip()
        task_description = (task.get("task_description") or "").strip()
        for idea in task.get("useful_ideas", []):
            if isinstance(idea, dict):
                text = (idea.get("idea") or idea.get("text") or "").strip()
                strategy = (idea.get("strategy") or "").strip()
            else:
                text = (idea or "").strip()
                strategy = ""
            if not text:
                continue
            memories.append(
                {
                    "content": text,
                    "task_name": task_name,
                    "task_description": task_description,
                    "strategy": strategy,
                }
            )

    print("1) Adding memories from list...\n")
    memory_ids = []
    for item in memories:
        analysis = memory.memory_system.analyze_content(item["content"])
        strategy = item.get("strategy") or ""
        tags = analysis.get("tags") or []
        keywords = analysis.get("keywords") or []
        context = item.get("task_description") or analysis.get("context") or "General"
        mid = memory.memory_system.add_note(
            content=item["content"],
            tags=tags,
            category=item.get("task_name") or "general",
            keywords=keywords,
            context=context,
            strategy=strategy,
        )
        memory.memory_ids.add(mid)
        memory._iters_after_rebuild += 1
        if memory._iters_after_rebuild >= memory.rebuild_interval:
            memory.rebuild()
            memory._iters_after_rebuild = 0
        memory_ids.append(mid)

    for idx, mid in enumerate(memory_ids, start=1):
        mem = memory.memory_system.read(mid)
        pretty_print_memory(mem, title=f"Added memory #{idx}")

    memory.rebuild()
    print(f"\nExported A-mem memories to: {memory.export_file}")
    print(f"Chroma vectors persisted under: {MEMORY_DIR / 'chroma'}")


if __name__ == "__main__":
    main()
