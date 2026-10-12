#!/usr/bin/env python3
"""
Textbook Migration Script
Scaffolds wiki/strategic_simulation.md, cleans wiki/evaluations.md, and synchronizes wiki/index.md.
"""

import sys
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(WORKSPACE_ROOT / "scripts"))
from ast_splicer import ASTSplicer
from sqlite_manager.indexer import index_wiki

wiki_dir = WORKSPACE_ROOT / "wiki"
eval_path = wiki_dir / "evaluations.md"
strat_path = wiki_dir / "strategic_simulation.md"
index_path = wiki_dir / "index.md"
db_path = WORKSPACE_ROOT / "raw_firehose.db"

with open(eval_path, "r", encoding="utf-8") as f:
    eval_orig = f.readlines()

# 1. Prepare strategic_simulation.md content
strat_header = """---
title: Strategic Simulation & Entrepreneurial Failure Anticipation
tags: [strategic-simulation, pre-mortem, decision-frameworks, startup-failure, mental-models, venture-mechanics]
domain: strategic_simulation
---

# Strategic Simulation & Entrepreneurial Failure Anticipation

*Structured mental simulation frameworks, cognitive pre-mortems, non-ergodic survival boundaries, and empirical failure anticipation for strategic decision-making and venture execution.*

---

## 1. Architectural Philosophy

Designing complex initiatives and entrepreneurial ventures requires evaluating decisions through structured counterfactual simulation rather than forward predictive optimism. When founders, engineering leads, or autonomous planners embark on new trajectories, failures are rarely confined to software bugs alone—they stem from validation false positives, platform custody traps, governance deadlocks, circular feedback illusions, and non-ergodic capital ruin.

By applying prospective hindsight (the Gary Klein Pre-Mortem), non-ergodic absorbing barrier audits, and fast-and-frugal decision heuristics, operators can identify terminal failure modes before expending irreversible capital and code.

---

## 2. Core Operating Invariants

| Domain | Architectural Invariant | Operational Rule | Failure State if Violated |
| :--- | :--- | :--- | :--- |
| **Strategy** | Two-Tiered Simulation Partition | Eliminate Day-1 Terminal Risks upfront; defer Elastic Scale to $\\ge 100$ users | Premature scaling debt and building for non-existent scale |
| **Simulation** | Prospective Hindsight Pre-Mortem | Gary Klein protocol: assume 100% failure at Turn 100 and work backward | Forward predictive optimism and overlooked blindspots |
| **Velocity** | 70% Information Stopping Rule | Terminate mental simulation at 70% data for Type 2 reversible decisions | Consensus paralysis and stalled execution velocity |
| **Ergodicity** | Non-Ergodic Absorbing Barrier Invariant | Enforce 20% capital ceiling; eliminate path-dependent ruin states before upside | Unrecoverable capital depletion and terminal bankruptcy |
| **Heuristics** | Fast-and-Frugal 3-Cue Decision Tree | Lexicographic binary exits (Workaround -> Distribution -> 3x Stress); sub-10m filter | Overfitting simulation paralysis and analysis paralysis |
| **Rehearsal** | Singular Trajectory RPD Rehearsal | Step-by-step mental movie playback of the single leading option to spot execution snags | Shallow multi-option comparisons and unspotted execution snags |
| **Incentives** | Counter-Metric Pairing Invariant | Never track solitary volume targets; pair velocity with defect escape and retention | Goodhart-Cobra perverse gaming and distorted output |
| **Custody** | Hostile Landlord Invariant | Retain direct unmediated customer channels; vendor-agnostic adapter layers | Sudden platform rug-pull and destroyed enterprise value |
| **Governance** | Asymmetric Tie-Breaker Invariant | Prohibit 50/50 voting control; enforce 4-year vesting with 1-year cliff | Co-founder deadlocks and equity litigation paralysis |
| **Validation** | Concierge Inversion (20-Manual Threshold) | Prohibit automated pipelines until executing 20 manual workflows for paying users | Automated ghost towns and building solutions without active pain |

---

## 3. Failure Anticipation Protocols & Empirical Case Studies

Across strategic execution and venture creation, twenty-nine distinct systemic failure modes recur in high-uncertainty environments:

"""

strat_subsections = eval_orig[85:392]
renumbered = []
counter = 1
for line in strat_subsections:
    if line.startswith("### 4."):
        parts = line.split(" ", 2)
        rest = parts[2] if len(parts) > 2 else ""
        renumbered.append(f"### 3.{counter} {rest}")
        counter += 1
    else:
        renumbered.append(line)

strat_footer = """---

## 4. Cross-Chapter Connections

* **[[evaluations|7. Empirical Evaluations & Failure Modes]]:** Empirical benchmarks on LLM context windows, token burn, and low-level concurrency locks.
* **[[agent_architectures|5. Agent Cognitive Architectures & Toolchains]]:** Autonomous agent workflows, runtime interception, and epistemic state machines.
* **[[knowledge_compiler|6. Karpathy LLM-Wiki Knowledge Compiler]]:** CST surgical section replacement and living technical textbooks.
* **[[storage|1. Storage Engines & SQLite WAL]]:** Persistence guarantees, single-writer invariants, and reader snapshot pinning.
* **[[consensus|2. Distributed Consensus & Coordination]]:** Leader leases, coordination protocols, and governance tie-breakers.
"""

strat_content = strat_header + "".join(renumbered) + strat_footer
with open(strat_path, "w", encoding="utf-8") as f:
    f.write(strat_content)
print(f"[OK] Wrote strategic_simulation.md ({len(strat_content.encode('utf-8'))} bytes)")

# 2. Prepare new evaluations.md content
new_eval_lines = eval_orig[:59] + [
    "Across empirical stress testing and continuous agent cycles, five distinct systemic failure modes recur in multi-agent persistent architectures (for strategic decision-making and cognitive simulation failure modes, see [[strategic_simulation|Strategic Simulation & Entrepreneurial Failure Anticipation]]):\n\n"
] + eval_orig[60:85] + eval_orig[392:406] + [
    "* **[[strategic_simulation|Strategic Simulation & Entrepreneurial Failure Anticipation]]:** Gary Klein prospective hindsight pre-mortems, Cynefin domain partitions, non-ergodic absorbing barriers, and venture failure anticipation.\n"
] + eval_orig[406:]

new_eval_content = "".join(new_eval_lines)
with open(eval_path, "w", encoding="utf-8") as f:
    f.write(new_eval_content)
print(f"[OK] Wrote evaluations.md ({len(new_eval_content.encode('utf-8'))} bytes)")

# 3. Update index.md
with open(index_path, "r", encoding="utf-8") as f:
    idx_content = f.read()

old_chap7 = """### [[evaluations|7. Empirical Evaluations & Failure Modes]]
* **File:** `wiki/evaluations.md`
* **Focus:** Benchmarking agent architectures, token burn curves, context saturation, retrieval trade-offs, 34 production failure modes, and entrepreneurial mental simulation frameworks.
* **Core Mechanisms:** Token burn vs accuracy curves, the 60% context saturation cliff, surgical AST slicing benchmark (95% token savings vs full-file loading), dense vector vs SQLite FTS5 latency comparison, empirical root-cause analysis of 34 production failure modes, Gary Klein's prospective hindsight pre-mortem, the Two-Tiered Simulation Partition (Day-1 Terminal Invariants vs Elastic Scale), Causal Loop Delays (Meadows Protocol), Strategic Chaos Injection (Simian Strategy), Motor Priming action deconstruction, Adversarial Role Inversion, the 70% Information Stopping Rule, the Peters-Taleb Non-Ergodic Absorbing Barrier audit (20% capital ceiling), the Gigerenzer Fast-and-Frugal Tree (sub-10-minute strategic calibration), Singular Trajectory Rehearsal (Klein RPD mental movie), Counter-Metric Pairing (Goodhart-Cobra incentive simulation), the Hostile Landlord Invariant (Platform Custody Risk insulation), the Asymmetric Tie-Breaker Invariant (50/50 Governance Deadlock prevention), and the Concierge Inversion (20-Manual-Transactions Threshold)."""

new_chap7_and_8 = """### [[evaluations|7. Empirical Evaluations & Failure Modes]]
* **File:** `wiki/evaluations.md`
* **Focus:** Benchmarking agent architectures, token burn curves, context saturation, retrieval trade-offs, and multi-agent production failure modes.
* **Core Mechanisms:** Token burn vs accuracy curves, the 60% context saturation cliff, surgical AST slicing benchmark (95% token savings vs full-file loading), dense vector vs SQLite FTS5 latency comparison, and empirical root-cause analysis of 5 production failure modes (lock escalation deadlocks, unbounded WAL bloat, semantic merge collisions, InjecMEM prompt injections, and whole-file rewrite corruption).

### [[strategic_simulation|8. Strategic Simulation & Entrepreneurial Failure Anticipation]]
* **File:** `wiki/strategic_simulation.md`
* **Focus:** Structured mental simulation frameworks, cognitive pre-mortems, non-ergodic survival boundaries, counterfactual reasoning, and venture failure anticipation.
* **Core Mechanisms:** Gary Klein's prospective hindsight pre-mortem, Two-Tiered Simulation Partition (Day-1 Terminal Invariants vs Elastic Scale), Causal Loop Delays (Meadows Protocol), Strategic Chaos Injection (Simian Strategy), Motor Priming action deconstruction, Adversarial Role Inversion, the 70% Information Stopping Rule, the Peters-Taleb Non-Ergodic Absorbing Barrier audit (20% capital ceiling), the Gigerenzer Fast-and-Frugal Tree (sub-10-minute strategic calibration), Singular Trajectory Rehearsal (Klein RPD mental movie), Counter-Metric Pairing (Goodhart-Cobra incentive simulation), the Hostile Landlord Invariant (Platform Custody Risk insulation), the Asymmetric Tie-Breaker Invariant (50/50 Governance Deadlock prevention), and the Concierge Inversion (20-Manual-Transactions Threshold)."""

assert old_chap7 in idx_content, "old_chap7 pattern not found in index.md!"
idx_updated = idx_content.replace(old_chap7, new_chap7_and_8)
with open(index_path, "w", encoding="utf-8") as f:
    f.write(idx_updated)
print(f"[OK] Wrote index.md ({len(idx_updated.encode('utf-8'))} bytes)")

# 4. Lint all 3 files
for p in [eval_path, strat_path, index_path]:
    errs = ASTSplicer.lint_file(p)
    print(f"[LINT] {p.name}: {len(errs)} warnings -> {errs}")

# 5. Re-index database
print("[INDEXING] Synchronizing SQLite indexer with newly scaffolded chapters...")
index_wiki(db_path, wiki_dir, embed=True)
print("[SUCCESS] All migrations and indexes synchronized successfully!")
