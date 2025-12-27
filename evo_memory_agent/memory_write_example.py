from dotenv import load_dotenv
load_dotenv()

from pathlib import Path

import config
from shared_memory.memory import AmemGamMemory
from shared_memory.a_mem_memory_creation import pretty_print_memory


MEMORY_DIR = Path(__file__).resolve().parent / "memory_usage_store" / "exp1"


def main():
    if not config.OPENROUTER_API_KEY:
        raise RuntimeError(
            "Missing OPENROUTER_API_KEY env var. "
            "Set it first, e.g.: export OPENROUTER_API_KEY='...'"
        )

    memory = AmemGamMemory(checkpoint_path=str(MEMORY_DIR), rebuild_interval=1000)

    print("\n==============================")
    print("A-MEM + GAM Demo: Memory formation")
    print("==============================\n")

    memories = [
        "Farthest Point Sampling replaced Sobol; created superior initial spread, foundational for +0.02519 fitness gain.",
        "Added stagnation restart (500 iters); escaped local minima, critical for the +0.02519 metric improvement.",
        # "Symmetric point distribution (5 left + axis + 5 right) eliminated parent's clustering; directly enabled +0.02231 area gain.",
        # "20k-iteration simulated annealing targeting min area; explains full +0.02231 metric gain through systematic bottleneck optimization.",
        # "Removed parent's rigid row-based grid (5->1 points) causing density clustering; removal eliminated small triangles, contributing to +0.02070 area gain.",
        # "Introduced simulated annealing with temperature-controlled moves; explored configurations beyond parent's static grid, enabling +0.02070 min_area gain.",
        # "Generalized perturbations to target min-triangle vertices (lines 40-50); direct refinement of critical regions increased min_area by 0.02070.",
        # "Reduced boundary repulsion to 1e-6, preventing edge clustering; directly enabled +0.01855 area gain by eliminating degenerate boundary triangles.",
        # "Enforced reflection symmetry via left/right mirroring; eliminated asymmetric clusters, directly contributing +0.01796 min_area gain.",
        # "Introduced simulated annealing (T=0.01) to escape local minima; accepted worse moves, enabling 0.01796 improvement.",
        # "Targeted perturbations to points in smallest triangle (found by triple loop); focused optimization on critical regions for +0.01796 gain.",
        # "Reduced boundary repulsion threshold from 0.02 to 1e-6; enabled optimal boundary placement, explaining +0.01224 fitness gain.",
    ]

    print("1) Adding memories from list...\n")
    memory_ids = []
    for text in memories:
        mid = memory.save(text)
        memory_ids.append(mid)

    for idx, mid in enumerate(memory_ids, start=1):
        mem = memory.memory_system.read(mid)
        pretty_print_memory(mem, title=f"Added memory #{idx}")

    memory.rebuild()
    print(f"\nExported A-mem memories to: {memory.export_file}")
    print(f"Chroma vectors persisted under: {MEMORY_DIR / 'chroma'}")


if __name__ == "__main__":
    main()
