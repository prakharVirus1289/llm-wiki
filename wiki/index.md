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
* **Focus:** Benchmarking agent architectures, token burn curves, context saturation, retrieval trade-offs, and production failure modes.
* **Core Mechanisms:** Token burn vs accuracy curves, the 60% context saturation cliff, surgical AST slicing benchmark (95% token savings vs full-file loading), dense vector vs SQLite FTS5 latency comparison, and empirical root-cause analysis of production failure modes.

---

## 3. Master Invariants Matrix

| Domain | Architectural Invariant | Enforcement Mechanism |
| :--- | :--- | :--- |
| **Storage** | Multi-Reader Single-Writer Isolation | Strict serialization of write transactions; `BEGIN IMMEDIATE` |
| **Consensus** | Election Safety & Leader Lease | Quorum grants with synchronized monotonically bounded lease timers |
| **Networking** | Bounded WAL Checkpoint Boundary | Autocheckpointing pinned at 16MB (4,000 pages) to prevent I/O stalls |
| **Caching** | Deterministic Prefix Invariant | Static system directives and tool schemas placed strictly at index 0 |
| **Agents** | Three-Valued Epistemic Memory | Discrete tracking of `Settled`, `Indeterminate`, and `Refuted` assertions |
| **Compiler** | Surgical Section AST Patching | CST byte offset replacement (`start_line` to `end_line`) |
| **Evaluations** | Context Window Compaction Boundary | Bounded session compaction triggered at 60% context saturation |

---

## 4. Navigation & Retrieval Protocol

1. **Tier 1 (Catalog Routing):** Identify relevant domain chapters using this master catalog for broad architectural scoping.
2. **Tier 2 (FTS5 Lexical Lookup):** Query specific sub-topics via the SQLite FTS5 shadow table (`wiki_sections_fts`) in $< 15\text{ms}$ using `llm_wiki_query`.
3. **Tier 3 (Surgical AST Slicing):** Read only targeted section line bounds using `llm_wiki_read_section`, avoiding whole-file token bloat.
4. **Tier 4 (Backlink Graph Traversal):** Explore 1-hop and 2-hop connected concepts via `wiki_links` using `llm_wiki_backlinks`.
