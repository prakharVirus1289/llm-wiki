# LLM-Wiki Knowledge Master Catalog
*Deterministic routing map for the living technical textbook.*

## Domain Chapters

- [[agent_architectures]]: **Agent Cognitive Architectures & Toolchains** (`wiki/agent_architectures.md`) — Autonomous coding agent workflows, MCP protocols, context degradation, and human-in-the-loop coordination. (*984 assets*)
- [[caching]]: **Memory Budgets & Context Caching** (`wiki/caching.md`) — Memory budgeting, prompt/KV-cache reuse, LRU eviction patterns, and context exhaustion mitigation. (*388 assets*)
- [[consensus]]: **Distributed Consensus & Coordination** (`wiki/consensus.md`) — Analysis of Raft, Paxos, quorum mechanisms, distributed state machines, and split-brain mitigation. (*205 assets*)
- [[evaluations]]: **Empirical Evaluations & Failure Modes** (`wiki/evaluations.md`) — Rigorous stress tests, benchmark results, production failure modes, and architectural trade-off comparisons. (*127 assets*)
- [[networking]]: **Ingestion Pipelines & Network Backpressure** (`wiki/networking.md`) — High-throughput firehose ingestion, backpressure regulation, WebSocket multiplexing, and network partitioning. (*1656 assets*)
- [[storage]]: **Storage Engines & SQLite WAL** (`wiki/storage.md`) — Deep dive into local persistence, ACID durability, SQLite WAL mode, B-Trees, and lock-free concurrency. (*280 assets*)

## Navigation Protocol
- **Tier 1:** Route domain queries directly via the catalog above.
- **Tier 2:** Query specific sub-topics via SQLite FTS5 index (`wiki_sections_fts`) in `<1ms`.
- **Tier 3:** If a topic falls outside existing domains, create a new chapter file and register it here.
