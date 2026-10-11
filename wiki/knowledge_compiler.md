# Karpathy LLM-Wiki & Knowledge Compilers

*Living technical textbooks, governed schemas, relational shadow tables, AST surgical patching, and two-hop graph traversal.*

---

## 1. Architectural Overview

Traditional retrieval-augmented generation (RAG) re-indexes raw, unorganized documents at query time. This approach forces the language model to repeatedly synthesize raw fragments on every question, leading to high token burn, inconsistent answers, and context window saturation.

The **Karpathy LLM-Wiki pattern** replaces ad-hoc RAG with a living, compiled knowledge base. In this paradigm, the language model acts as an incremental knowledge compiler: it continuously processes raw inputs, distills empirical insights, and integrates them into a structured, interconnected textbook written in plain Markdown.

---

## 2. The Three-Layer Wiki Architecture

The knowledge compiler organizes information across three distinct, decoupled tiers:

### 2.1 Layer 1: Immutable Ground Truth (`raw/` & `raw_firehose.db`)
* **Role:** Append-only permanent storage for unvarnished primary sources (research papers, engineering post-mortems, social discussions, API changelogs).
* **Guarantees:** Write-once, read-many (WORM). Raw sources are never rewritten or deleted during synthesis passes.
* **Storage Substrate:** Embedded SQLite database with unique URL constraints, canonical normalization, and SHA-256 deduplication.

### 2.2 Layer 2: Living Technical Textbook (`wiki/*.md`)
* **Role:** Synthesized, human-readable CommonMark chapters representing the current state of engineering knowledge.
* **Schema Governance:** Every chapter adheres to standard structural contracts:
  - Document title and conceptual subtitle.
  - Architectural overview and core design principles.
  - Deep-dive technical sections detailing mechanisms and code patterns.
  - Explicit tables of architectural invariants and failure modes.
  - Bidirectional `[[target-domain/target-slug|Alias]]` cross-chapter wikilinks.
* **Human Auditability:** Stored as plain text in Git, enabling human engineers to review git diffs, inspect technical claims, and edit files directly in standard editors.

### 2.3 Layer 3: Relational Shadow Index & Query Endpoints
* **Role:** High-speed lookup substrate that powers agent retrieval without requiring disk scans over raw text files.
* **Shadow Tables:**
  - `wiki_sections_index`: Tracks every file path, heading title, slug, heading level, and exact `start_line` / `end_line` coordinates.
  - `wiki_links`: Maps bidirectional edges (`source_file`, `target_slug`, `target_heading`, `alias`).
  - `wiki_sections_fts`: SQLite FTS5 virtual table indexing heading and content tokens for sub-15ms BM25 ranking.

---

## 3. Three-Tier Hierarchical Reading Protocol

When an autonomous coding agent needs context to answer a question or complete a code modification, loading entire 1,000-line markdown files quickly exhausts the agent's context budget.

To maintain strict token economy, the knowledge compiler enforces the **3-Tier Hierarchical Reading Protocol**:

### 3.1 Tier 1: FTS5 Lexical Filtering (`llm_wiki_query`)
* Executes an SQLite FTS5 query using BM25 scoring over heading titles and content snippets.
* Completes in $< 15\text{ms}$ with zero filesystem reads on raw markdown.
* Returns only candidate file paths, section headings, and line boundaries.

### 3.2 Tier 2: Surgical Section Slicing (`llm_wiki_read_section`)
* Rather than reading an entire chapter, the runtime extracts only the precise line range (`start_line` to `end_line`) corresponding to the target heading.
* An average section payload requires only **250 to 450 tokens**, compared to 10,000+ tokens for full-chapter loading.
* Prevents context window saturation and preserves model attention for complex code generation.

### 3.3 Tier 3: Bidirectional Backlink Graph Navigation (`llm_wiki_backlinks`)
* Traverses the relational `wiki_links` table to locate adjacent concepts within 1 or 2 hops of the active node.
* Eliminates recursive file crawler loops and ensures that related architectural invariants are loaded deterministically.

---

## 4. AST-Driven Surgical Section Patching

### 4.1 The Whole-File Rewrite Anti-Pattern
A frequent failure mode in automated knowledge maintenance is prompting an LLM to "rewrite the entire file with updated information":
* As documents grow beyond 500 lines, LLMs frequently truncate lower sections, hallucinate missing details, or drop subtle docstrings.
* Concurrent file edits result in catastrophic merge conflicts.

### 4.2 In-Place Byte-Level Replacement
The knowledge compiler utilizes a **Concrete Syntax Tree (CST) Surgical Patching Engine**:
1. The compiler parses the target markdown document into CommonMark AST nodes.
2. It identifies the target heading node and calculates its exact character byte offsets:
   $$\text{Range} = [\text{byte\_start}, \text{byte\_end})$$
3. The LLM generates *only* the updated text for that specific section.
4. The engine performs an atomic in-place byte substitution, leaving all preceding and succeeding sections bit-for-bit identical.
5. In the same atomic transaction, the SQLite shadow index is updated with the new line boundaries.

---

## 5. Bidirectional Wikilink Governance & Epistemic Audit

### 5.1 The 4-Point Epistemic Link Audit
Automated link generators often produce spurious cross-references based on superficial token similarity (e.g., linking every occurrence of the word "memory" or "database").

To prevent graph pollution, every candidate cross-reference must pass the **4-Point Epistemic Link Audit**:

```
[Candidate Link: Concept A -> Concept B]
   │
   ├── 1. Substantive Concept Test: Is Target a defined architectural entity? (Not filler or dates)
   │      └── NO  --> REJECT
   │      └── YES --> Continue
   │
   ├── 2. Causal Architecture Test: Does understanding A depend on the mechanisms of B?
   │      └── NO  --> REJECT
   │      └── YES --> Continue
   │
   ├── 3. Epistemic Grounding Test: Is the connection backed by verified compiler/test evidence?
   │      └── NO  --> REJECT
   │      └── YES --> Continue
   │
   └── 4. Canonical Slug Resolution: Does the target slug exist in wiki_sections_index?
          └── NO  --> REJECT (Flag as Dangling Link)
          └── YES --> APPROVE AND PERSIST
```

### 5.2 Dangling Link Detection & Automated Repair
* A dangling link occurs when a chapter references `[[target-domain/target-slug|Alias]]`, but `target-domain/target-slug` does not exist in `wiki_sections_index`.
* The maintenance toolchain runs automated integrity sweeps via the MCP server interface:
  ```json
  {"tool": "llm_wiki_get_graph", "arguments": {"action": "dangling"}}
  ```
* Any unresolvable references are either routed to a canonical alias or pruned before publication.

---

## 6. Architectural Invariants & Failure Modes

| Invariant | Enforcement Mechanism | Failure Mode If Violated |
| :--- | :--- | :--- |
| **Immutable Ground Truth** | WORM policy on `raw/` and SQLite `raw_firehose.db` | Accidental data corruption and loss of reproducible primary source evidence. |
| **Human-Auditable Markdown** | Plain CommonMark files tracked in Git | Opaque binary lock-in and inability for human engineers to review changes. |
| **3-Tier Retrieval Budgeting** | FTS5 filtering before surgical AST slicing | Catastrophic token exhaustion and degraded model attention. |
| **Surgical Section Patching** | CST byte offset replacement (`start_line` to `end_line`) | Accidental file truncation and corrupted document sections. |
| **Shadow Index Synchronicity** | Atomic SQLite transaction updating shadow tables after edits | Stale search results and broken line coordinate lookups. |
| **4-Point Epistemic Link Audit** | Rejecting superficial vector similarity matches | Graph pollution and noisy, irrelevant cross-references. |

---

## 7. Cross-Chapter Connections

* **[[storage/the-single-writer-invariant|SQLite Single-Writer Invariant]]:** Explains how the SQLite shadow index coordinates concurrent agent queries with serialized writes.
* **[[storage/reader-snapshot-pinning-and-wal-bloat-mitigation|Reader Snapshot Pinning]]:** Details how to prevent WAL bloat during continuous ingestion sweeps.
* **[[caching/the-deterministic-prefix-invariant|The Deterministic Prefix Invariant]]:** Outlines prompt engineering standards for LLM compiler passes to maximize KV-cache reuse.
* **[[agent_architectures/flat-markdown-vaults-vs-opaque-vector-databases|Flat Markdown Vaults vs Vector Databases]]:** Explores why agent cognitive loops benefit from plain Markdown memory substrates.
* **[[evaluations/token-burn-vs-accuracy-saturation-curve|Token Burn vs Accuracy Saturation]]:** Details the empirical data demonstrating why full-file loads degrade reasoning compared to surgical section slicing.
