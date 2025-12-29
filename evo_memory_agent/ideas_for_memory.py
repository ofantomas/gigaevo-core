test_ideas = [
  {
    "task_name": "Circles packing",
    "task_description": "Write a Python function that arranges exactly **9 non-overlapping circles with variable radii** inside a unit square [0, 1] × [0, 1] to **maximize the total sum of their radii.",
    "useful_ideas": [
      {
        "idea": "Start from a known dense canonical structure (for 9 circles: a 3×3 lattice) before attempting novel/heuristic packings.",
        "strategy": "exploitation"
      },
      {
        "idea": "Use grid-spacing math to set a near-optimal radius bound: adjacent spacing ≈ 1/3 ⇒ baseline radius ≈ (1/3)/2 = 1/6, giving sum(r) ≈ 1.5.",
        "strategy": "exploitation"
      },
      {
        "idea": "Avoid exact tangency due to numeric overlap checks: introduce micro-slack by slightly increasing spacing (dx > 1/3) and/or shrinking radii by a tiny epsilon.",
        "strategy": "exploitation"
      },
      {
        "idea": "Prefer 'valid-by-construction' geometry over iterative repair; post-hoc repair/shrink steps can catastrophically reduce sum(r).",
        "strategy": "exploitation"
      },
      {
        "idea": "Inject variable radii safely by keeping geometry fixed (lattice) and applying small controlled variations (e.g., corners slightly larger, edges slightly smaller, center slightly larger) while preserving d >= r_i + r_j.",
        "strategy": "hybrid"
      },
      {
        "idea": "Handle wall constraints via lattice offsets: place boundary centers at offset a from walls and enforce r_i <= a for boundary circles, using x,y in {a, 0.5, 1-a}.",
        "strategy": "exploitation"
      },
      {
        "idea": "Keep the solution deterministic (no randomness) to maximize reliability and reproducibility under strict validity checkers.",
        "strategy": "exploitation"
      },
      {
        "idea": "For maximizing sum(r) with fixed n in a square, near-uniform large radii often outperform multi-scale 'one big + many small' motifs unless cavity-fill is provably efficient.",
        "strategy": "exploitation"
      },
      {
        "idea": "Reusable motif pattern: 'NineCircles_3x3_NearTangent_WithSlack' with centers from xs=[a,0.5,1-a], ys=[a,0.5,1-a], and radii chosen so r_i+r_j <= (0.5-a)-eps for adjacent pairs.",
        "strategy": "exploitation"
      }
    ]
  },
  {
    "task_name": "PDF Table Extraction and Cleanup",
    "task_description": "Extract tables from a PDF into a clean CSV/Excel format, preserving headers and fixing merged cells.",
    "useful_ideas": [
      {
        "idea": "Try native PDF text/table extraction first; fall back to page screenshots + OCR only if needed.",
        "strategy": "hybrid"
      },
      {
        "idea": "Detect header rows by font/position consistency; propagate headers to columns with missing labels.",
        "strategy": "exploitation"
      },
      {
        "idea": "Normalize whitespace, remove footnotes, and coerce numeric columns using locale-aware parsing.",
        "strategy": "exploitation"
      },
      {
        "idea": "If cells are merged, reconstruct by spanning rules: forward-fill labels and split multi-line entries.",
        "strategy": "exploitation"
      }
    ]
  },
  {
    "task_name": "Email Thread Summarization with Action Items",
    "task_description": "Summarize a long email thread and produce a clear list of decisions, open questions, and next actions.",
    "useful_ideas": [
      {
        "idea": "Segment by sender/time; identify quoted text blocks and de-duplicate repeated content.",
        "strategy": "exploitation"
      },
      {
        "idea": "Extract commitments using verb patterns ('I will', 'can you', 'please'); attach owners and deadlines.",
        "strategy": "exploitation"
      },
      {
        "idea": "Separate 'decisions made' from 'proposals' using modality cues ('agreed', 'decided' vs 'suggest').",
        "strategy": "exploitation"
      },
      {
        "idea": "Output: 5-bullet summary + action list + unanswered questions + risks.",
        "strategy": "exploitation"
      }
    ]
  },
  {
    "task_name": "SQL Query Optimization for Slow Reports",
    "task_description": "Speed up a slow SQL report query without changing results.",
    "useful_ideas": [
      {
        "idea": "Inspect query plan; find full table scans, missing indexes, and bad join order.",
        "strategy": "exploitation"
      },
      {
        "idea": "Push filters early; reduce row counts before joins; replace SELECT * with needed columns.",
        "strategy": "exploitation"
      },
      {
        "idea": "Use covering indexes for common WHERE+GROUP BY patterns.",
        "strategy": "exploitation"
      },
      {
        "idea": "Materialize expensive subqueries/CTEs when reused; avoid functions on indexed columns in WHERE.",
        "strategy": "exploitation"
      }
    ]
  },
  {
    "task_name": "Time Series Forecasting with Limited Data",
    "task_description": "Forecast the next 30 days of a metric given sparse historical daily data.",
    "useful_ideas": [
      {
        "idea": "Start with simple baselines: seasonal naive, moving average, exponential smoothing.",
        "strategy": "exploitation"
      },
      {
        "idea": "Decompose trend/seasonality; add holiday indicators if relevant.",
        "strategy": "hybrid"
      },
      {
        "idea": "Use rolling-origin cross-validation; avoid random splits.",
        "strategy": "exploitation"
      },
      {
        "idea": "Quantify uncertainty with prediction intervals (bootstrap or model-based).",
        "strategy": "exploitation"
      }
    ]
  },
  {
    "task_name": "Shortest Path with Obstacles on a Grid",
    "task_description": "Find the shortest path from start to goal on a grid with blocked cells; return the path coordinates.",
    "useful_ideas": [
      {
        "idea": "Use BFS for unweighted grids; A* with Manhattan heuristic for faster search.",
        "strategy": "exploitation"
      },
      {
        "idea": "Store parent pointers to reconstruct path; mark visited to prevent cycles.",
        "strategy": "exploitation"
      },
      {
        "idea": "Early exit when goal popped from queue/heap.",
        "strategy": "exploitation"
      },
      {
        "idea": "Handle bounds and obstacles carefully; test edge cases (no path, start==goal).",
        "strategy": "exploitation"
      }
    ]
  },
  {
    "task_name": "Knapsack-Style Budget Allocation",
    "task_description": "Select projects under a budget to maximize total value, with optional constraints like categories.",
    "useful_ideas": [
      {
        "idea": "Use DP for exact solution when budget is small; otherwise greedy + local search for large budgets.",
        "strategy": "hybrid"
      },
      {
        "idea": "If categories/limits exist, add state dimensions or use Lagrangian relaxation.",
        "strategy": "exploration"
      },
      {
        "idea": "Sort by value/cost ratio as a heuristic baseline; then refine with swaps.",
        "strategy": "hybrid"
      },
      {
        "idea": "Track reconstruction choices to output selected set, not just the score.",
        "strategy": "exploitation"
      }
    ]
  },
  {
    "task_name": "Data Deduplication via Fuzzy Matching",
    "task_description": "Identify duplicate records (names/addresses) in a dataset and merge them safely.",
    "useful_ideas": [
      {
        "idea": "Normalize text: lowercase, strip punctuation, standardize abbreviations (St → Street).",
        "strategy": "exploitation"
      },
      {
        "idea": "Block candidates using cheap keys (zip code, first letter) before expensive similarity checks.",
        "strategy": "exploitation"
      },
      {
        "idea": "Use token-based similarity (Jaccard/TF-IDF cosine) plus edit distance for short fields.",
        "strategy": "exploration"
      },
      {
        "idea": "Merge with confidence thresholds; keep audit trail of merges and conflicts.",
        "strategy": "exploitation"
      }
    ]
  },
  {
    "task_name": "Image Segmentation Post-Processing",
    "task_description": "Clean a binary mask from a segmentation model to remove noise and fill small holes.",
    "useful_ideas": [
      {
        "idea": "Use morphological opening to remove specks; closing to fill gaps.",
        "strategy": "exploitation"
      },
      {
        "idea": "Remove small connected components under an area threshold.",
        "strategy": "exploitation"
      },
      {
        "idea": "Fill holes via flood-fill from border then invert.",
        "strategy": "exploitation"
      },
      {
        "idea": "Optionally smooth boundaries with a small blur + re-threshold.",
        "strategy": "hybrid"
      }
    ]
  },
  {
    "task_name": "Robust CSV Ingestion Pipeline",
    "task_description": "Load messy CSV files with inconsistent columns, encodings, and delimiters into a normalized schema.",
    "useful_ideas": [
      {
        "idea": "Detect encoding (utf-8-sig, latin-1 fallback) and delimiter via sampling.",
        "strategy": "exploitation"
      },
      {
        "idea": "Use schema inference with explicit overrides for critical columns.",
        "strategy": "hybrid"
      },
      {
        "idea": "Normalize column names (snake_case) and map synonyms to canonical names.",
        "strategy": "exploitation"
      },
      {
        "idea": "Log row-level parse errors; quarantine bad rows rather than failing the whole load.",
        "strategy": "exploitation"
      }
    ]
  },
  {
    "task_name": "REST API Client with Retries and Backoff",
    "task_description": "Implement an API client that handles transient failures and rate limits safely.",
    "useful_ideas": [
      {
        "idea": "Retry idempotent requests on 429/5xx with exponential backoff + jitter.",
        "strategy": "exploitation"
      },
      {
        "idea": "Respect Retry-After headers; cap max backoff and max attempts.",
        "strategy": "exploitation"
      },
      {
        "idea": "Use timeouts on connect/read; instrument latency and error rates.",
        "strategy": "exploitation"
      },
      {
        "idea": "Separate transport from business logic; centralize auth and pagination handling.",
        "strategy": "exploitation"
      }
    ]
  },
  {
    "task_name": "Text Classification with Imbalanced Labels",
    "task_description": "Train a classifier where positive examples are rare; optimize for recall at acceptable precision.",
    "useful_ideas": [
      {
        "idea": "Use stratified splits; evaluate with PR-AUC and F1, not accuracy.",
        "strategy": "exploitation"
      },
      {
        "idea": "Apply class weights or focal loss; try threshold tuning on validation set.",
        "strategy": "hybrid"
      },
      {
        "idea": "Use calibrated probabilities (Platt/isotonic) if thresholds matter.",
        "strategy": "exploitation"
      },
      {
        "idea": "Augment minority class carefully (paraphrase/back-translation) while monitoring leakage.",
        "strategy": "exploration"
      }
    ]
  },
  {
    "task_name": "Schedule Optimization with Conflicting Meetings",
    "task_description": "Given constraints and preferences, generate a feasible weekly schedule minimizing conflicts and context switching.",
    "useful_ideas": [
      {
        "idea": "Model as constraint satisfaction: hard constraints first, then soft scoring.",
        "strategy": "exploitation"
      },
      {
        "idea": "Use greedy placement for hard constraints, then local search (swap/shift) to improve score.",
        "strategy": "hybrid"
      },
      {
        "idea": "Cluster similar tasks; add buffer blocks to reduce fragmentation.",
        "strategy": "hybrid"
      },
      {
        "idea": "Represent time slots discretely (e.g., 15-min) for simpler feasibility checks.",
        "strategy": "exploitation"
      }
    ]
  },
  {
    "task_name": "Anomaly Detection in Streaming Metrics",
    "task_description": "Detect anomalies in a live stream with seasonality and drift; trigger alerts with low false positives.",
    "useful_ideas": [
      {
        "idea": "Maintain rolling baselines (EWMA) and robust dispersion (MAD).",
        "strategy": "exploitation"
      },
      {
        "idea": "Use seasonal windows (same hour/day) for expected value estimates.",
        "strategy": "exploitation"
      },
      {
        "idea": "Require persistence (k of last n) before alerting; apply cooldown periods.",
        "strategy": "exploitation"
      },
      {
        "idea": "Log features at alert time for debugging (z-score, baseline, residual).",
        "strategy": "exploitation"
      }
    ]
  }
]
