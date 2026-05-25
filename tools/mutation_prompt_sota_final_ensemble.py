"""SOTA final ensemble review for mutation/system.txt.

Reviewing the cumulative post-edit prompt (4 patches + 4-domain rebalanced BAD→GOOD pairs)
against the user's goal: SOTA memory cards — HELPFUL, NOT BLOATED, TRANSFERRABLE across problems.

Full gigaevo context provided:
- pipeline overview (MAP-Elites + LLM mutation, memory write/read split)
- v4 packed-grammar card semantics
- 4 dry renders (Heilbron / tabular_regression / kissing_number_12d / chains/hover/static_soft)
- Real cards from a recent tabular_regression run

3 voices at HIGH reasoning effort, 60K max tokens:
- anthropic/claude-opus-4.1
- google/gemini-2.5-pro
- openai/o3

Squid proxy MUST be active. JSON parse fallback + 1 retry on failure.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import sys

import httpx
import yaml

OUTPUT_DIR = Path(
    "/home/jovyan/gigaevo/output/mutation_prompt_sota_final_ensemble_20260524"
)
PROMPT_PATH = Path("/home/jovyan/gigaevo/gigaevo/prompts/mutation/system.txt")
PROBLEMS_ROOT = Path("/home/jovyan/gigaevo/problems")

DRY_RENDER_PROBLEMS = [
    ("heilbron (discrete geometry, 11 points)", PROBLEMS_ROOT / "heilbron"),
    (
        "tabular_regression (ML, California Housing)",
        PROBLEMS_ROOT / "tabular_regression",
    ),
    (
        "kissing_number_12d (high-D sphere packing, integer construction)",
        PROBLEMS_ROOT / "kissing_number_12d",
    ),
    (
        "chains/hover/static_soft (multi-hop NLP retrieval)",
        PROBLEMS_ROOT / "chains" / "hover" / "static_soft",
    ),
]


def render_metrics(yaml_path: Path) -> str:
    from gigaevo.programs.metrics.context import MetricsContext
    from gigaevo.programs.metrics.formatter import MetricsFormatter

    specs = yaml.safe_load(yaml_path.read_text())["specs"]
    ctx = MetricsContext(specs=specs)
    return MetricsFormatter(ctx).format_metrics_description()


def render_full_prompt(task_path: Path, metrics_path: Path, template: str) -> str:
    task = task_path.read_text()
    metrics = render_metrics(metrics_path)
    return template.format(task_description=task, metrics_description=metrics)


REAL_CARDS_FROM_TABULAR_RUN = """\
The following 8 cards are REAL output from a recent tabular_regression run
(`output/tabular_regression_intra_extra_20260523_161718/memory/api_index.json`,
2026-05-23, pre-final-edits). They are what the CURRENT prompt actually produces in the wild.
Use them as ground truth for "what the prompt drives the LLM to emit", not as exemplars
of what we WANT.

1. `Removed target_log_transform log->raw: gradient updates match evaluation metric scale`
2. `Replaced target_transform log->raw: aligns training objective with raw-scale RMSE metric`
3. `Rewired prediction_postprocess exp+upper_clip->clip_both: avoids RMSE penalty from sub-0.15 predictions`
4. `Replaced target_transform log->raw: aligns training objective with raw-scale RMSE metric` (duplicate of #2)
5. `Removed target_log_transform log->raw: gradient updates match evaluation metric scale; Rewired prediction_postprocess exp+upper_clip->clip_both: avoids RMSE penalty from sub-0.15 predictions` (TWO knobs collapsed into one description — violates "≥2 distinct knobs → ≥2 items" rule)
6. `Top-10 program (fitness=-0.428681); no recorded idea lineage - inspect \\`code\\` field for mechanism.` (NOT a mutation card; from a different writer path)
7. `Top-7 program (fitness=-0.428681); no recorded idea lineage - inspect \\`code\\` field for mechanism.` (same)
8. `Top-4 program (fitness=-0.428681); no recorded idea lineage - inspect \\`code\\` field for mechanism.` (same)

Patterns visible:
- Cards 1-3 follow grammar correctly with mostly-good `<why-it-transfers>` clauses.
- Card 3 has a concrete numeric anchor ("sub-0.15 predictions" = lower bound of California Housing target) — closest to SOTA.
- Cards 1-2 have textbook-style mechanism clauses ("match evaluation metric scale", "aligns training objective") — vague, low transfer.
- Card 5 violates the multi-knob rule (compound description).
- Cards 6-8 are produced by a DIFFERENT writer (top-program scraper), not the mutator. Out of scope for Rule 2 but worth noting they pollute the bank.
"""


GIGAEVO_CONTEXT = """\
## What GigaEvo is

GigaEvo is an evolutionary program-synthesis framework where an LLM acts as the mutation operator.
- **Selection**: MAP-Elites archive over an N-D feature grid (typically fitness × structural-novelty axes).
- **Mutation**: LLM reads parent program + evidence pack (metrics, insights, intra-memory clusters, cross-population memory cards, evo stats) and emits a child program + structured `changes`.
- **Memory**: cross-population substrate. Cards are extracted from previous runs and surfaced to subsequent mutation calls as the `Memory Cards` evidence channel.

## Problem domains gigaevo runs against (representative, not exhaustive)

| Domain | Examples | Lever vocabulary |
|--------|----------|------------------|
| Discrete geometry | heilbron, hexagon_pack, kissing_number_11d/12d, spherical_codes, santa2025_* | point coords, perturbation magnitude, symmetry transforms, lattice constructions |
| ML / tabular | tabular_regression, tabular_regression_optuna | model family, HPs, target transforms, feature engineering, ensembling |
| NLP chains | chains/hotpotqa, chains/hover, chains/musique, chains/ifbench | chain topology, step `aim`/`stage_action`/`reasoning_questions`, retrieval k, query templates |
| Prompt evolution | prompt_evolution, prompt_evolution_hover | system_prompt content, prompt-template structure |
| Adversarial co-evolution | adversarial, heilbron_adversarial | attacker_policy, defender_policy, opponent_pool |
| Algorithm tuning | algotune, alphaevolve | algorithm choice, data-structure swaps, traversal order |

A SOTA memory card MUST be useful when surfaced to mutators in ANY of these domains — not just the one that produced it.

## The card pipeline (write → read)

WRITE phase (post-run): an Ideas Tracker reads `changes[i].description` from each mutation and packs into v4 packed-grammar memory cards:

  `[UNVERIFIED_]<VERB> <target> [<old>→<new>]: <mechanism>; support=N; Δbest=+F; co=[t1,t2]`

The `<mechanism>` slot is the `<why-it-transfers>` clause from the description.
Suffix metrics:
- `support=N` — count of distinct programs that used this lever
- `Δbest=+F` — best fitness improvement attributed to this lever (positive = improvement, direction-aware)
- `co=[…]` — co-changed levers in the same program (confounders; do NOT double-credit)

READ phase (next-gen mutation): `MemoryContextStage` queries the memory DB and surfaces top-N relevant cards to the mutation operator. The operator picks high-`support × Δbest` cards and transposes the mechanism into the new child program.

## Why prompt quality matters

The mutation operator's `description` text IS the seed of every memory card. A vague description ("matches the K-way interaction") creates a vague card. A specific one ("matches the feature_group_size value listed in TASK CONTEXT") creates an actionable card.

The current prompt has been iteratively polished. This is the FINAL pass — the goal is to identify ANY remaining gap before lock-in.
"""


SOTA_CRITERIA = """\
## SOTA memory card — 3 quality axes

A card is SOTA if it scores well on ALL THREE:

**1. HELPFUL** — gives the next mutator everything needed to RE-APPLY the lever:
- WHAT lever (verb + target) — given by packed grammar
- WHAT delta (old → new) — given
- WHEN to apply (mechanism names the observable trigger)
- HOW it works (mechanism names the causal chain)

**2. NOT BLOATED** — economical, signal-dense:
- ≤140 char description, ideally ~110
- No preamble ("In order to...", "We propose...")
- No textbook lines that apply to any dataset
- No metric restatements
- No goal restatements
- One coherent change per description (multi-knob → multi-item)

**3. TRANSFERRABLE** — the mechanism is recognizable on OTHER problems:
- Mechanism names a property class (value bound, distribution shape, optimization landscape, structural property, etc.) general enough to detect elsewhere
- Specific values cited via context keys (`feature_group_size=6`, `P99/P1≈1e4`) — these transfer because the NAME of the trigger generalizes even when the value doesn't
- Avoid hyper-specific factoids that only apply to ONE dataset (e.g. "California latitude 32-42" — bad; "paired geo coordinates" — good)
- Avoid pure tautologies that are technically general but information-free ("models complex interactions")

The "Goldilocks zone": dataset-specific but transferable. The mechanism cites a property visible in THIS run's CONTEXT, and that property class also appears in other runs.
"""


def build_brief(rendered_problems: list[tuple[str, str]]) -> str:
    parts = [
        "# Mutation Prompt — SOTA Final Ensemble Review",
        "",
        "You are reviewing the CUMULATIVE post-edit form of GigaEvo's mutation operator prompt.",
        "This is the FINAL pass before lock-in. Goal: SOTA memory cards — HELPFUL, NOT BLOATED, TRANSFERRABLE across problems.",
        "",
        GIGAEVO_CONTEXT,
        "",
        SOTA_CRITERIA,
        "",
        "## The current prompt (full file, post all 5 edit rounds — taxonomy expansion, numeric-trigger preference, escape hatch rename, BAD→GOOD pairs upgrade, 4-domain rebalance)",
        "",
        "```",
        PROMPT_PATH.read_text(),
        "```",
        "",
        "## DRY RENDERS — how the prompt renders for 4 representative problem domains",
        "",
        "Each render below shows the FULL prompt as the LLM actually sees it on that problem, with `{task_description}` and `{metrics_description}` slots filled in.",
        "Focus on the bottom (CONTEXT + metrics) — that's what changes per problem. The top (ROLE/EVIDENCE/ARCHETYPE/EXECUTION/OUTPUT) is identical across all four.",
        "",
    ]

    for i, (label, rendered) in enumerate(rendered_problems, 1):
        parts.append(f"### Dry render {i} — {label}")
        parts.append("")
        parts.append("```")
        parts.append(rendered)
        parts.append("```")
        parts.append("")

    parts.extend(
        [
            "## Real cards from a recent run (current prompt's actual wild output)",
            "",
            REAL_CARDS_FROM_TABULAR_RUN,
            "",
            "## Your task (3 voices in parallel, HIGH reasoning effort)",
            "",
            "Score the CURRENT prompt (post all 5 edits) on the 3 SOTA axes. Be ruthless and specific.",
            "",
            "Concretely answer:",
            "",
            "1. **HELPFUL gap** — does the prompt push the LLM to emit cards that give downstream mutators everything they need? Show 1-2 specific clauses in the prompt that fall short, and propose CONCRETE rewrites.",
            "2. **BLOAT gap** — is the prompt itself bloated (verb list, delta shapes, examples, BAD lines)? Is it pushing the LLM toward bloated card text? Show 1-2 specific clauses and propose tightenings — but ONLY if the cut is genuinely safe (don't trade transferability for terseness).",
            "3. **TRANSFER gap** — do the BAD→GOOD pairs + GOOD examples teach a pattern that transfers across the 4 problem domains shown in the dry renders? Show 1-2 specific failures of transfer in the current pairs/examples, and propose CONCRETE replacements.",
            "4. **Dry-render-specific observations** — for EACH of the 4 problems, name ONE specific way the current prompt would fail to produce a SOTA card for that problem. (E.g. for kissing_number_12d, what does the LLM need to know that the prompt doesn't tell it?)",
            "5. **Real-card observations** — given the 8 real cards from the recent tabular run, name the TOP-2 prompt-driven defects (e.g. duplicate cards #2/#4, multi-knob bug #5, vague-mechanism cards #1/#2). Propose prompt changes that would have prevented each.",
            "6. **TOP-3 final changes** — if you could make exactly 3 CONCRETE edits to mutation/system.txt to push it from current-state to SOTA, what would they be? Show exact `old_string` → `new_string` (use snippets, not the whole file). Justify each on the HELPFUL/NOT-BLOATED/TRANSFERRABLE axes.",
            "",
            "## Hard constraints (NON-NEGOTIABLE)",
            "",
            "- **Problem-agnostic**: any examples or rewrites you propose must NOT bake in a single problem. Use `<placeholders>` or generic property-class language.",
            "- **Schema field names FROZEN**: cannot rename `description`, `explanation`, `changes`, `archetype`, `insights_used`, `code`, `justification`.",
            "- **Stay inside Rule 2 + Rule 3** of OUTPUT RULES. Other sections (ROLE, EVIDENCE INPUTS, ARCHETYPE, EXECUTION PRINCIPLES) are out of scope for this review.",
            "- **Keep all 4 load-bearing additions** intact: (a) 8-class property taxonomy, (b) numeric-trigger preference line, (c) `weak transfer-evidence` escape hatch, (d) 4-domain BAD→GOOD pairs.",
            "- **Do NOT propose `;when=` / `;risk=` / `;scope=` suffixes** to the description — they would collide with the packager's `;`-separated card-level suffixes (support, Δbest, co).",
            "- **Do NOT propose Pydantic validators** on the description field — explicit user feedback says fix producers (prompts), not validators.",
            "",
            "## Output format (STRICTLY valid JSON, no markdown fence around the JSON object)",
            "",
            "{",
            '  "helpful_gap": {',
            '    "diagnosis": "...",',
            '    "specific_clauses_falling_short": ["<excerpt of prompt clause>", "..."],',
            '    "concrete_rewrites": [{"old": "...", "new": "...", "why": "..."}]',
            "  },",
            '  "bloat_gap": {',
            '    "diagnosis": "...",',
            '    "specific_clauses": ["..."],',
            '    "concrete_tightenings": [{"old": "...", "new": "...", "safe_because": "..."}]',
            "  },",
            '  "transfer_gap": {',
            '    "diagnosis": "...",',
            '    "failing_pairs_or_examples": ["..."],',
            '    "concrete_replacements": [{"old": "...", "new": "...", "transfers_because": "..."}]',
            "  },",
            '  "per_problem_observations": [',
            '    {"problem": "heilbron", "what_prompt_misses_for_sota": "...", "concrete_fix": "..."},',
            '    {"problem": "tabular_regression", "what_prompt_misses_for_sota": "...", "concrete_fix": "..."},',
            '    {"problem": "kissing_number_12d", "what_prompt_misses_for_sota": "...", "concrete_fix": "..."},',
            '    {"problem": "chains/hover/static_soft", "what_prompt_misses_for_sota": "...", "concrete_fix": "..."}',
            "  ],",
            '  "real_card_defects": [',
            '    {"defect": "...", "evidence_card_nums": [...], "prompt_change_to_prevent": "..."},',
            '    {"defect": "...", "evidence_card_nums": [...], "prompt_change_to_prevent": "..."}',
            "  ],",
            '  "top_3_final_edits": [',
            '    {"rank": 1, "old_string": "...", "new_string": "...", "rationale_on_3_axes": {"helpful": "...", "not_bloated": "...", "transferrable": "..."}},',
            '    {"rank": 2, "old_string": "...", "new_string": "...", "rationale_on_3_axes": {"helpful": "...", "not_bloated": "...", "transferrable": "..."}},',
            '    {"rank": 3, "old_string": "...", "new_string": "...", "rationale_on_3_axes": {"helpful": "...", "not_bloated": "...", "transferrable": "..."}}',
            "  ],",
            '  "overall_verdict": "SOTA_READY | NEEDS_FINAL_TWEAKS | NEEDS_REWORK",',
            '  "notes": "..."',
            "}",
            "",
            "Be specific, concrete, and ruthless. Cite the exact text of the prompt clause you're commenting on. Propose verbatim edit strings, not abstract critique.",
        ]
    )

    return "\n".join(parts)


async def call_openrouter(
    client: httpx.AsyncClient, voice: dict, api_key: str, brief: str, attempt: int = 1
) -> dict:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/KhrulkovV/gigaevo-core-internal",
        "X-Title": "mutation-prompt-sota-final-ensemble",
    }
    body = {
        "model": voice["model"],
        "max_tokens": 60000,
        "messages": [{"role": "user", "content": brief}],
        **voice.get("extra", {}),
    }
    t0 = asyncio.get_event_loop().time()
    try:
        resp = await client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            json=body,
            timeout=1800.0,
        )
        elapsed = asyncio.get_event_loop().time() - t0
        if resp.status_code != 200:
            return {
                "alias": voice["alias"],
                "model": voice["model"],
                "ok": False,
                "status": resp.status_code,
                "body": resp.text[:2000],
                "elapsed_s": elapsed,
                "attempt": attempt,
            }
        raw_text = resp.text
        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError as je:
            (
                OUTPUT_DIR / f"voice_{voice['alias']}_raw_body_attempt{attempt}.txt"
            ).write_text(raw_text)
            if attempt < 2:
                await asyncio.sleep(3.0)
                return await call_openrouter(
                    client, voice, api_key, brief, attempt=attempt + 1
                )
            return {
                "alias": voice["alias"],
                "model": voice["model"],
                "ok": False,
                "error": f"JSON parse error after {attempt} attempts: {je}; raw body saved",
                "elapsed_s": elapsed,
                "attempt": attempt,
                "raw_body_head": raw_text[:500],
                "raw_body_tail": raw_text[-500:],
            }
        return {
            "alias": voice["alias"],
            "model": voice["model"],
            "ok": True,
            "elapsed_s": elapsed,
            "attempt": attempt,
            "data": data,
        }
    except Exception as e:
        return {
            "alias": voice["alias"],
            "model": voice["model"],
            "ok": False,
            "error": str(e),
            "elapsed_s": asyncio.get_event_loop().time() - t0,
            "attempt": attempt,
        }


async def main() -> int:
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        print("OPENROUTER_API_KEY missing", file=sys.stderr)
        return 2

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    template = PROMPT_PATH.read_text()

    rendered_problems: list[tuple[str, str]] = []
    for label, prob_dir in DRY_RENDER_PROBLEMS:
        rendered = render_full_prompt(
            prob_dir / "task_description.txt", prob_dir / "metrics.yaml", template
        )
        rendered_problems.append((label, rendered))
        # Save each render to disk for inspection
        safe_name = label.split()[0].replace("/", "_")
        (OUTPUT_DIR / f"dry_render_{safe_name}.txt").write_text(rendered)

    brief = build_brief(rendered_problems)
    (OUTPUT_DIR / "ensemble_brief.md").write_text(brief)
    brief_size_kb = len(brief) / 1024
    print(f"Brief size: {brief_size_kb:.1f} KB", file=sys.stderr)

    voices = [
        {
            "alias": "anthropic_opus",
            "model": "anthropic/claude-opus-4.1",
            "extra": {"extra_body": {"reasoning": {"effort": "high"}}},
        },
        {
            "alias": "google_gemini25",
            "model": "google/gemini-2.5-pro",
            "extra": {"extra_body": {"reasoning": {"effort": "high"}}},
        },
        {
            "alias": "openai_o3",
            "model": "openai/o3",
            "extra": {"reasoning_effort": "high"},
        },
    ]

    proxy = os.environ.get("HTTPS_PROXY")
    async with httpx.AsyncClient(proxy=proxy) as client:
        results = await asyncio.gather(
            *[call_openrouter(client, v, api_key, brief) for v in voices]
        )

    summary = []
    for voice, result in zip(voices, results):
        out_path = OUTPUT_DIR / f"voice_{voice['alias']}.json"
        out_path.write_text(json.dumps(result, indent=2))
        row = {
            "alias": voice["alias"],
            "model": voice["model"],
            "ok": result.get("ok"),
            "elapsed_s": result.get("elapsed_s"),
            "attempt": result.get("attempt"),
            "path": str(out_path),
        }
        if result.get("ok") and "data" in result:
            choices = result["data"].get("choices", []) or []
            if choices:
                msg = choices[0].get("message") or {}
                content = msg.get("content") or msg.get("reasoning") or ""
                row["content_chars"] = len(content)
                row["finish_reason"] = choices[0].get("finish_reason")
                row["used_field"] = "content" if msg.get("content") else "reasoning"
                if content:
                    (OUTPUT_DIR / f"voice_{voice['alias']}_response.md").write_text(
                        content
                    )
        else:
            row["error_head"] = (result.get("error") or result.get("body", ""))[:500]
        summary.append(row)

    (OUTPUT_DIR / "run_summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
