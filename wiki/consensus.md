# Distributed Consensus & Coordination

*Analysis of Raft, Paxos, quorum mechanisms, distributed state machines, leader leases, and split-brain mitigation.*

---

## 1. Architectural Overview: Coordination in Multi-Agent Systems

When multiple autonomous coding agents work concurrently across different repositories, tasks, or machines, they must agree on shared facts without central point-of-failure bottlenecks. Without formal consensus mechanisms, distributed agent swarms suffer from **split-brain mutations** (where two agents execute conflicting architectural refactors simultaneously) or **lost updates** (where one agent overwrites another agent's work).

Distributed consensus algorithms guarantee that a cluster of independent nodes agrees on a single, deterministic sequence of state transitions, even when individual nodes crash or network messages are delayed, reordered, or dropped.

---

## 2. The Raft Consensus Protocol

The living textbook architecture standardizes on the **Raft consensus algorithm** due to its explicit decomposition of consensus into three independent subproblems: **leader election**, **log replication**, and **safety**.

### 2.1 Leader Election Algorithm
At any given instant, every agent node in the consensus cluster exists in one of three states:
- **`LEADER`:** Handles all mutation requests, coordinates log replication, and maintains heartbeats.
- **`FOLLOWER`:** Passive node that responds to RPCs from leaders and candidates.
- **`CANDIDATE`:** Intermediate state used during elections to collect votes.

#### Election Invariants:
1. **Randomized Election Timeouts:** To prevent split-vote deadlocks where multiple candidates start elections simultaneously, nodes select election timeouts randomized between **150 ms and 300 ms**.
2. **One Vote Per Term:** A node grants at most one vote per term number on a first-come, first-served basis.
3. **Majority Quorum ($N/2 + 1$):** A candidate is elected leader only if it receives affirmative votes from a strict mathematical majority of the cluster.

### 2.2 Log Replication & State Machine Safety
Once elected, the leader acts as the sole intake point for mutations:
1. An agent proposing a textbook patch submits the mutation to the leader.
2. The leader appends the entry to its local log and issues `AppendEntries` RPCs to all followers.
3. When the entry has been safely replicated on a majority of nodes, the leader commits the entry and applies it to the state machine.
4. The leader includes the updated `commit_index` in subsequent heartbeat messages, notifying followers to apply the entry locally.

> [!IMPORTANT]
> **The Leader Completeness Invariant:** If a log entry is committed in a given term, that entry will be present in the logs of the leaders for all higher terms. A follower will reject a candidate's vote request if the candidate's log is less up-to-date than the follower's own log.

---

## 3. Distributed Leases & Storage Engine Integration

### 3.1 Leader Leases & SQLite Single-Writer Locks
As detailed in [[storage/the-single-writer-invariant|The Single-Writer Invariant]], the local SQLite storage engine strictly permits only one active writer transaction (`BEGIN IMMEDIATE`) at a time. In a distributed multi-agent deployment, consensus provides the **time-bounded leader lease** that determines which agent node is authorized to hold the write connection:

```python
import time

class LeaderLease:
    def __init__(self, duration_ms: int = 5000):
        self.duration_ms = duration_ms
        self.lease_expires_at = 0
        self.term = 0

    def is_valid(self) -> bool:
        """Returns True only if the local node holds an unexpired leader lease."""
        return (time.time() * 1000) < self.lease_expires_at

    def renew(self, quorum_ack_time_ms: float, term: int):
        """Renews lease upon receiving heartbeat acknowledgments from majority quorum."""
        self.term = term
        self.lease_expires_at = quorum_ack_time_ms + self.duration_ms
```

### 3.2 Split-Brain Mitigation Under Network Partitions
If a network partition isolates a 5-node cluster into two partitions (Node A, B on Side 1; Node C, D, E on Side 2):
1. Side 1 (2 nodes) cannot reach quorum ($2 < 5/2 + 1 = 3$). Node A's leader lease expires immediately; it steps down and rejects all write operations.
2. Side 2 (3 nodes) holds majority quorum ($3 \ge 3$). Nodes C, D, and E elect a new leader for a higher term and continue processing verified mutations.
3. When the network partition heals, Node A observes the higher term from Side 2, yields immediately, and synchronizes its local log to match the majority state.

---

## 4. Autonomous Rollback & State Machine Reversibility

In an LLM-compiled knowledge base, autonomous agents generate hypotheses, benchmark claims, and patch sections continuously. When an empirical test or peer critique disproves an earlier claim, the cluster must roll back the invalid mutation without corrupting subsequent sections.

### 4.1 Git as the Cryptographically Signed Consensus DAG
Rather than inventing custom undo logs or database transaction replay tables, the living textbook uses **Git as the immutable Merkle DAG**:
- Every verified consensus commit corresponds to an atomic Git commit (`git commit -m "..."`).
- Rolling back an erroneous mutation executes an atomic Git revert (`git revert <sha>`).
- Git's cryptographic SHA-256 tree hashing provides guaranteed audit trails and instant reversibility out of the box with zero custom storage code.

---

## 5. Architectural Invariants Summary

| Invariant Name | Rule / Contract | Failure Mode if Violated |
| :--- | :--- | :--- |
| **Quorum Threshold** | All decisions require $\lfloor N/2 \rfloor + 1$ affirmative votes | Split-brain partition; conflicting concurrent mutations |
| **Leader Lease Expiry** | Writer connection dropped immediately when lease expires | Stale writer overwriting newer partition state |
| **Log Monotonicity** | Log entries are append-only; entries never modified in-place | State machine divergence across cluster nodes |
| **Atomic Remote Push** | Every committed mutation pushed immediately to remote tracking branch | Divergent local branches; lost historical provenance |
| **Leader Completeness** | Candidate vote rejected if log term/index is behind voter | Overwriting committed history during leader transitions |

---

## 6. Cross-Chapter Connections

- [[storage/sqlite-wal-concurrency-reality-vs-myth|SQLite WAL Concurrency: Reality vs Myth]]: How local single-writer database engines coordinate with distributed leader leases.
- [[networking/ingestion-pipelines-and-network-backpressure|Ingestion Pipelines & Network Backpressure]]: Regulating network throughput so consensus heartbeat RPCs are never starved by high-volume firehose traffic.
- [[agent_architectures/agent-cognitive-architectures-and-toolchains|Agent Cognitive Architectures & Toolchains]]: How autonomous coding sub-agents coordinate multi-step refactoring workflows across isolated git worktrees.
- [[evaluations/empirical-evaluations-and-failure-modes|Empirical Evaluations & Failure Modes]]: Benchmarking consensus recovery times, split-brain failovers, and network partition saturation curves.
