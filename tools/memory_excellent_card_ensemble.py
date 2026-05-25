"""3-voice OpenRouter ensemble to converge on 'Excellent Memory Card' spec.

Reads PRE-v4 cards + v4 cards + goldilocks criterion + current grammar/caps,
then asks 3 frontier voices three independent questions:

1. Define an excellent memory card (slot pattern + length range + worked examples).
2. Rank intervention sites by leverage on tautology rate.
3. Adversarial: what failure mode survives the top-ranked fix?

Each voice runs in parallel; full JSON saved per voice.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
import json
import os
from pathlib import Path
import sys

import httpx

OUTPUT_DIR = Path("/home/jovyan/gigaevo/output/memory_excellent_card_ensemble_20260524")
PRE_V4_INDEX = Path(
    "/home/jovyan/gigaevo/output/tabular_regression_intra_extra_20260523_161718/memory/api_index.json"
)
V4_INDEX = Path(
    "/home/jovyan/gigaevo/outputs/2026-05-24/13-49-55/memory/api_index.json"
)

CRITERION = (
    "Memory-card mechanism clauses (the why-it-transfers text after `:` in packed grammar) must be "
    "**dataset-specific but yet generalizable** — neither a textbook restatement of the verb+delta, "
    "nor a hyper-specific factoid tied to one task. The mutator reads cards to learn TRANSFERABLE "
    "LEVERS across tasks. A tautology ('deeper trees model complex interactions') carries no signal "
    "because it's true of every dataset. A hyper-specific claim ('California Housing log1p distorts "
    "gradients for median income > 0.42') doesn't transfer. The goldilocks zone names a PROPERTY that "
    "this run revealed (e.g. 'hard cap at 5.0', 'RMSE penalty from sub-0.15 predictions', "
    "'heavy-tailed population count') AT A LEVEL OF ABSTRACTION that maps to other tasks "
    "('any capped target', 'any asymmetric metric region', 'any heavy-tailed feature')."
)

PACKED_GRAMMAR = "[UNVERIFIED_]<VERB> <target> [<old>→<new>]: <mechanism>; support=N; Δbest=+F; co=[t1,t2]"
WHITELIST_VERBS = "{ADD, REMOVE, UPDATE, SWAP, USE}"

CONSTRAINTS = (
    "FROZEN: card field NAMES + TYPES (external GAM contract requires schema stability). "
    "Adding NEW pydantic fields is allowed but heavyweight (touches schema, validators, all consumers). "
    "OUT OF SCOPE: post-hoc Python regex validators that REJECT or REWRITE cards after emission "
    "(user explicit: 'we don't need post-hoc validators; let us operate by purely tuning LLM to "
    "provide more useful and concrete suggestions in the goldilocks zone'). "
    "Current binding length cap: `why-it-transfers` ≤12 words (gigaevo/prompts/mutation/system.txt:75). "
    "Schema has NO max_length on description. The 35-word cap on insights/user.txt is on a separate "
    "pipeline that intra_extra_memory does NOT invoke."
)


def _format_cards(cards: list[dict], prefix: str) -> str:
    out = []
    for i, c in enumerate(cards):
        out.append(
            f"  {prefix}{i:02d} [{c.get('category')}] {c.get('description', '')}"
        )
    return "\n".join(out)


def build_context() -> str:
    pre = json.loads(PRE_V4_INDEX.read_text())
    pre_cards = list(pre.get("memory_cards", {}).values())
    pre_general = [c for c in pre_cards if c.get("category") == "general"]

    v4 = json.loads(V4_INDEX.read_text())
    v4_cards = list(v4.get("memory_cards", {}).values())

    return f"""\
# CONTEXT: GigaEvo Memory-Card Quality Audit

You are one of three independent expert voices reviewing a memory-card system for an
LLM-guided evolutionary algorithm. The mutator LLM reads these cards to learn transferable
levers across runs. The other two voices answer the same questions in parallel.

## What the cards are

Each card describes ONE change introduced into a Python program during evolution.
Cards use a "packed grammar":
    {PACKED_GRAMMAR}

Verb whitelist: {WHITELIST_VERBS}

The mechanism clause (the part after `:`) is the WHY-IT-TRANSFERS text. That clause
is where quality is decided — it must be **dataset-specific but yet generalizable**.

## The quality criterion

{CRITERION}

## Hard constraints on any fix proposal

{CONSTRAINTS}

## DATA: 18 PRE-v4 general/idea cards (from a 800-mutant run, before recent prompt fixes)

These are unfiltered — some hit the goldilocks zone, others are tautological textbook
explanations. Approximately 11/18 are graded as goldilocks-specific by a regex tautology
catcher; the remaining 7 match templates like "models complex X interactions",
"captures X patterns", "fundamental X for Y".

{_format_cards(pre_general, prefix="PRE-v4 #")}

## DATA: v4-prompt run cards (run terminated early at 266/800 mutants due to OutputTooLarge)

The v4 grammar packed-form prompt was deployed for this run. Note: only 2 idea cards
emitted because the run died early. One is goldilocks-specific (hard-cap-at-5.0),
the other survived as tautology even under the v4 prompt:

{_format_cards(v4_cards, prefix="v4 #")}

## Current upstream-prompt anchor (mutation/system.txt:60-80, abbreviated)

The prompt asks the mutation LLM to emit `MutationChange.description` as:
    `<VERB> <target> <old>→<new>: <why-it-transfers>`
with `<why-it-transfers>` constrained to **≤12 words** naming the specific *causal mechanism*
— HOW the change works, not WHAT goal it serves. "Restating the metric goal" is forbidden.

Despite this guidance, both PRE-v4 (~39% tautology) and v4 (50% tautology on the 2-sample
post-fix run) still emit templated textbook sentences when the LLM defaults to safe ground.

## The three questions (answer all three independently)

### Q1. Define an "excellent memory card"

Produce a concrete spec. Cover:
  - What the description MUST contain (mandatory slots / clauses / pieces of evidence)
  - What it MUST NOT contain (forbidden patterns, anti-templates)
  - Target word-range that hits goldilocks (justify against current 12-word cap)
  - Canonical structural pattern — pick ONE of (a) slot-list with explicit labels in the
    description text, (b) implicit sentence template, (c) something else — and defend it
  - Show 2 worked EXCELLENT examples (for tabular ML mutations like these), and 1 ANTI-example
    (textbook-tautology version of the same change)

### Q2. Where to intervene in the stack

Rank these candidate interventions by expected effect-per-unit-effort on tautology rate:
  (a) Widen the 12-word cap to 25-35 words (prompt-only edit)
  (b) Add 4-6 contrastive few-shot examples (tautology → goldilocks) in mutation/system.txt
  (c) Split `description` into structured pydantic slots (dataset_property + lever + transfer_class)
      via NEW MutationChange fields — joined into the packed grammar at serialize time
  (d) Add a `transfer_class:<label>` keyword that the LLM must emit (smaller schema touch
      than (c) — uses existing `keywords` field)
  (e) Inject the current run's TASK CONTEXT (task description, dataset properties, primary
      metric definition) into the mutation prompt so the LLM has concrete anchors to cite

For each: estimate effect-on-tautology-rate (qualitative: high/med/low) AND effort
(qualitative: low/med/high). Give your final ranking with one-line reasoning each.

### Q3. Adversarial: predicted failure mode

Name the single most likely way the system will STILL emit tautologies AFTER your top-ranked
fix from Q2 ships. Be specific about which prompt path / which kind of mutation /
which dataset shape would defeat it. This is self-critique — don't be polite.

## OUTPUT FORMAT

Return a single JSON object with these top-level keys:
    {{
      "Q1_excellent_card_spec": {{...your full spec, free-form structured...}},
      "Q2_intervention_ranking": [{{"option": "a|b|c|d|e", "rank": N, "effect": "...", "effort": "...", "reasoning": "..."}}, ...],
      "Q3_predicted_failure_mode": "...full paragraph..."
    }}

Be specific. Cite the data above. No prose preamble outside the JSON.
"""


async def call_openrouter(
    client: httpx.AsyncClient, model: str, payload: dict, api_key: str
) -> dict:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/KhrulkovV/gigaevo-core-internal",
        "X-Title": "memory-card-quality-ensemble",
    }
    body = {"model": model, "max_tokens": 16000, **payload}
    t0 = asyncio.get_event_loop().time()
    try:
        resp = await client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            json=body,
            timeout=600.0,
        )
        elapsed = asyncio.get_event_loop().time() - t0
        if resp.status_code != 200:
            return {
                "model": model,
                "ok": False,
                "status": resp.status_code,
                "body": resp.text,
                "elapsed_s": elapsed,
            }
        data = resp.json()
        return {"model": model, "ok": True, "elapsed_s": elapsed, "data": data}
    except Exception as e:
        return {
            "model": model,
            "ok": False,
            "error": str(e),
            "elapsed_s": asyncio.get_event_loop().time() - t0,
        }


async def main() -> int:
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        print("OPENROUTER_API_KEY not set", file=sys.stderr)
        return 2

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    context = build_context()
    (OUTPUT_DIR / "ensemble_brief.md").write_text(context)

    voices = [
        {
            "alias": "anthropic_opus",
            "model": "anthropic/claude-opus-4.1",
            "payload": {
                "messages": [{"role": "user", "content": context}],
                "extra_body": {"reasoning": {"effort": "high"}},
            },
        },
        {
            "alias": "google_gemini25",
            "model": "google/gemini-2.5-pro",
            "payload": {
                "messages": [{"role": "user", "content": context}],
                "extra_body": {"reasoning": {"effort": "high"}},
            },
        },
        {
            "alias": "openai_o3",
            "model": "openai/o3",
            "payload": {
                "messages": [{"role": "user", "content": context}],
                "extra_body": {"reasoning": {"effort": "high"}},
            },
        },
    ]

    async with httpx.AsyncClient() as client:
        tasks = [
            call_openrouter(client, v["model"], v["payload"], api_key) for v in voices
        ]
        results = await asyncio.gather(*tasks)

    summary = []
    for voice, result in zip(voices, results):
        out_path = OUTPUT_DIR / f"voice_{voice['alias']}.json"
        out_path.write_text(json.dumps(result, indent=2))
        summary_row = {
            "alias": voice["alias"],
            "model": voice["model"],
            "ok": result.get("ok"),
            "elapsed_s": result.get("elapsed_s"),
            "path": str(out_path),
        }
        if result.get("ok") and "data" in result:
            choices = result["data"].get("choices", [])
            if choices:
                content = choices[0].get("message", {}).get("content", "")
                summary_row["content_chars"] = len(content)
                (OUTPUT_DIR / f"voice_{voice['alias']}_response.md").write_text(content)
        else:
            summary_row["error"] = result.get("error") or result.get("body", "")[:500]
        summary.append(summary_row)

    (OUTPUT_DIR / "ensemble_run_summary.json").write_text(
        json.dumps(
            {
                "started_at": datetime.utcnow().isoformat() + "Z",
                "voices": summary,
            },
            indent=2,
        )
    )

    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
