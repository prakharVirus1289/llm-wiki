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

Across empirical stress testing and continuous agent cycles, fourteen distinct systemic failure modes recur in complex engineering and strategic environments:

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

### 4.6 Strategic Mental Simulation & Pre-Mortem Failure Anticipation
* **Symptom:** Founders and engineering leads burn weeks of engineering capital building complete systems, only to encounter catastrophic adoption failure, second-order operational bottlenecks, or untracked trust depletion upon release.
* **Root Cause:** Relying on forward predictive optimism and speculative user feature requests without performing structured counterfactual simulation or empirical pre-building validation.
* **Cognitive Simulation Frameworks & Systemic Mitigations:**
  1. **The Prospective Hindsight Pre-Mortem (Gary Klein Protocol):** Assume as a deterministic fact that the initiative has completely collapsed 12 months in the future. Working backward from certainty eliminates social conformity and optimism bias, surfacing systemic risks that standard forward planning conceals.
  2. **Second-Order Ripple Modeling (Causal Loop Mapping):** Differentiate first-order direct effects ($A \rightarrow B$) from downstream feedback loops ($B \rightarrow C \rightarrow \neg A$). Trace delays, feedback loops, and unintended behavioral shifts before committing code.
  3. **The Trust Bandwidth Bottleneck (Theory of Constraints Inversion):** System execution speed is rarely constrained by raw code velocity; it is constrained by the organizational and customer trust envelope. Over-engineering architecture without established user trust creates fatal coordination drag.
  4. **The Pre-Building Behavioral Verification Protocol:** Validate customer willingness-to-pay using behavioral commitments (pre-orders, time expenditure, process displacement) rather than hypothetical verbal agreement. If users are not already spending time or money hacking around the problem with inferior tools, building an automated software solution will not create demand. See [[evaluations/the-fallacy-of-the-infinite-context-window|Empirical Evaluations]].

### 4.7 The Five Pre-Building Death Buckets (Validation False Positives)
* **Symptom:** An engineering founder builds an architecturally sound solution with clean code and working pipelines, but experiences complete commercial stalls ($0 MRR, $< 5\%$ retention, or immediate regulatory blockade).
* **Root Cause:** Failing to screen early hypotheses through the five structural "Death Buckets" before writing code:
  1. **The Compliance Nightmare:** Underestimating legal and regulatory barriers (e.g. financial licensing, HIPAA, government compliance) that require enterprise legal capital to clear.
  2. **The "Logical Idea" Vitamin Trap:** The product makes logical sense on paper, but the actual user pain is mild, leading to low organic search volume and customer acquisition costs ($CAC > LTV$) that exceed willingness to pay.
  3. **The Incumbent Saturated Bloodbath:** Entering an established market where differentiated technical architecture cannot overcome the marketing, distribution, and SEO moat of existing players.
  4. **The 1-Jira-Ticket Platform Risk:** Building a workflow or wrapper that is a trivial roadmap item for the underlying platform (e.g., OpenAI, Google, AWS), destroying the business upon the platform's next release.
  5. **The Uneducated Category Drag:** Attempting to sell solutions to problems prospective users do not yet know they have, burning runway trying to educate the market rather than capturing active demand.
* **Fix:** Subject every proposed project to the 5-Bucket Elimination Audit and verify pre-existing search intent and CAC/LTV unit economic thresholds before initializing software repositories. See [[evaluations/the-fallacy-of-the-infinite-context-window|Empirical Evaluations]].

### 4.8 The Synthetic Simulation Sycophancy Cliff (FutureSim Invariants)
* **Symptom:** Founders and product strategists use LLM persona swarms ("synthetic users") or ungrounded mental simulations to evaluate product ideas, receiving overwhelmingly enthusiastic approval, only to launch and experience near-zero real-world organic adoption.
* **Root Cause:** Language model agents exhibit natural sycophancy bias and zero-inertia adoption. Without explicit simulated switching costs, real monetary constraints, and negative domain priors, simulated agents accept proposed solutions unconditionally. Furthermore, empirical evaluations (FutureSim 2026 benchmark) demonstrate that unconstrained models top out at $\approx 25\%$ accuracy on long-horizon temporal execution tasks.
* **Fix:** Enforce the *Adversarial In-Silico Calibration Protocol*:
  1. **Strict Switching Costs:** Every simulated persona must be initialized with existing incumbent workflows and a quantifiable penalty (time, retraining, integration friction) for switching.
  2. **Bounded Discretionary Budgets:** Synthetic buyers must possess hard budget limits and competing alternative allocations.
  3. **Adversarial Red-Team Cohorts:** Minimum $50\%$ of the simulated evaluation cohort must be explicitly seeded with resistant, cynical, or legacy-entrenched priors to stress-test real-world inertia. See [[agent_architectures|Agent Cognitive Architectures]] and [[evaluations/the-fallacy-of-the-infinite-context-window|Empirical Evaluations]].

### 4.9 The Circular Validation Mirage (The Self-Referential Green Suite Trap)
* **Symptom:** Founders, system architects, and autonomous coding agents produce complete requirement specifications, mock user interviews, and extensive test suites that all report 100% success, yet the project collapses immediately upon exposure to unconstrained external users.
* **Root Cause:** Circular validation loops. When the same author or model that forms a hypothesis also designs the verification harness, it inherently builds mock-heavy tests that mirror its own internal assumptions. In software engineering, this manifests as test suites that pass by asserting mock states rather than exercising real I/O and database constraints; in strategy, it manifests as customer interview questions that lead participants to validate the founder's thesis.
* **Fix:** Strict Decoupling of Verification Arbiters.
  1. **Zero-Mock Boundary Invariants:** Mandate validation against real external environments, unmocked database transaction boundaries, and unscripted user environments.
  2. **Independent Skeptical Arbiters:** Require that validation criteria be reviewed or executed by external adversarial observers tasked specifically with disproving viability.
  3. **Rapid Empirical Reality Probes:** Replace protracted theoretical modeling with immediate, observable commitments (e.g. asking for payment or workflow displacement within 48 hours). See [[agent_architectures/three-valued-epistemic-state-machine|Epistemic Memory]] and [[evaluations|Empirical Evaluations]].

### 4.10 The Expertise Trap & Extreme Parameter Sensitivity Stress-Testing (Cynefin Protocol)
* **Symptom:** Founders with deep technical expertise build exhaustive multi-year analytical models and execution simulations, yet experience complete commercial failure because customer and market adoption operates contrary to the model.
* **Root Cause:** The Expertise Trap (Dave Snowden's Cynefin Framework). Treating a *Complex* domain (markets, human adoption, emergent system dynamics) as if it were a *Complicated* domain (compiler design, database optimization). In a Complicated system, cause and effect are knowable through expert analysis (*Sense-Analyze-Respond*). In a Complex system, cause and effect are only knowable in hindsight through emergent behavior (*Probe-Sense-Respond*). Attempting to mentally simulate a complex emergent market from start to finish without micro-probing creates fatal overconfidence.
* **Systemic Fix & Stress-Testing Primitives:**
  1. **The Cynefin Domain Partition:** Categorize project layers into closed technical components (Complicated: analyze and verify) versus human adoption components (Complex: probe, sense, and respond).
  2. **The $10\times$ Extreme Parameter Sensitivity Test:** Stress-test every business and operational spreadsheet by applying $10\times$ multiplier penalties to key assumptions (e.g. what if CAC is $10\times$ higher? What if onboarding takes $5\times$ longer? What if customer churn reaches $50\%$?). If model outputs fail to react realistically, the simulation formula is fundamentally disconnected from operational reality.
  3. **Short-Cycle Probing:** Replace multi-month predictive simulation with low-cost bounded probes that extract unambiguous empirical data from the market. See [[agent_architectures|Agent Cognitive Architectures]] and [[evaluations|Empirical Evaluations]].

### 4.11 Consensus Paralysis & The Falsification Decision Log (DRI Protocol)
* **Symptom:** Founders and early engineering teams spend weeks locked in open-ended architecture or roadmap debates, or make strategic bets with no structured way to evaluate whether their mental simulation models were accurate.
* **Root Cause:** Consensus seeking and uncalibrated post-facto rationalization. Requiring full team consensus creates analysis paralysis because different team members optimize for contradictory vectors (velocity vs stability vs architecture elegance). Furthermore, lack of immutable decision records allows hindsight bias to rewrite memory after failure, preventing operators from improving predictive judgment.
* **Systemic Fix & Strategic Velocity Primitives:**
  1. **Directly Responsible Individual (DRI) Ownership:** Enforce open debate followed strictly by single-owner executive resolution. The DRI owns the decision and executes against pre-established simplicity invariants (e.g. standard library before custom code; battle-tested platforms before unproven tech).
  2. **The Falsification Decision Journal:** Record every strategic choice in a structured decision log prior to execution:
     * *Ground Truth Assertions:* Explicit assumptions and numbers held at the time of the decision.
     * *The Rejected Counterfactual:* What alternative paths were deliberately abandoned.
     * *The Falsification Trigger:* A precise, quantifiable signal (e.g. zero paid signups in 7 days, or customer onboarding time exceeding 2 hours) that proves the thesis false and triggers an immediate pivot.
     * *Calendar Review Checkpoint:* Scheduled retrospective to grade prediction accuracy against reality, eliminating hindsight bias. See [[agent_architectures/three-valued-epistemic-state-machine|Epistemic Memory]] and [[evaluations|Empirical Evaluations]].

### 4.12 The Rubber-Stamp Simulation Fallacy & Meaningful Oversight Gates
* **Symptom:** Strategic planning sessions and AI-assisted simulation runs produce articulate roadmaps and proposal summaries that evaluators rubber-stamp without exercising genuine discernment, resulting in predictable execution blindspots detonating post-launch.
* **Root Cause:** Passive rubber-stamping and absence of discarded counterfactual evaluation. Evaluators review project proposals looking for superficial coherence and positive sentiment rather than testing uncertainty limits and discarded alternatives. Without an active obligation and explicit tools to challenge assumptions, human oversight is purely cosmetic.
* **Systemic Fix & Verification Primitives:**
  1. **Mandatory Dual-Path Articulation:** Evaluators must require the presentation of at least two mutually exclusive execution models, explicitly contrasting why the rejected path was dropped.
  2. **The Adversarial Pressure Gate:** Apply explicit stress tests (e.g., immediate 50% loss of runway or a sudden platform policy shift). If an analytical model collapses or changes recommendation under mild pushback, the strategic thesis lacks foundational grounding.
  3. **Inspection of Uncertainty Envelopes:** Require explicit bounds on what remains unknown, verifying that risk mitigation buffers exist for variance rather than planning purely for the median case. See [[agent_architectures/three-valued-epistemic-state-machine|Epistemic Memory]] and [[evaluations|Empirical Evaluations]].

### 4.13 The Code Velocity Mirage & The Three-Persona Adversarial Triangle
* **Symptom:** Founders leverage modern AI coding tools and rapid frameworks to build functional software products in 24 hours, yet experience zero customer adoption and complete commercial silence upon release.
* **Root Cause:** Confusing *construction velocity* with *strategic validation*. Accelerating the speed of software construction does not accelerate market demand or distribution. Building faster merely produces unvalidated software inventory faster. Furthermore, founders fall prey to the "Prompt-as-a-Moat" illusion, where their entire value proposition is defenseless against underlying platform updates.
* **Systemic Fix & Strategic Verification Primitives:**
  1. **The Three-Persona Adversarial Simulation Triangle:** Before writing any code, mentally or systematically interrogate the proposal through three distinct conflicting personas:
     * *The Cynical Investor:* Attacks customer acquisition economics ($CAC$), total addressable market, and defensibility against foundation model releases.
     * *The Domain SME:* Attacks operational edge cases, data compliance barriers, and regulatory edge cases.
     * *The Stubborn End-User:* Attacks habit inertia, workflow switching costs, and the friction of adopting another standalone tool.
  2. **The Distribution-First Proof Invariant:** Require evidence of pre-existing distribution or active community pull (e.g. users begging for a solution in existing public forums) before authorizing software repository creation. See [[agent_architectures|Agent Cognitive Architectures]] and [[evaluations|Empirical Evaluations]].

### 4.14 The Feature Accumulation Liability & Subtractive Via Negativa (Strategic Chaos Injection)
* **Symptom:** Project roadmaps continuously expand in scope, product messaging becomes convoluted, development timelines triple, and prototypes collapse under the weight of edge-case regressions before validating core value.
* **Root Cause:** Additive planning bias. Operators instinctively attempt to resolve uncertainty by accumulating features and speculative capabilities (*"What if a customer also needs X?"*), ignoring the non-linear second-order costs of complexity (support overhead, UI cognitive friction, maintenance surface area).
* **Systemic Fix & Subtractive Primitives:**
  1. **The Subtractive Invariant (Taleb's Via Negativa):** Define the project by what it strictly refuses to do. Write down the user's primary outcome on a single regular weekday in one sentence. If any feature can be deleted without breaking that core utility, it must be removed rather than built or optimized.
  2. **The "What Actually Breaks?" Test:** Invert the prioritization prompt. Replace *"What is the risk of not building this?"* with *"What concrete workflow halts if this is omitted?"* If the consequence is non-fatal, purge it immediately.
  3. **Strategic Chaos Injection:** Stress-test the design by deliberately simulating the sudden failure of primary dependencies (e.g. key API provider shutdown, 3x latency increase, or channel block). If failure destroys the entire business without recovery options, architect structural isolation before writing feature code. See [[agent_architectures/three-valued-epistemic-state-machine|Epistemic Memory]] and [[evaluations|Empirical Evaluations]].

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
