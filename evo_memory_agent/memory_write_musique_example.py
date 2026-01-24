from dotenv import load_dotenv
load_dotenv()

from pathlib import Path
import json

import config
from shared_memory.memory import AmemGamMemory
from shared_memory.a_mem_memory_creation import pretty_print_memory


DATASET_PATH = Path(__file__).resolve().parent / "datasets" / "musique_200.json"
MEMORY_DIR = Path(__file__).resolve().parent / "memory_usage_store" / "musique0"
TASK_INDEX = 0  # Pick the task to load from the dataset (0-based index).
ENABLE_MEMORY_EVOLUTION = False


def load_task(path: Path, task_index: int) -> dict:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    tasks = data.get("data") or []
    if not tasks:
        raise ValueError(f"No tasks found in dataset: {path}")

    if task_index < 0 or task_index >= len(tasks):
        raise IndexError(f"TASK_INDEX {task_index} is out of range for {len(tasks)} tasks")

    return tasks[task_index]


def main():
    if not config.OPENROUTER_API_KEY:
        raise RuntimeError(
            "Missing OPENROUTER_API_KEY env var. "
            "Set it first, e.g.: export OPENROUTER_API_KEY='...'"
        )

    task = load_task(DATASET_PATH, TASK_INDEX)
    task_id = task.get("id") or f"musique_task_{TASK_INDEX}"
    paragraphs = task.get("paragraphs") or []

    if not paragraphs:
        raise ValueError(f"Task {task_id} has no paragraphs to ingest.")

    memory = AmemGamMemory(checkpoint_path=str(MEMORY_DIR), rebuild_interval=1000)
    if not ENABLE_MEMORY_EVOLUTION:
        # Skip the evolution step during note ingestion.
        memory.memory_system.process_memory = lambda note: (False, note)

    print("\n==============================")
    print("A-MEM + GAM Demo: Musique paragraph notes")
    print("==============================\n")
    print(f"Using task index {TASK_INDEX} (id={task_id})\n")

    memory_ids = []
    for paragraph in paragraphs:
        text = (paragraph.get("paragraph_text") or "").strip()
        if not text:
            continue
        mid = memory.save(text, category=str(task_id))
        memory_ids.append(mid)

    for idx, mid in enumerate(memory_ids, start=1):
        mem = memory.memory_system.read(mid)
        pretty_print_memory(mem, title=f"Added memory #{idx}")

    memory.rebuild()
    print(f"\nExported A-mem memories to: {memory.export_file}")
    print(f"Chroma vectors persisted under: {MEMORY_DIR / 'chroma'}")


if __name__ == "__main__":
    main()
