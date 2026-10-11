# Ingestion Pipelines & Network Backpressure

*High-throughput firehose ingestion, backpressure regulation, WebSocket multiplexing, and network partitioning.*

---

## 1. Architectural Overview: The Ingestion Firehose

Building and maintaining an autonomous technical knowledge base requires harvesting real-world engineering experiences, post-mortems, benchmarks, and library updates from across the web. The ingestion pipeline connects multi-platform scrapers (Reddit, Twitter/X, GitHub, Lobsters, Hacker News) to the central SQLite firehose database.

However, high-velocity network streams introduce a fundamental **throughput mismatch**:
- Network sockets can pull thousands of candidate items per second from external APIs.
- The local storage engine must parse, deduplicate, calculate embeddings, and update SQLite FTS5 indexes on disk.

Without explicit **backpressure regulation**, unthrottled network ingestion exhausts local memory, starves disk write queues, and causes SQLite write lock contention.

---

## 2. Storage Boundaries & Backpressure Regulation

### 2.1 The 16MB WAL Autocheckpoint Boundary
Under high-velocity firehose ingestion, inserting raw posts generates secondary writes across dual FTS5 virtual tables (`firehose_fts` and `wiki_sections_fts`). By default, SQLite triggers an automatic checkpoint after every 1,000 pages (approx. 4MB).

In high-throughput ingestion loops:
- Default 4MB checkpointing triggers every few hundred milliseconds, causing severe NVMe write amplification and I/O thrashing.
- Checkpoint workers contend with active writers, triggering `SQLITE_BUSY` spikes.

To eliminate thrashing, the ingestion engine tunes the checkpoint boundary to **16MB** (`4,000 pages`):
```sql
PRAGMA wal_autocheckpoint = 4000;
```
This allows writers to complete bounded batch transactions in contiguous chunks, amortizing checkpoint overhead and slashing total disk write operations by over 60%.

### 2.2 Memory-Mapped I/O (MMAP) Boundaries on Windows
Configuring memory-mapped I/O (`PRAGMA mmap_size = 268435456`) speeds up read scanning across the database. However, the ingestion engine enforces two essential platform boundaries:
1. **The WAL Buffer Boundary:** In SQLite WAL mode, memory mapping applies strictly to the primary database file (`raw_firehose.db`), **not** to the active transaction log (`raw_firehose.db-wal`). Freshly ingested items reside in the WAL and must be read via standard I/O until checkpointed.
2. **Kernel Handle Locking on Windows:** On Windows systems, memory-mapped sections hold kernel file mapping handles. Opening long-lived memory-mapped connections blocks database truncates and snapshot backups with `PermissionError: [WinError 32]`. The ingestion pipeline isolates reader connections from writer connections and ensures reader cursors close immediately upon query completion.

### 2.3 Regulated Backpressure Architecture
To prevent uncheckpointed WAL inflation and writer starvation:
1. **Transactional Batching:** Harvester scripts must never execute single-row auto-commits. Items are grouped into bounded batches of **50 to 100 items** wrapped inside a single atomic transaction:
   ```python
   def ingest_batch(conn: sqlite3.Connection, items: list[dict]):
       with conn:
           conn.execute("BEGIN IMMEDIATE;")
           for item in items:
               conn.execute("INSERT OR IGNORE INTO raw_firehose ...", item)
   ```
2. **Checkpointed Pacing:** Ingestion workers monitor WAL frame counts via `PRAGMA wal_checkpoint(SQLITE_CHECKPOINT_PASSIVE)`. If the number of uncheckpointed frames exceeds 8,000 (32MB), ingestion workers pause intake until the background checkpoint worker completes.

---

## 3. High-Velocity Canonical Deduplication

External feeds frequently link to identical articles, pull requests, or announcements using different query parameters, redirect URLs, or referral tags. Ingesting duplicate raw posts wastes storage and skews vector similarity indexes.

The ingestion pipeline enforces **canonical URL normalization** before checking the SQLite index:

```python
import urllib.parse

TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "ref", "s", "t", "rcm", "trackingId", "trk", "fbclid", "gclid"
}

def normalize_canonical_url(raw_url: str) -> str:
    """Strips tracking parameters, normalizes scheme/host, and removes trailing slashes."""
    parsed = urllib.parse.urlparse(raw_url.strip())
    query_params = urllib.parse.parse_qsl(parsed.query, keep_blank_values=False)
    filtered_params = [
        (k, v) for k, v in query_params 
        if k.lower() not in TRACKING_PARAMS
    ]
    clean_query = urllib.parse.urlencode(sorted(filtered_params))
    clean_path = parsed.path.rstrip("/")
    return urllib.parse.urlunparse((
        parsed.scheme.lower(),
        parsed.netloc.lower(),
        clean_path,
        "",
        clean_query,
        ""
    ))
```

Deduplication executes inside SQLite in a single index lookup:
```sql
SELECT 1 FROM raw_firehose WHERE id = ? OR canonical_url = ? LIMIT 1;
```
If a match exists, the duplicate is dropped immediately, consuming zero additional disk space and triggering zero FTS5 write overhead.

---

## 4. Connection Resilience & Stream Multiplexing

When scraping platforms with aggressive rate limiting (e.g. GitHub API, Reddit OAuth, Twitter endpoints):
1. **Dialect Mutation:** Rather than broadcasting identical queries across platforms, each harvester translates the topic into platform-native query dialects (e.g., code-oriented qualifiers for GitHub, boolean keywords for Twitter).
2. **Circuit Breakers with Jittered Exponential Backoff:** When receiving HTTP 429 (Too Many Requests), harvesters back off exponentially with decorrelated randomized jitter to avoid thundering-herd retry storms:
   $$T_{\text{wait}} = \min(T_{\text{max}}, T_{\text{base}} \times 2^{\text{attempt}} + \text{random}(0, 1000\text{ms}))$$
3. **Bandwidth Partitioning:** Network bandwidth is strictly partitioned so high-volume scraping streams never contend with consensus heartbeat RPCs.

---

## 5. Architectural Invariants Summary

| Invariant Name | Rule / Contract | Failure Mode if Violated |
| :--- | :--- | :--- |
| **16MB Checkpoint Rule** | Set `PRAGMA wal_autocheckpoint = 4000` | Sub-second NVMe write thrashing; lock contention |
| **Canonical Deduplication** | Strip tracking tags (`utm_*`) before SQLite lookup | Duplicate post inflation; polluted FTS5 and vector indices |
| **Batching Invariant** | Group 50–100 items per `BEGIN IMMEDIATE` batch | High per-row fsync overhead; writer thread starvation |
| **High-Water Pacing** | Pause intake if uncheckpointed WAL frames exceed 32MB | Unbounded `-wal` inflation to gigabytes; read latency spike |
| **Windows Lock Isolation** | Reader connections close cursors immediately | `WinError 32: PermissionError` on database truncate |

---

## 6. Cross-Chapter Connections

- [[storage/sqlite-wal-concurrency-reality-vs-myth|SQLite WAL Concurrency: Reality vs Myth]]: How the local storage engine manages write locks during high-velocity network intake.
- [[consensus/distributed-consensus-and-coordination|Distributed Consensus & Coordination]]: Ensuring network partition failures do not cause split-brain mutations across agent clusters.
- [[caching/multi-agent-compaction-thresholds|Multi-Agent Compaction Thresholds]]: Token budgeting and cache compaction protocols to prevent network ingestion streams from saturating LLM context windows.
- [[knowledge_compiler/karpathy-llm-wiki-and-knowledge-compilers|Karpathy LLM-Wiki & Knowledge Compilers]]: How the 3-layer architecture (`raw/` firehose $\rightarrow$ `wiki/` living textbook $\rightarrow$ `site/` presentation) isolates raw network posts from clean textbook chapters.
