# Benchmark Survey: Adversarial Co-Evolution of Python Programs

**Date**: April 2026
**Purpose**: Identify well-known benchmarks where adversarial co-evolution (two MAP-Elites populations + LLM-guided mutation) can demonstrate clear value for a NeurIPS 2026 submission.

---

## Executive Summary

After thorough analysis of 40+ benchmarks across 6 categories, the **top 3 recommended benchmarks** for adversarial co-evolution are:

1. **EvalPlus / HumanEval+ / MBPP+** (Code + Test co-evolution) -- most natural fit, proven gap, high visibility
2. **HarmBench** (Attack prompts vs defense filters) -- highest impact, 900+ citations, active area
3. **CO-Bench / BBOB** (Solvers vs hard instances) -- cleanest adversarial framing, proven by EALG

The survey below provides detailed analysis for each benchmark category.

---

## 1. Red Teaming / LLM Safety Benchmarks

### HarmBench
- **URL**: https://www.harmbench.org/ | [Paper](https://arxiv.org/abs/2402.04249) | Published at ICML 2024
- **Citations**: ~920 (Semantic Scholar, Apr 2026) -- **most-cited red teaming benchmark**
- **GitHub**: https://github.com/centerforaisafety/HarmBench (~1k stars)
- **What it is**: Standardized evaluation of 18 attack methods against 33 LLMs/defenses. 510 harmful behaviors across 7 categories.
- **Current SOTA**: J2 (Jailbreaking-to-Jailbreak) achieves 93% ASR against GPT-4o. Multi-turn human jailbreaks >70% ASR. No model is robust to all attacks; no attack breaks all models.
- **Saturated?**: NO -- continuous arms race between attacks and defenses. New attacks keep emerging.
- **Adversarial co-evolution fit**:
  - **Population A**: Evolve attack strategies (Python programs that generate jailbreak prompts)
  - **Population B**: Evolve defense filters (Python programs that detect/block attacks)
  - MAP-Elites diversity across attack styles (role-play, encoding, multi-turn, etc.)
- **Integration difficulty**: MEDIUM -- HarmBench has clean API, but needs LLM inference for evaluation ($$)
- **NeurIPS publishability**: HIGH -- safety is a flagship NeurIPS topic. Beating PAIR/GCG/AutoDAN with evolved attacks would be headline-worthy.
- **Key risk**: Ethical review may flag automated attack generation. Need to frame as defense improvement.

### JailbreakBench
- **URL**: https://jailbreakbench.github.io/ | [Paper](https://arxiv.org/abs/2404.01318) | NeurIPS 2024 D&B Track
- **Citations**: ~200+
- **What it is**: 200 distinct behaviors, official leaderboard tracking attacks vs defenses
- **Current SOTA**: Various attacks achieve 40-90% ASR depending on target model
- **Saturated?**: NO
- **Adversarial fit**: Same as HarmBench but smaller scale. Could use as secondary evaluation.
- **Integration difficulty**: LOW -- pip installable, clean Python API

### StrongREJECT
- **URL**: https://github.com/dsbowen/strong_reject | [Blog](https://bair.berkeley.edu/blog/2024/08/28/strong-reject/)
- **Citations**: ~100+
- **What it is**: 313 forbidden prompts + continuous scoring (not binary). Spearman 0.90 correlation with human judges.
- **Current SOTA**: Binary autograders saturate early; StrongREJECT's continuous scoring still differentiates.
- **Adversarial fit**: Better as an evaluator than a benchmark. Use as the scoring function for HarmBench co-evolution.
- **Integration difficulty**: LOW

### Tensor Trust (Prompt Injection Game)
- **URL**: https://tensortrust.ai/ | [Paper](https://arxiv.org/abs/2311.01011) | ICLR 2024
- **Citations**: ~100+
- **What it is**: 563K prompt injection attacks + 118K defenses from an online game. Both attack and defense are text.
- **Saturated?**: NO -- new attack types keep emerging
- **Adversarial fit**: EXCELLENT -- the game IS adversarial co-evolution. Pop A = attack prompts, Pop B = defense system prompts.
- **Integration difficulty**: LOW -- text-in, text-out
- **NeurIPS publishability**: MEDIUM-HIGH -- novel framing but smaller community than HarmBench

### Rainbow Teaming (MAP-Elites for Red Teaming)
- **URL**: [Paper](https://arxiv.org/abs/2402.16822) | NeurIPS 2024
- **What it is**: Uses MAP-Elites to generate diverse adversarial prompts. 90%+ ASR across tested models.
- **Why it matters for us**: This is MAP-Elites for attack evolution -- but it's **single-population** (attacks only, no co-evolving defense). Our contribution would be adding the defense population.
- **Follow-up**: RainbowPlus (Apr 2025) extends with multi-element archives.
- **Adversarial fit**: We directly extend this with two-population co-evolution.

### Quality-Diversity Red-Teaming (QDRT)
- **URL**: [Paper](https://arxiv.org/pdf/2506.07121) (June 2025)
- **What it is**: MAP-Elites-style behavioral replay buffer for training attacker models across risk categories and attack styles.
- **Why it matters**: Most direct prior work to ours in the safety domain. We'd need to differentiate clearly.

**VERDICT FOR CATEGORY 1**: HarmBench is the gold standard. Framing as "Rainbow Teaming + co-evolving defense" would be strong positioning. High impact but needs ethical framing.

---

## 2. Code Generation / Program Synthesis Benchmarks

### EvalPlus (HumanEval+ / MBPP+)
- **URL**: https://evalplus.github.io/ | [Paper](https://arxiv.org/abs/2305.01210) | NeurIPS 2023 + COLM 2024
- **Citations**: 500+
- **GitHub**: https://github.com/evalplus/evalplus (~1.5k stars)
- **What it is**: 80x/35x test augmentation for HumanEval/MBPP. GPT-4 drops from 88.4% to 76.2%.
- **Current SOTA**: Kimi K2 leads at 80.3% on HumanEval+ (pass@1). o1-mini 96.2% on original HumanEval but only 76.2% on HumanEval Pro.
- **Saturated?**: Original HumanEval YES (~96%+). HumanEval+ NO (top is ~80%). MBPP+ NO (top ~88%).
- **Adversarial co-evolution fit**:
  - **Population A**: Evolve Python solutions (code generators)
  - **Population B**: Evolve adversarial test cases that break solutions
  - This is EXACTLY the adversarial setup. Tests expose bugs in solutions; solutions evolve to handle edge cases.
  - MAP-Elites could map tests by: input type (edge cases, boundary, type errors), code complexity, coverage profile
- **Integration difficulty**: LOW -- pure Python, EvalPlus is pip-installable, problems are well-defined
- **NeurIPS publishability**: HIGH -- EvalPlus is already a NeurIPS paper. Showing that adversarial test evolution finds even more bugs than 80x augmentation would be a clear contribution.
- **Key advantage**: This is the cleanest benchmark for our system. Solutions and tests are both Python programs.

### LiveCodeBench
- **URL**: https://livecodebench.github.io/ | [Paper](https://arxiv.org/abs/2403.07974)
- **Citations**: 200+
- **What it is**: Continuously updated competitive programming problems from LeetCode/AtCoder/Codeforces
- **Current SOTA**: Gemini 3 Pro 91.7%, DeepSeek V3.2 89.6%. Hard problems: 40-60% pass rate.
- **Saturated?**: NO -- continuously refreshed, hard problems remain challenging
- **Adversarial fit**: MEDIUM -- problems are fixed (from contests), so only test co-evolution applies
- **Integration difficulty**: MEDIUM -- requires execution sandbox

### SWE-bench / SWE-bench Verified
- **URL**: https://www.swebench.com/
- **Current SOTA**: Claude 4.5 Opus at 76.8% resolve rate (SWE-bench Verified)
- **Saturated?**: NO -- top is 76.8%, plenty of room
- **Adversarial fit**: LOW -- problems are real GitHub issues, not synthetically generated. Hard to frame adversarially.
- **Integration difficulty**: HIGH -- requires full repo context, environment setup

### CodeContests / CodeContests+
- **URL**: https://github.com/google-deepmind/code_contests | [CodeContests+ paper](https://arxiv.org/abs/2506.05817)
- **What it is**: Competitive programming + improved test suites
- **Current SOTA**: Original had 62% false positive rate; CodeContests+ significantly improves
- **Adversarial fit**: MEDIUM-HIGH -- Codehacks dataset (288K adversarial tests from Codeforces) shows the value of adversarial test generation
- **Integration difficulty**: MEDIUM

### Code-A1: Adversarial Evolving of Code LLM and Test LLM
- **URL**: [Paper](https://arxiv.org/abs/2603.15611) (March 2026)
- **What it is**: Code LLM vs Test LLM via RL. Test LLM rewarded for failing code; Code LLM rewarded for passing tests.
- **Results**: 3B model achieves 83.5% on HumanEval+, surpasses 7B baseline on test generation
- **Why it matters**: **Most direct competitor**. But uses RL fine-tuning, not evolutionary QD. No MAP-Elites diversity.
- **Our differentiation**: We evolve programs (not model weights), use MAP-Elites for diversity, and don't require fine-tuning.

### EvolveCoder
- **URL**: [Paper](https://arxiv.org/abs/2603.12698) (March 2026)
- **What it is**: Evolves test cases via adversarial verification for code RL training
- **Results**: +4.2 points across 4 benchmarks. Pass@1 drops from 43.8% to 31.2% with evolved tests.
- **Adversarial fit**: Directly relevant as a baseline

### Codehacks Dataset
- **URL**: [Paper](https://arxiv.org/abs/2503.23466) | IEEE ICST 2025
- **What it is**: 288,617 adversarial test inputs from Codeforces "hacking" mechanic. 42.1% success rate.
- **Why it matters**: Real-world evidence that adversarial test generation is valuable for competitive programming

**VERDICT FOR CATEGORY 2**: EvalPlus (HumanEval+/MBPP+) is the best fit. Clean adversarial setup, well-known benchmark, not saturated, pure Python, and our approach directly extends EvalPlus's test augmentation with evolutionary adversarial dynamics. Code-A1 and EvolveCoder are direct competitors to cite and beat.

---

## 3. Cybersecurity Benchmarks

### CyberSecEval 4 (Purple Llama)
- **URL**: https://meta-llama.github.io/PurpleLlama/CyberSecEval/
- **GitHub**: https://github.com/meta-llama/PurpleLlama (~3.5k stars)
- **What it is**: 4 generations of cybersecurity benchmarks. CyberSecEval 4 adds AutoPatchBench (136 C/C++ vulnerabilities), CyberSOCEval (malware analysis + threat intelligence), and prompt injection tests.
- **Current SOTA**: 26-41% successful prompt injections across tested models. AutoPatchBench: ~15% fix rate.
- **Saturated?**: NO -- very low solve rates
- **Adversarial fit**: MEDIUM -- could evolve attack code vs defense patches, but C/C++ focus doesn't align with Python evolution
- **Integration difficulty**: HIGH -- requires C/C++ compilation, fuzzing infrastructure
- **NeurIPS publishability**: MEDIUM -- security community is somewhat separate from ML venues

### CTF Benchmarks (NYU CTF Bench, CTFusion, InterCode-CTF)
- **NYU CTF Bench**: [Paper](https://arxiv.org/abs/2406.05590) -- scalable open-source CTF benchmark
- **InterCode-CTF**: Saturated at high-school level (95% solve rate)
- **CTFusion**: Streaming evaluation on live CTFs to avoid contamination
- **Current SOTA**: AI agents solve 83-95% of easy CTFs, but struggle with harder ones
- **Adversarial fit**: LOW -- CTFs are fixed puzzles, not programs that compete
- **Integration difficulty**: HIGH

### ARC (Autonomous Cyber Resilience)
- **URL**: [Paper](https://arxiv.org/abs/2506.20102) (June 2025)
- **What it is**: Co-evolutionary arms race in a Digital Twin sandbox. Red DRL agent discovers attacks; Blue ensemble agent defends.
- **Results**: Co-evolution provides 27% performance improvement
- **Adversarial fit**: HIGH -- directly adversarial co-evolution, but uses RL not program evolution
- **Integration difficulty**: HIGH -- requires industrial control system simulation

**VERDICT FOR CATEGORY 3**: Cybersecurity benchmarks are mostly in C/C++ and require specialized infrastructure. Not a natural fit for Python program evolution unless we focus on prompt injection (which overlaps with Category 1). The ARC concept is inspiring but the specific benchmarks don't fit.

---

## 4. Black-Box Optimization Benchmarks

### BBOB/COCO
- **URL**: https://numbbo.github.io/coco/ | https://github.com/numbbo/coco
- **Citations**: 1000+ (the platform paper)
- **What it is**: 24 scalable benchmark functions for black-box optimization, used in annual GECCO workshops since 2009
- **Current SOTA**: Various CMA-ES variants dominate. Well-characterized function landscape.
- **Saturated?**: PARTIALLY -- standard functions are well-understood, but noisy/constrained/mixed-integer variants are not
- **Adversarial co-evolution fit**:
  - **Population A**: Evolve optimizer algorithms (Python)
  - **Population B**: Evolve deceptive fitness landscapes (Python functions)
  - Optimizers improve by handling harder landscapes; landscapes improve by fooling better optimizers
- **Integration difficulty**: LOW -- pure Python evaluation, clean API
- **NeurIPS publishability**: MEDIUM -- optimization community overlaps with ML but is niche at NeurIPS

### CO-Bench (Combinatorial Optimization Benchmark)
- **URL**: https://github.com/sunnweiwei/CO-Bench | [Paper](https://arxiv.org/abs/2504.04310) | **AAAI 2026**
- **What it is**: 36 problems across 8 categories (TSP, bin packing, scheduling, etc.) evaluating LLM agents as algorithm designers
- **Current SOTA**: FunSearch scores 0.842 (best), classical solver 0.797. LLMs beat classical on 25/36 problems.
- **Saturated?**: NO -- significant room for improvement on hard instances
- **Adversarial fit**: HIGH -- directly about evolving optimization algorithms. EALG (below) has already demonstrated co-evolution here.
- **Integration difficulty**: LOW -- Python, well-defined evaluation
- **NeurIPS publishability**: MEDIUM-HIGH -- algorithm discovery is hot topic (AlphaEvolve, FunSearch)

### EALG (Evolutionary Adversarial LLM-Guided Generators)
- **URL**: [Paper](https://arxiv.org/abs/2506.02594) (June 2025)
- **What it is**: Co-evolves instance generators (harder problems) and heuristic solvers using LLMs
- **Results**: EALG instances increase optimality gap for SOTA solvers from 0.7% to >9% on TSP400. Co-evolved solvers generalize across tasks.
- **Why it matters**: **Most direct prior work for the optimization domain**. Demonstrates that adversarial co-evolution works for algorithm evolution. BUT does not use MAP-Elites / quality-diversity.
- **Our differentiation**: MAP-Elites diversity over algorithm strategies, not just quality optimization.

### SAT Competition + SATLUTION
- **URL**: https://satcompetition.github.io/2025/ | [SATLUTION paper](https://arxiv.org/abs/2509.07367)
- **SATLUTION results**: Evolved solvers beat human-designed SAT Competition 2025 winners (344-347 vs 334-331 instances solved). <$20K, 90K CPU-hours, 10K+ LOC evolved.
- **Adversarial fit**: MEDIUM -- SAT is solver-only (no adversarial instance generation in competition format)
- **Integration difficulty**: HIGH -- C/C++ solvers, not Python
- **NeurIPS publishability**: HIGH -- SATLUTION itself is likely a top-tier paper

**VERDICT FOR CATEGORY 4**: CO-Bench is the best option -- clean Python interface, directly evaluates LLM-evolved algorithms, AAAI 2026 venue validates quality. EALG is the direct competitor; we differentiate with MAP-Elites diversity. BBOB is classic but may be too niche for NeurIPS.

---

## 5. Adversarial Robustness Benchmarks

### RobustBench
- **URL**: https://robustbench.github.io/ | [Paper](https://arxiv.org/abs/2010.09670) | NeurIPS 2021 D&B
- **Citations**: 1500+
- **GitHub**: https://github.com/RobustBench/robustbench (~1.5k stars)
- **Current SOTA (CIFAR-10 Linf, eps=8/255)**: 73.71% robust accuracy (top model), clean 93.68%
- **Saturated?**: NO -- large gap between clean (93-95%) and robust (67-74%) accuracy
- **Adversarial fit**:
  - **Population A**: Evolve attack algorithms (adversarial perturbation strategies)
  - **Population B**: Evolve defense architectures or adversarial training procedures
  - BUT: both populations are typically neural networks, not Python programs
- **Integration difficulty**: HIGH -- requires GPU training, PyTorch models, not simple Python functions
- **NeurIPS publishability**: HIGH (if results are strong) but WRONG FIT for GigaEvo (evolves Python programs, not neural nets)

### AutoAttack
- Part of RobustBench. Ensemble of 4 attacks (APGD-CE, APGD-DLR, FAB, Square Attack).
- Not a standalone benchmark.

**VERDICT FOR CATEGORY 5**: RobustBench is extremely well-known but fundamentally about neural network robustness, not Python program evolution. Unless we frame it as "evolve the attack algorithm code" (which is unconventional), this doesn't fit GigaEvo's paradigm.

---

## 6. Code Optimization / Refactoring Benchmarks

### PIE (Performance-Improving Edits)
- **URL**: https://pie4perf.com/ | [Paper](https://openreview.net/forum?id=ix7rLVHXyY)
- **GitHub**: https://github.com/LearningOpt/pie
- **What it is**: 35K code editing pairs where one version is faster. Evaluation on deterministic gem5 simulator.
- **Current SOTA**: Best models achieve 6-9x average speedup (C++ focus). Chain-of-Thought: 7.53x. Best human: 9.56x.
- **Saturated?**: NO -- significant room for optimization, especially on Python code
- **Adversarial co-evolution fit**:
  - **Population A**: Evolve fast Python implementations
  - **Population B**: Evolve stress-test inputs that expose worst-case performance
  - MAP-Elites diversity over optimization strategies (algorithmic vs micro-optimization vs data structure choices)
- **Integration difficulty**: MEDIUM -- needs execution timing infrastructure, but Python functions are natural
- **NeurIPS publishability**: MEDIUM-HIGH -- code optimization is practical and impactful
- **Key concern**: PIE focuses on C++ competitive programming code. A Python equivalent would need to be created or found.

### AdverTest (Test vs Mutant)
- **URL**: [Paper](https://arxiv.org/abs/2602.08146) (Feb 2026)
- **What it is**: Two LLM agents -- test generator vs mutant generator -- compete to improve fault detection
- **Results**: 66.6% FDR on Defects4J (+8.6% over HITS SOTA), 34% cheaper than baselines
- **Adversarial fit**: DIRECTLY relevant as a baseline. Java-focused though.
- **Our differentiation**: We evolve programs (not just prompts to an LLM), use MAP-Elites for diverse strategies

### CLOVER (Test Case Generation Benchmark)
- **URL**: [Paper](https://openreview.net/forum?id=gPpQa4PGEZ) | ICLR 2025
- **What it is**: Benchmark for evaluating test case generation quality
- **Adversarial fit**: MEDIUM -- evaluation benchmark, not an adversarial setup itself

### CodeHacker / CodeHackerBench
- **URL**: [Paper](https://arxiv.org/abs/2602.20213) (Feb 2026)
- **What it is**: LLM agent generates adversarial test inputs to break competitive programming solutions
- **Adversarial fit**: HIGH -- directly about adversarial test generation for code

**VERDICT FOR CATEGORY 6**: PIE + adversarial input generation is promising but requires Python adaptation. AdverTest is the closest competitor in the test-vs-code adversarial space.

---

## Related Work: Adversarial Co-Evolution Frameworks

These are not benchmarks but frameworks that demonstrate the approach:

### Digital Red Queen (DRQ) -- Sakana AI + MIT
- **URL**: https://pub.sakana.ai/drq/ | [Paper](https://arxiv.org/abs/2601.03335) (Jan 2026)
- **What it is**: Self-play algorithm evolving assembly warriors in Core War using LLMs (GPT-4.1 mini)
- **Results**: Evolved warriors match/surpass 96.3% of human-designed warriors. Convergent evolution observed.
- **Key for us**: Proves adversarial LLM program evolution works. But single domain, no MAP-Elites.

### GAME (Generative Adversarial MAP-Elites)
- **Venue**: ALife 2025
- **What it is**: Two-population MAP-Elites adversarial co-evolution. No LLM mutation.
- **Key for us**: Proves MAP-Elites + adversarial works. We add LLM mutation.

### Multi-Agent Evolve: LLM Self-Improve through Co-evolution
- **URL**: [Paper](https://arxiv.org/abs/2510.23595) (Oct 2025)
- **What it is**: Multiple LLMs co-evolve by generating challenges for each other

### CURE / Co-FunSearch
- Co-evolving coder + tester LLMs (NeurIPS 2025 Spotlight)
- Cooperative, not adversarial. Fine-tunes model weights.

---

## Synthesis: Recommended Benchmark Strategy for NeurIPS 2026

### Tier 1: Primary Benchmark (must include)

**EvalPlus (HumanEval+ / MBPP+) with adversarial test co-evolution**

| Criterion | Score |
|-----------|-------|
| Reviewer recognition | 10/10 -- NeurIPS paper, universally known |
| Not saturated | YES -- top HumanEval+ is 80.3%, top MBPP+ is 88.6% |
| Natural adversarial fit | 10/10 -- solutions vs tests is the canonical adversarial pair |
| Python program evaluation | 10/10 -- everything is Python |
| Integration difficulty | LOW -- pip install evalplus |
| Competition awareness | Code-A1, EvolveCoder are direct competitors; we differentiate with MAP-Elites QD |
| Publishable impact | HIGH -- "Adversarial co-evolution finds 3x more bugs than EvalPlus's 80x augmentation" |

**Setup**: Pop A evolves Python solution functions. Pop B evolves Python test functions (assert-based). Fitness_A = pass rate across evolved tests. Fitness_B = fail rate across evolved solutions.

### Tier 2: Generality Demonstration (include 1-2)

**Option A: CO-Bench (Combinatorial Optimization)**
- Shows the approach generalizes beyond code testing
- Pop A = heuristic solver programs, Pop B = hard instance generator programs
- Beats EALG by adding MAP-Elites diversity
- AAAI 2026 paper validates benchmark quality

**Option B: HarmBench (Red Teaming / Safety)**
- Highest impact domain
- Pop A = attack strategy programs, Pop B = defense filter programs
- Extends Rainbow Teaming with co-evolving defense
- Risk: ethical review, LLM inference costs

**Option C: PIE-style Code Optimization**
- Pop A = optimized implementations, Pop B = worst-case inputs
- Practical impact story
- Needs Python adaptation of PIE

### Tier 3: Toy Domain for Analysis (optional)

**Core War / IPD (Iterated Prisoner's Dilemma)**
- Cheapest to run, easiest to analyze dynamics
- Direct comparison to DRQ and GAME
- Shows Red Queen dynamics clearly

### Recommended Paper Structure

1. **Method**: Adversarial MAP-Elites co-evolution with LLM-guided mutation (general framework)
2. **Primary domain**: EvalPlus -- adversarial test generation beats 80x augmentation
3. **Generality domain**: CO-Bench -- adversarial instance generation improves solvers
4. **Analysis domain**: Core War or IPD -- demonstrate convergent evolution, arms race dynamics
5. **Ablation**: MAP-Elites vs random selection, LLM mutation vs random mutation, co-evolution vs static evaluation

---

## Appendix: Full Benchmark Comparison Table

| Benchmark | Category | Citations | SOTA | Saturated? | Adversarial Fit | Python Native | Integration | NeurIPS Impact |
|-----------|----------|-----------|------|------------|----------------|---------------|-------------|----------------|
| HarmBench | Safety | 920+ | 93% ASR | NO | HIGH | MEDIUM | MEDIUM | HIGH |
| JailbreakBench | Safety | 200+ | varies | NO | HIGH | YES | LOW | MEDIUM-HIGH |
| Tensor Trust | Safety | 100+ | varies | NO | EXCELLENT | YES | LOW | MEDIUM |
| EvalPlus (HumanEval+) | Code Gen | 500+ | 80.3% | NO | EXCELLENT | YES | LOW | HIGH |
| LiveCodeBench | Code Gen | 200+ | 91.7% | NO | MEDIUM | YES | MEDIUM | MEDIUM-HIGH |
| SWE-bench | Code Gen | 500+ | 76.8% | NO | LOW | YES | HIGH | HIGH |
| CodeContests+ | Code Gen | 50+ | varies | NO | MEDIUM-HIGH | YES | MEDIUM | MEDIUM |
| CyberSecEval 4 | Security | 200+ | ~15% fix | NO | MEDIUM | NO (C/C++) | HIGH | MEDIUM |
| NYU CTF Bench | Security | 50+ | 83-95% | PARTIAL | LOW | PARTIAL | HIGH | MEDIUM |
| BBOB/COCO | Optimization | 1000+ | CMA-ES | PARTIAL | HIGH | YES | LOW | MEDIUM |
| CO-Bench | Optimization | 20+ | 0.842 | NO | HIGH | YES | LOW | MEDIUM-HIGH |
| RobustBench | Robustness | 1500+ | 73.7% | NO | HIGH concept | NO (neural) | HIGH | HIGH |
| PIE | Code Opt | 100+ | 9.6x | NO | HIGH | NO (C++) | MEDIUM | MEDIUM-HIGH |

---

## Sources

### Red Teaming / Safety
- [HarmBench paper](https://arxiv.org/abs/2402.04249)
- [HarmBench website](https://www.harmbench.org/)
- [JailbreakBench](https://jailbreakbench.github.io/)
- [JailbreakBench NeurIPS 2024](https://proceedings.neurips.cc/paper_files/paper/2024/file/63092d79154adebd7305dfd498cbff70-Paper-Datasets_and_Benchmarks_Track.pdf)
- [StrongREJECT blog](https://bair.berkeley.edu/blog/2024/08/28/strong-reject/)
- [StrongREJECT GitHub](https://github.com/dsbowen/strong_reject)
- [Tensor Trust paper](https://arxiv.org/abs/2311.01011)
- [Tensor Trust game](https://tensortrust.ai/)
- [Rainbow Teaming NeurIPS 2024](https://arxiv.org/abs/2402.16822)
- [RainbowPlus](https://arxiv.org/abs/2504.15047)
- [QDRT paper](https://arxiv.org/pdf/2506.07121)
- [General Analysis benchmarks](https://www.generalanalysis.com/benchmarks)
- [J2 Jailbreaking paper](https://static.scale.com/uploads/654197dc94d34f66c0f5184e/J2_02092025%20(1).pdf)

### Code Generation
- [EvalPlus website](https://evalplus.github.io/)
- [EvalPlus leaderboard](https://evalplus.github.io/leaderboard.html)
- [LiveCodeBench](https://livecodebench.github.io/)
- [LiveCodeBench leaderboard](https://livecodebench.github.io/leaderboard.html)
- [SWE-bench](https://www.swebench.com/)
- [BenchLM coding leaderboard March 2026](https://benchlm.ai/coding)
- [CodeContests+](https://arxiv.org/abs/2506.05817)
- [CodeContests GitHub](https://github.com/google-deepmind/code_contests)
- [Code-A1 paper](https://arxiv.org/abs/2603.15611)
- [EvolveCoder paper](https://arxiv.org/abs/2603.12698)
- [Codehacks dataset](https://arxiv.org/abs/2503.23466)
- [CodeHacker](https://arxiv.org/abs/2602.20213)
- [CLOVER test generation benchmark](https://openreview.net/forum?id=gPpQa4PGEZ)
- [HumanEval Pro / MBPP Pro](https://arxiv.org/abs/2412.21199)

### Cybersecurity
- [CyberSecEval 4](https://meta-llama.github.io/PurpleLlama/CyberSecEval/)
- [Purple Llama GitHub](https://github.com/meta-llama/PurpleLlama)
- [AutoPatchBench blog](https://engineering.fb.com/2025/04/29/ai-research/autopatchbench-benchmark-ai-powered-security-fixes/)
- [NYU CTF Bench](https://arxiv.org/abs/2406.05590)
- [ARC framework](https://arxiv.org/abs/2506.20102)

### Black-Box Optimization
- [BBOB/COCO](https://numbbo.github.io/coco/)
- [BBOB 2025 workshop](https://coco-platform.org/workshops/bbob2025.html)
- [CO-Bench AAAI 2026](https://arxiv.org/abs/2504.04310)
- [CO-Bench GitHub](https://github.com/sunnweiwei/CO-Bench)
- [EALG paper](https://arxiv.org/abs/2506.02594)
- [SATLUTION paper](https://arxiv.org/abs/2509.07367)
- [AlphaEvolve paper](https://storage.googleapis.com/deepmind-media/DeepMind.com/Blog/alphaevolve-a-gemini-powered-coding-agent-for-designing-advanced-algorithms/AlphaEvolve.pdf)
- [FunSearch Nature paper](https://storage.googleapis.com/deepmind-media/DeepMind.com/Blog/funsearch-making-new-discoveries-in-mathematical-sciences-using-large-language-models/Mathematical-discoveries-from-program-search-with-large-language-models.pdf)
- [OpenEvolve GitHub](https://github.com/jamesahou/openevolve)

### Adversarial Robustness
- [RobustBench](https://robustbench.github.io/)
- [RobustBench paper](https://arxiv.org/abs/2010.09670)
- [RobustBench CIFAR-10 Linf leaderboard](https://robustbench.github.io/cifar10/Linf.html)

### Code Optimization
- [PIE benchmark](https://pie4perf.com/)
- [PIE paper](https://openreview.net/forum?id=ix7rLVHXyY)
- [PIE GitHub](https://github.com/LearningOpt/pie)
- [FasterPy](https://arxiv.org/abs/2512.22827)
- [AdverTest paper](https://arxiv.org/abs/2602.08146)

### Adversarial Co-Evolution Frameworks
- [Digital Red Queen (Sakana AI)](https://arxiv.org/abs/2601.03335)
- [DRQ website](https://pub.sakana.ai/drq/)
- [Multi-Agent Evolve](https://arxiv.org/abs/2510.23595)
- [Co-Evolving Complexity (NeurIPS 2025)](https://arxiv.org/abs/2509.03771)

### Coding Benchmark Surveys
- [Runloop blog: Understanding LLM Code Benchmarks](https://runloop.ai/blog/understanding-llm-code-benchmarks-from-humaneval-to-swe-bench)
- [MorphLLM: AI Coding Benchmarks 2026](https://www.morphllm.com/ai-coding-benchmarks-2026)
- [Artificial Analysis LiveCodeBench](https://artificialanalysis.ai/evaluations/livecodebench)
