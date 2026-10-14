# LLM-Wiki Knowledge Master Catalog

*Deterministic navigation index and architectural sitemap for the living technical textbook.*

---

## 1. Architectural Philosophy

The LLM-Wiki living technical textbook organizes software engineering principles, empirical benchmarks, and systems knowledge into a governed, compounding knowledge substrate. Built upon Andrej Karpathy's three-layer wiki paradigm, it decouples immutable primary sources from human-readable textbook synthesis and high-speed relational shadow indices.

---

## 2. Domain Chapters

### [[storage|1. Storage Engines & SQLite WAL]]
* **File:** `wiki/storage.md`
* **Focus:** Deep dive into local persistence, ACID durability, SQLite WAL mode, B-Trees, and lock-free concurrency.
* **Core Mechanisms:** Multi-reader single-writer concurrency, `BEGIN IMMEDIATE` lock escalation deadlock mitigation, reader snapshot pinning, WAL file bloat prevention, Ed25519 memory attestation, and Windows MMAP boundaries.

### [[consensus|2. Distributed Consensus & Coordination]]
* **File:** `wiki/consensus.md`
* **Focus:** Analysis of Raft, Paxos, quorum mechanisms, distributed state machines, and split-brain mitigation.
* **Core Mechanisms:** Randomized election timeouts, term numbers, log replication consistency check, state machine safety invariant, leader leases integrated with SQLite single-writer locks, and Git Merkle DAG state reversibility.

### [[networking|3. Ingestion Pipelines & Network Backpressure]]
* **File:** `wiki/networking.md`
* **Focus:** High-throughput firehose ingestion, backpressure regulation, WebSocket multiplexing, and network partitioning.
* **Core Mechanisms:** The 16MB WAL autocheckpoint boundary (`PRAGMA wal_autocheckpoint = 4000;`), Windows MMAP handle limits, bounded queue backpressure (400-item high water mark), and canonical SHA-256 URL deduplication.

### [[caching|4. Memory Budgets & Context Caching]]
* **File:** `wiki/caching.md`
* **Focus:** Memory budgeting, prompt/KV-cache reuse, LRU eviction patterns, and context exhaustion mitigation.
* **Core Mechanisms:** Context window economy, the Deterministic Prefix Invariant for zero-copy hardware KV-cache reuse, ARC/LRU eviction policies, and the Multi-Agent Compaction Threshold (60% saturation rule).

### [[agent_architectures|5. Agent Cognitive Architectures & Toolchains]]
* **File:** `wiki/agent_architectures.md`
* **Focus:** Autonomous coding agent workflows, Model Context Protocol (MCP), memory governance, runtime interception, and failure recovery.
* **Core Mechanisms:** Flat Markdown vaults vs opaque vector databases, MCP rug-pull defense via cryptographic tool hashing, high-throughput tool call interception (<0.4ms proxy gate), Three-Valued Epistemic State Machine (`Settled`, `Indeterminate`, `Refuted`), InjecMEM prompt injection defense, and isolated Git worktree sandboxing.

### [[knowledge_compiler|6. Karpathy LLM-Wiki & Knowledge Compilers]]
* **File:** `wiki/knowledge_compiler.md`
* **Focus:** Living technical textbooks, governed schemas, relational shadow tables, AST surgical patching, and two-hop graph traversal.
* **Core Mechanisms:** Karpathy three-layer architecture (`raw/` -> `wiki/` -> `site/`), 3-Tier Hierarchical Reading Protocol (FTS5 Lexical -> Surgical AST Slicing -> Backlink Graph), Concrete Syntax Tree (CST) surgical section replacement, and the 4-Point Epistemic Link Audit.

### [[evaluations|7. Empirical Evaluations & Failure Modes]]
* **File:** `wiki/evaluations.md`
* **Focus:** Benchmarking agent architectures, token burn curves, context saturation, retrieval trade-offs, and multi-agent production failure modes.
* **Core Mechanisms:** Token burn vs accuracy curves, the 60% context saturation cliff, surgical AST slicing benchmark (95% token savings vs full-file loading), dense vector vs SQLite FTS5 latency comparison, and empirical root-cause analysis of 5 production failure modes (lock escalation deadlocks, unbounded WAL bloat, semantic merge collisions, InjecMEM prompt injections, and whole-file rewrite corruption).

### [[strategic_simulation|8. Strategic Simulation & Entrepreneurial Failure Anticipation]]
* **File:** `wiki/strategic_simulation.md`
* **Focus:** Structured mental simulation frameworks, cognitive pre-mortems, non-ergodic survival boundaries, counterfactual reasoning, and venture failure anticipation.
* **Core Mechanisms:** Gary Klein's prospective hindsight pre-mortem, Two-Tiered Simulation Partition (Day-1 Terminal Invariants vs Elastic Scale), Causal Loop Delays (Meadows Protocol), Strategic Chaos Injection (Simian Strategy), Motor Priming action deconstruction, Adversarial Role Inversion, the 70% Information Stopping Rule, the Peters-Taleb Non-Ergodic Absorbing Barrier audit (20% capital ceiling), the Gigerenzer Fast-and-Frugal Tree (sub-10-minute strategic calibration), Singular Trajectory Rehearsal (Klein RPD mental movie), Counter-Metric Pairing (Goodhart-Cobra incentive simulation), the Hostile Landlord Invariant (Platform Custody Risk insulation), the Asymmetric Tie-Breaker Invariant (50/50 Governance Deadlock prevention), and the Concierge Inversion (20-Manual-Transactions Threshold).

### [[political_governance_india|9. Indian Political Governance, Coalition Dynamics & Civic Movements]]
* **File:** `wiki/political_governance_india.md`
* **Focus:** Comparative governance records of the Indian National Congress (INC) and Bharatiya Janata Party (BJP), regional coalition leverage, civil unrest responses, and civic pressure outfits.
### [[workstation_hardware_evaluations|10. Workstation Hardware & Ergonomic Setup Evaluations]]
* **File:** `wiki/workstation_hardware_evaluations.md`
* **Focus:** Empirical ergonomics, height-adjustable desk mechanics, L-shaped multi-laptop surface layouts, chair biomechanics, and sub-20k INR procurement combinations.
* **Core Mechanisms:** The Ergonomic Clearance Model (90° elbow angle, 28"–45" sit-stand range), Carbon Steel frame rigidity, BIFMA Class 3/4 pneumatic gas lift safety, winged bucket foam vs breathable mesh heat dissipation, and strategic budget partitioning for sub-20,000 INR computer setups.

### [[combat_sports_gear_evaluations|11. Combat Sports Gear & Boxing Glove Evaluations]]
* **File:** `wiki/combat_sports_gear_evaluations.md`
* **Focus:** Impact dynamics, heavy bag knuckle shock absorption, wrist stabilization mechanics, lace-up vs. velcro engineering, and 14oz/16oz glove sizing for 70kg fighters.
* **Core Mechanisms:** 360° cylindrical lace wrist casting, Injected Molded Foam (IMF) cell density, cowhide vs synthetic durability, and locked-thumb alignment.

## 3. Master Invariants Matrix

| Domain | Architectural Invariant | Enforcement Mechanism |
| :--- | :--- | :--- |
| **Combat Sports** | Wrist Alignment & Knuckle Deceleration Invariant | Heavy bag impact forces require 360° cylindrical lace-up wrist stabilization and minimum 2" multi-layer/IMF knuckle foam to prevent carpal hyperextension |
| **Hardware** | Ergonomic Height & Postural Alignment Invariant | Desks and chairs must provide independent vertical travel to maintain 90° elbow and neutral spine alignment |
| **Storage** | Multi-Reader Single-Writer Isolation | Strict serialization of write transactions; `BEGIN IMMEDIATE` |
| **Consensus** | Election Safety & Leader Lease | Quorum grants with synchronized monotonically bounded lease timers |
| **Networking** | Bounded WAL Checkpoint Boundary | Autocheckpointing pinned at 16MB (4,000 pages) to prevent I/O stalls |
| **Caching** | Deterministic Prefix Invariant | Static system directives and tool schemas placed strictly at index 0 |
| **Agents** | Three-Valued Epistemic Memory | Discrete tracking of `Settled`, `Indeterminate`, and `Refuted` assertions |
| **Compiler** | Surgical Section AST Patching | CST byte offset replacement (`start_line` to `end_line`) |
| **Evaluations** | Context Window Compaction Boundary | Bounded session compaction triggered at 60% context saturation |
| **Strategy** | Two-Tiered Simulation Partition | Eliminate Day-1 Terminal Risks upfront; defer Elastic Scale to $\ge 100$ users |
| **Simulation** | Prospective Hindsight Pre-Mortem | Gary Klein protocol: assume 100% failure at Turn 100 and work backward |
| **Velocity** | 70% Information Stopping Rule | Terminate mental simulation at 70% data for Type 2 reversible decisions |
| **Ergodicity** | Non-Ergodic Absorbing Barrier Invariant | Enforce 20% capital ceiling; eliminate path-dependent ruin states before upside |
| **Heuristics** | Fast-and-Frugal 3-Cue Decision Tree | Lexicographic binary exits (Workaround -> Distribution -> 3x Stress); sub-10m filter |
| **Rehearsal** | Singular Trajectory RPD Rehearsal | Step-by-step mental movie playback of the single leading option to spot execution snags |
| **Incentives** | Counter-Metric Pairing Invariant | Never track solitary volume targets; pair velocity with defect escape and retention |
| **Custody** | Hostile Landlord Invariant | Retain direct unmediated customer channels; vendor-agnostic adapter layers |
| **Governance** | Asymmetric Tie-Breaker Invariant | Prohibit 50/50 voting control; enforce 4-year vesting with 1-year cliff |
| **Validation** | Concierge Inversion (20-Manual Threshold) | Prohibit automated pipelines until executing 20 manual workflows for paying users |
| **Coalition** | Regional Coalition Veto Invariant | Parliamentary minority executives face deterministic policy vetoes from regional sub-coalition allies |
| **Civic Action** | Public Interest Legal Pressure Invariant | Extra-parliamentary civil society fronts (e.g. CJP, ADR) leverage Supreme Court PILs as judicial counter-weights against executive overreach |
| **Regulatory** | Foreign Funding Compliance Invariant | Civil society organizations face centralized statutory scrutiny (FCRA 2020) and judicial validation (*Noel Harper*) |
| **Federalism** | Gubernatorial Legislative Non-Impediment Invariant | Governors cannot exercise indefinite pocket vetoes over passed assembly bills (*Punjab v. Principal Secretary*) |



## 4. Navigation & Retrieval Protocol

1. **Tier 1 (Catalog Routing):** Identify relevant domain chapters using this master catalog for broad architectural scoping.
2. **Tier 2 (FTS5 Lexical Lookup):** Query specific sub-topics via the SQLite FTS5 shadow table (`wiki_sections_fts`) in $< 15\text{ms}$ using `llm_wiki_query`.
3. **Tier 3 (Surgical AST Slicing):** Read only targeted section line bounds using `llm_wiki_read_section`, avoiding whole-file token bloat.
4. **Tier 4 (Backlink Graph Traversal):** Explore 1-hop and 2-hop connected concepts via `wiki_links` using `llm_wiki_backlinks`.
