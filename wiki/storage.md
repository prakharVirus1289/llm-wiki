# Storage Engines & SQLite WAL

*Deep dive into local persistence, ACID durability, SQLite WAL mode, B-Trees, and lock-free concurrency.*

---

## 1. Architectural Overview

The storage engine is the persistent foundation of the LLM-Wiki living technical textbook. Modern agentic workflows require sub-millisecond metadata retrieval, atomic file modifications, and reliable concurrent access without running a heavy background database server. 

Rather than deploying a separate database daemon (such as PostgreSQL or MySQL) or relying on opaque vector databases, the textbook architecture uses an embedded **SQLite engine operating in Write-Ahead Logging (WAL) mode**, coupled with flat, human-auditable CommonMark files on disk.

---

## 2. SQLite WAL Concurrency: Reality vs Myth

### 2.1 The Single-Writer Invariant
> [!IMPORTANT]
> **Core Architectural Invariant:** SQLite WAL mode provides **multi-reader single-writer concurrency**, *not* lock-free multi-writer concurrency.

While readers do not block writers and writers do not block readers, writes remain strictly serialized via the exclusive `WAL_WRITE_LOCK`. Multiple concurrent writers must be coordinated via explicit queuing or application-level serialization. If multiple autonomous sub-agents attempt concurrent write transactions without coordination, all but one will immediately stall and trigger `SQLITE_BUSY` errors.

### 2.2 The Lock Escalation Deadlock Hazard
A frequent failure mode in autonomous agent design is relying on `busy_timeout` (e.g., 5,000 ms) while using naive deferred transactions (`BEGIN DEFERRED`):

1. Connection A begins a transaction and executes a `SELECT` query (acquiring a `SHARED` lock).
2. Connection B begins a transaction and executes a `SELECT` query (acquiring a `SHARED` lock).
3. Connection A attempts to execute an `UPDATE` or `INSERT`, attempting to escalate from `SHARED` to `RESERVED`.
4. Connection B simultaneously attempts to execute an `UPDATE` or `INSERT`, attempting the exact same escalation.

Because both connections hold `SHARED` locks, neither can be granted `RESERVED`. SQLite recognizes this state as an unresolvable deadlock and immediately returns `SQLITE_BUSY` **without honoring the configured busy timeout**.

```python
# DEADLOCK HAZARD (DO NOT USE IN MULTI-AGENT SYSTEMS):
conn.execute("BEGIN DEFERRED;")  # Naive deferred lock escalation

# PRODUCTION PATTERN: IMMEDIATE WRITE LOCK
conn.execute("BEGIN IMMEDIATE;") # Acquires RESERVED lock at transaction start
```

### 2.3 Reader Snapshot Pinning & WAL Bloat Mitigation
Automatic WAL checkpoints (`PRAGMA wal_autocheckpoint`) execute by default in passive mode (`SQLITE_CHECKPOINT_PASSIVE`). In this mode, SQLite only checkpoints frames up to the oldest active reader's read-mark in `-shm`.

If any reader process keeps an open read transaction (for example, an agent streaming LLM responses or holding an uncommitted read cursor):
1. The checkpoint worker cannot advance past that reader's snapshot point.
2. New write transactions continue appending new frames to the end of the `-wal` file.
3. The `-wal` file inflates silently from megabytes to gigabytes (observed reaching 10GB+ in high-throughput coding agent loops).
4. Read latency degrades from sub-millisecond to hundreds of milliseconds because readers must linearly scan thousands of uncheckpointed hash buckets in `-shm`.

#### Production Mitigation Strategy:
* **Short-Lived Transactions:** Enforce a strict connection lifecycle where read queries immediately commit or close cursors.
* **Separated Read/Write Connections:** Maintain dedicated, short-lived read connections and a single, serialized write connection.
* **Bounded Ingestion Tuning:** Tune autocheckpointing to 16MB bounds (`PRAGMA wal_autocheckpoint = 4000;`) to prevent disk I/O thrashing. See [[networking/the-16mb-wal-autocheckpoint-boundary|The 16MB WAL Boundary]].

---

## 3. High-Throughput Storage Invariants

### 3.1 Uncontrolled Disk I/O Traps in Coding Agent Loops
Autonomous coding agents operating in iterative loops frequently enter tight execution cycles where they re-parse, lint, and write files dozens of times per minute. If the storage engine commits after every individual line diff:
- FTS5 virtual tables (`firehose_fts` and `wiki_sections_fts`) trigger full index rebuild passes.
- Operating system file buffers are constantly flushed via `fsync`, exhausting NVMe write endurance and generating lock thrashing.

To resolve this, the storage layer implements **bounded transactional chunking**:
```python
def transactional_batch_commit(conn: sqlite3.Connection, operations: list[tuple]):
    """Executes a bounded batch of operations within a single atomic write transaction."""
    with conn:
        conn.execute("BEGIN IMMEDIATE;")
        for stmt, params in operations:
            conn.execute(stmt, params)
```

### 3.2 Memory-Mapped I/O (MMAP) Boundaries on Windows
Configuring `PRAGMA mmap_size = 268435456` (256MB) maps pages of the primary database file into the process's virtual memory space, bypassing user-space buffer copies for high-speed indexing passes.

However, two critical platform constraints apply on Windows:
1. **WAL Independence:** `mmap_size` applies exclusively to the main `.db` file, **not** to the `-wal` file. Pages residing in the WAL must still be read via standard file I/O until checkpointed.
2. **Handle Locking:** Memory-mapped sections on Windows hold active kernel file mapping handles. Attempting to delete, rename, or truncate database files while a reader holds a memory map fails with `PermissionError` (WinError 32). Always close all reader handles before running migration or truncate scripts.

---

## 4. Multi-Agent Protocol Security & Memory Concurrency

When a fleet of autonomous sub-agents reasoning over codebases accesses the living textbook simultaneously, storage isolation prevents data poisoning and race conditions:

### 4.1 Cryptographic Memory Attestation
In multi-agent architectures where agents update shared memory, unauthorized sub-agents can tamper with or overwrite established technical invariants. To enforce memory integrity, each section mutation includes an Ed25519 signature payload verifying author identity:

```python
from cryptography.hazmat.primitives.asymmetric import ed25519

def verify_section_attestation(public_key_bytes: bytes, message: bytes, signature: bytes) -> bool:
    """Verifies that the section mutation was signed by an authorized reasoning agent."""
    verify_key = ed25519.Ed25519PublicKey.from_public_bytes(public_key_bytes)
    try:
        verify_key.verify(signature, message)
        return True
    except Exception:
        return False
```
SIMD-accelerated Ed25519 checks complete in under 45 microseconds, introducing zero measurable latency into the storage pipeline.

### 4.2 Three-Valued Logic Memory States
To prevent memory drift and premature convergence, storage records support three distinct epistemic states:
1. **`ESTABLISHED` (Proven Ground Truth):** Invariants verified against empirical benchmarks or unit tests.
2. **`CONTESTED` (Epistemic Conflict):** Architectural approaches with conflicting production trade-offs. Flagged for adversarial review. See [[evaluations|Empirical Evaluations]].
3. **`HYPOTHETICAL` (Candidate Insight):** Unverified claims extracted from raw firehose posts, awaiting council evaluation.

---

## 5. Architectural Invariants Summary

| Invariant Name | Rule / Contract | Failure Mode if Violated |
| :--- | :--- | :--- |
| **Single-Writer Contract** | All writes serialized via `BEGIN IMMEDIATE` | `SQLITE_BUSY` deadlock on lock escalation |
| **Passive Checkpoint Bound** | Read transactions must terminate immediately (< 50ms) | Silent `-wal` inflation to gigabytes; read lag |
| **Transactional Chunking** | Group 50–100 candidate items per transaction | Secondary FTS5 write thrashing; NVMe saturation |
| **Windows MMAP Safety** | Explicitly close all connections before truncate | `WinError 32: The process cannot access the file` |
| **Attestation Integrity** | High-signal section mutations must carry agent signature | Sleeper memory poisoning and silent invariant drift |

---

## 6. Cross-Chapter Connections

- [[networking/the-16mb-wal-autocheckpoint-boundary|The 16MB WAL Autocheckpoint Boundary]]: How high-throughput network firehoses coordinate with SQLite WAL buffers.
- [[consensus|Distributed Consensus & Coordination]]: How single-writer storage engines scale across multi-node agent swarms using Raft leases.
- [[caching/multi-agent-compaction-thresholds|Multi-Agent Compaction Thresholds]]: Mitigating context window exhaustion by replacing runtime RAG with local SQLite shadow indices.
- [[agent_architectures/flat-markdown-vaults-vs-opaque-vector-databases|Flat Markdown Vaults vs Vector Databases]]: Why flat Markdown files paired with SQLite shadow indices outperform monolithic vector databases.
