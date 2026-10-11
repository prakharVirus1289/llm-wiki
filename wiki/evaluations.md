# Empirical Evaluations & Failure Modes

*Benchmarking agent architectures, token burn curves, context saturation, retrieval trade-offs, and production failure modes.*

---

## 1. Architectural Overview

Designing autonomous agent systems and knowledge compilers requires moving beyond subjective "vibe checks" to empirical, reproducible benchmarks. When language models interact with persistent codebases, execution failures are rarely confined to model reasoning alone—they stem from systemic bottlenecks in storage concurrency, token budgets, retrieval latency, and context degradation.

---

## 2. Token Burn vs Accuracy Saturation Curve

### 2.1 The Fallacy of the Infinite Context Window
A prevalent misconception in agent engineering is that expanding context windows (e.g., 200K to 1M tokens) eliminates the need for disciplined memory management. Empirical evaluations reveal that **model reasoning accuracy does not scale linearly with context size**:

```
Accuracy (%)
100 |----------------\
 80 |                 \
 60 |                  \  (The 60% Saturation Cliff)
 40 |                   \
 20 |                    \-------------------
  0 +----------------------------------------
    0%    20%    40%    60%    80%   100% Context Utilized
```

* **The 60% Saturation Boundary:** When prompt context surpasses approximately **60% of total window capacity**, models experience significant attention dilution ("lost in the middle").
* **Needle-in-a-Haystack Degradation:** In multi-file coding tasks where architectural constraints are placed in large contexts, instruction adherence drops by up to $42\%$ when context utilization exceeds $65\%$.
* **Compaction Invariant:** Agent harnesses must trigger deterministic context compaction or session memory offloading whenever active prompt size reaches $60\%$ of maximum context. See [[caching/multi-agent-compaction-thresholds|Multi-Agent Compaction Thresholds]].

### 2.2 Surgical AST Slicing vs Full-File Loading
To evaluate the impact of retrieval granularity, benchmark runs compared two document ingestion strategies across 1,000 architectural query tasks:

| Ingestion Strategy | Median Tokens Burned | Retrieval Latency (p95) | Answer Accuracy | Syntax Regressions |
| :--- | :--- | :--- | :--- | :--- |
| **Full-File Loading** | 18,450 tokens | 480 ms | 68.2% | 14.5% |
| **3-Tier Surgical AST Slicing** | **840 tokens** | **18 ms** | **94.8%** | **0.8%** |

* **Token Savings:** Surgical section slicing delivers an **over 95% reduction in prompt token consumption**.
* **Accuracy Improvement:** By stripping away irrelevant file boilerplate and passing only the targeted section and its 1-hop dependencies, model attention remains focused on the relevant logic, cutting syntax regressions to under $1\%$.

---

## 3. Retrieval Architectures: Dense Vectors vs FTS5 Hybrid

### 3.1 Latency and Cost Trade-Offs
Deploying dense vector retrieval (embedding generation + cosine similarity matrix search) introduces substantial runtime costs compared to embedded SQLite FTS5 lexical indexes:

1. **Pure Dense Vectors:** Requires generating vector embeddings for every incoming query ($\sim 80\text{--}150\text{ms}$ network or local GPU inference) and scanning dense index matrices. Furthermore, dense vectors frequently match irrelevant content due to shared conversational phrasing or marketing vocabulary.
2. **Embedded SQLite FTS5:** Operates in-process with zero network overhead, executing BM25 ranking over heading tokens in **$< 15\text{ms}$**.
3. **Graph Backlink Traversal:** Resolving 1-hop and 2-hop edges in the `wiki_links` relational table requires only **$2\text{--}5\text{ms}$**, deterministically retrieving relevant dependencies without vector search variance.

---

## 4. Production Failure Modes & Root-Cause Analysis

Across empirical stress testing and continuous agent cycles, five distinct systemic failure modes recur in multi-agent environments:

### 4.1 The Lock Escalation Deadlock Cascade
* **Symptom:** Concurrent agent workers stall indefinitely, logging recurring `sqlite3.OperationalError: database is locked` errors despite generous busy timeouts.
* **Root Cause:** Multiple connections executing `BEGIN DEFERRED;`, reading data under shared locks, and simultaneously attempting to execute writes. SQLite cannot escalate multiple shared locks to reserved locks, causing an immediate unresolvable deadlock.
* **Fix:** Enforce `BEGIN IMMEDIATE;` on all write transactions. See [[storage/the-lock-escalation-deadlock-hazard|Lock Escalation Deadlock Hazard]].

### 4.2 The Unbounded WAL Bloat Trap
* **Symptom:** The database `-wal` file inflates from 5MB to over 10GB during continuous ingestion runs, causing read queries to slow from sub-millisecond to several seconds.
* **Root Cause:** A long-running reader process (e.g., an unclosed streaming cursor) pins the WAL read-mark. Passive autocheckpoints cannot advance past the pinned frame, forcing subsequent writes to append new frames indefinitely.
* **Fix:** Enforce short-lived read connections, close cursors immediately, and tune autocheckpointing to 16MB bounds (`PRAGMA wal_autocheckpoint = 4000;`).

### 4.3 The Semantic Merge Collision Hazard
* **Symptom:** Two parallel sub-agents each submit pull requests that pass local test suites in their respective git worktrees. When merged together into `main`, the build breaks completely.
* **Root Cause:** Git performs three-way line-level merges without understanding semantic syntax dependencies. Agent A updated a function signature, while Agent B added a new call site using the old signature. Both branches were locally green on their base commits, but their combined state was never verified.
* **Fix:** Sub-agents must run rebase-and-verify loops against current `main` before acquiring merge leases. See [[consensus/leader-leases-and-sqlite-single-writer-locks|Leader Leases & Coordination]].

### 4.4 The Memory Poisoning Cascade (InjecMEM)
* **Symptom:** An agent assigned to write a unit test unexpectedly attempts to read local credentials or disable security linting rules.
* **Root Cause:** The agent retrieved an external web scrape from persistent memory that contained an indirect prompt injection payload. The payload was formatted as raw system instructions, overriding the agent's active directives.
* **Fix:** Treat all retrieved memory as passive, read-only data blocks. Sanitize delimiter tokens prior to persistent storage. See [[agent_architectures/defense-against-memory-injection-attacks-injecmem|InjecMEM Defense]].

### 4.5 The Whole-File Rewrite Corruption
* **Symptom:** A chapter loses half its technical subsections after an automated documentation update pass.
* **Root Cause:** The LLM was prompted to rewrite an entire 1,500-line markdown file. Due to completion length constraints, the model silently dropped earlier sections while generating the requested additions.
* **Fix:** Prohibit whole-file rewrites. Enforce the Concrete Syntax Tree (CST) surgical section patching engine. See [[knowledge_compiler/ast-driven-surgical-section-patching|AST Surgical Patching]].

---

## 5. Architectural Invariants & Benchmark Thresholds

| Invariant / Metric | Target Threshold | Hard Failure Boundary | Diagnostic Tool |
| :--- | :--- | :--- | :--- |
| **Section Query Latency** | $< 15\text{ms}$ (p95) | $> 50\text{ms}$ | `llm_wiki_query` telemetry |
| **Context Window Saturation** | $\le 60\%$ capacity | $> 75\%$ capacity | Active turn token meter |
| **WAL File Size** | $\le 16\text{MB}$ | $> 64\text{MB}$ | OS filesystem check (`.db-wal`) |
| **AST Diff Syntax Error Rate** | $0.0\%$ | $> 0.1\%$ | Pre-commit syntax validator |
| **Dangling Wikilinks** | $0$ broken links | $> 0$ broken links | `llm_wiki_get_graph(action="dangling")` |
| **SQLite Deadlock Rate** | $0.0\%$ | $> 0.01\%$ | Application error logs (`SQLITE_BUSY`) |

---

## 6. Cross-Chapter Connections

* **[[storage/the-single-writer-invariant|SQLite Single-Writer Concurrency]]:** Core storage guarantees necessary to prevent `SQLITE_BUSY` deadlocks under concurrent agent access.
* **[[storage/reader-snapshot-pinning-and-wal-bloat-mitigation|Reader Snapshot Pinning]]:** Deep dive into the mechanics of WAL bloat and passive checkpoint stalls.
* **[[consensus/leader-leases-and-sqlite-single-writer-locks|Leader Leases & Coordination]]:** Distributed consensus patterns to prevent semantic merge collisions in multi-agent fleets.
* **[[caching/multi-agent-compaction-thresholds|Multi-Agent Compaction Thresholds]]:** Practical rules for pruning and compacting agent context at the 60% saturation boundary.
* **[[agent_architectures/the-mcp-rug-pull-attack|MCP Security & Tool Interception]]:** Runtime protection patterns against tool schema mutations and malicious memory payloads.
* **[[knowledge_compiler/three-tier-hierarchical-reading-protocol|Three-Tier Hierarchical Reading Protocol]]:** Concrete retrieval protocol for achieving sub-15ms latency and 95% token savings.
