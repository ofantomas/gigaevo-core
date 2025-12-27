from dotenv import load_dotenv
load_dotenv()

from pathlib import Path

import config

from memory import AmemGamMemory
from a_mem_memory_creation import pretty_print_memory


def main():
    # Configure OpenRouter-backed LLMService (used by both A-mem + GAM)
    if not config.OPENROUTER_API_KEY:
        raise RuntimeError(
            "Missing OPENROUTER_API_KEY env var. "
            "Set it first, e.g.: export OPENROUTER_API_KEY='...'"
        )

    checkpoint_dir = Path(__file__).resolve().parent / "memory_usage_store"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)

    memory = AmemGamMemory(checkpoint_path=str(checkpoint_dir), rebuild_interval=3)

    print("\n==============================")
    print("A-MEM + GAM Demo: AmemGamMemory usage")
    print("==============================\n")

    # -------------------------------------------------------
    # 1) Your memories: list of strings only
    # -------------------------------------------------------
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

    # -------------------------------------------------------
    # 2) Add/index them (category=heilbron, everything else blank)
    # -------------------------------------------------------
    print("1) Adding memories from list...\n")
    memory_ids = []
    for text in memories:
        mid = memory.save(text)
        memory_ids.append(mid)

    # Read back and print each memory so you can see what A-MEM generated
    for idx, mid in enumerate(memory_ids, start=1):
        mem = memory.memory_system.read(mid)
        pretty_print_memory(mem, title=f"Added memory #{idx}")

    # -------------------------------------------------------
    # 2.5) Export A-mem memories for GAM reuse + rebuild retriever
    # -------------------------------------------------------
    memory.rebuild()
    print(f"\nExported A-mem memories to: {memory.export_file}")

    # -------------------------------------------------------
    # 3) Retrieval example (GAM ResearchAgent)
    # -------------------------------------------------------
    memory_state = (
        "This task is heilborn packing task"
    )
    print("\n2) Retrieval example (AmemGamMemory.search -> ResearchAgent.research) ...\n")
    q1 = "What is most important thing in memory?"
    print(f">>> QUERY Q1: {q1!r}")
    result = memory.search(q1, memory_state=memory_state)
    print("\nResult Q1:\n")
    print(result)

    print("\nDone Q1.\n")
    
    # -------------------------------------------------------
    # 4) Add new memory and retrieve again
    # -------------------------------------------------------
    
    memories2 = [
        "Removed hex grid generation; eliminated structured clustering artifacts causing small triangles, primary driver of +0.00916 gain.",
        # "Replaced hexagonal lattice with Halton sequence (5000 points); eliminated structured clustering; enabled better space coverage for +0.00902 gain.",
        # "Changed boundary buffer to max(0.005, 0.02*best_fitness); balanced exploration near boundaries; reduced constraint violations by 63%.",
        # "Triangle area caching with periodic clearing reduced computation time by ~35%, enabling more effective exploration within iteration limit.",
        # "Vectorized triangle calculation with precise tolerance (0.002*fitness); reduced false collinearity detection; improved gradient accuracy by 4x.",
    ]
    
    for text in memories2:
        memory.save(text)
    
    # DO NOT REBUILD HERE, to see automatic rebuild on destruction
    # memory.rebuild()
    
    print("\n2) Retrieval example (AmemGamMemory.search -> ResearchAgent.research) ...\n")
    q2 = "What changes improved min_area the most and why?"
    print(f">>> QUERY Q2: {q2!r}")
    result = memory.search(q2, memory_state=memory_state)
    print("\nResult Q2:\n")
    print(result)

    print("\nDone Q2.\n")


if __name__ == "__main__":
    main()
