# Memory Budgets & Context Caching

*Memory budgeting, prompt/KV-cache reuse, LRU eviction patterns, context exhaustion mitigation, and multi-agent concurrency.*

---

## 1. Architectural Overview: The Context Window Economy

In autonomous agent systems, the LLM context window is the most scarce and expensive computational resource. While modern foundation models offer large theoretical context limits (128K to 2M tokens), treating the context window as an unbounded document dump causes three severe failure modes:

1. **Quadratic Attention Latency:** Standard self-attention scales quadratically $O(N^2)$ with token length. Feeding 100K+ tokens on every turn inflates Time-to-First-Token (TTFT) from 200ms to over 5 seconds.
2. **Context Degradation & Hallucination Cascades:** Models exhibit the "Lost in the Middle" phenomenon; empirical retrieval accuracy degrades sharply as context saturates, causing agents to hallucinate non-existent tool outputs or miss critical architectural constraints.
3. **Severe Economic Inefficiency:** Re-reading static documents across repetitive iteration turns burns millions of tokens unnecessarily, increasing operational API costs by orders of magnitude.

To achieve sub-second response times and deterministic accuracy, the living textbook architecture enforces a strict **Context Window Economy** combining prompt prefix caching, surgical reading protocols, and bounded memory envelopes.

---

## 2. Prompt Prefix Caching & KV-Cache Reuse

Modern inference runtimes (such as Anthropic Prompt Caching, vLLM, and SGLang) support **prompt prefix caching**: when consecutive API requests share an identical token prefix, the engine reuses the precomputed Key-Value (KV) attention activations directly from GPU memory, bypassing prefill computation.

### 2.1 The Deterministic Prefix Invariant
To maximize KV-cache hit rates ($> 90\%$), context layouts must maintain a strictly deterministic ordering:
1. **Static System Directives:** Behavioral rules, communication guidelines, and invariant directives must remain byte-identical across requests.
2. **Deterministic Tool Declarations:** MCP tool schemas must be sorted alphabetically by tool name so JSON serialization never permutes token order.
3. **Dynamic Elements at the Tail:** Dynamic execution outputs, user requests, and surgical section texts must strictly reside at the bottom of the prompt. Placing a dynamic timestamp at the top of the prompt invalidates 100% of the downstream KV-cache on every turn.

```python
def assemble_deterministic_prompt(system_rules: str, tools: list[dict], dynamic_section: str) -> list[dict]:
    """Ensures dynamic data is strictly appended at the tail to preserve prefix KV-cache."""
    # Sort tool declarations deterministically to preserve exact token sequence
    sorted_tools = sorted(tools, key=lambda t: t["name"])
    return [
        {"role": "system", "content": system_rules},
        {"role": "system", "content": f"Available Tools:\n{json.dumps(sorted_tools, sort_keys=True)}"},
        {"role": "user", "content": dynamic_section}
    ]
```

### 2.2 Low-Bit KV-Cache Quantization (NVFP4 / FP8)
In local multi-agent deployments, storing FP16 KV-cache activations for large context windows quickly exhausts GPU VRAM (e.g., 32 concurrent agents each holding 64K tokens require over 80GB of VRAM solely for KV-cache state).

Modern runtimes utilize low-bit KV quantization:
- **FP8 (E4M3 / E5M2):** Reduces KV-cache memory consumption by 50% with zero measurable degradation in task completion accuracy.
- **NVFP4 (4-bit Microscaling):** Reduces KV memory footprint by 75%, allowing local workstations to support 4x higher agent concurrency at the cost of $< 1\%$ perplexity variance on long-context benchmarks.

---

## 3. Cache Eviction Policies & Memory Envelopes

When caching intermediate reasoning thoughts, search snippets, or file trees in local memory, autonomous agents must avoid unbounded heap growth:

### 3.1 Eviction Mechanics: LRU vs ARC
- **Least Recently Used (LRU):** Discards the least recently accessed items first. Simple and fast $O(1)$ operations, but vulnerable to cache pollution during large sequential scans (e.g. scanning an entire chapter evicts all frequently referenced core rules).
- **Adaptive Replacement Cache (ARC):** Dynamically balances between recency and frequency, self-tuning based on workload patterns. Preferred for persistent shadow index caches.

```python
from collections import OrderedDict

class LRUSectionCache:
    def __init__(self, max_tokens: int = 50000):
        self.max_tokens = max_tokens
        self.current_tokens = 0
        self.cache: OrderedDict[str, str] = OrderedDict()

    def get(self, key: str) -> str | None:
        if key not in self.cache:
            return None
        self.cache.move_to_end(key)
        return self.cache[key]

    def put(self, key: str, value: str, token_cost: int):
        if key in self.cache:
            self.cache.move_to_end(key)
            return
        while self.current_tokens + token_cost > self.max_tokens and self.cache:
            evicted_key, evicted_val = self.cache.popitem(last=False)
            self.current_tokens -= len(evicted_val.split()) * 2  # Approx token count
        self.cache[key] = value
        self.current_tokens += token_cost
```

---

## 4. Multi-Agent Compaction Thresholds

In multi-agent architectures (such as the LLM-Council reasoning fleet), spawning 50 to 100 sub-agents creates extreme context inflation if sub-agents pass uncompressed transcripts to one another.

### 4.1 The Compaction Threshold Invariant
> [!IMPORTANT]
> **Compaction Threshold Invariant:** Whenever an agent's execution scratchpad reaches **60% of its total token budget**, it must pause tool calls and execute an atomic **Compaction Pass**.

The compaction pass extracts:
1. **Established Ground Truths:** Concrete metrics, verified equations, and confirmed code diffs.
2. **Disproven Hypotheses:** Documented dead-ends to prevent peer sub-agents from repeating redundant tests.
3. **Discarded Noise:** Verbose raw terminal outputs, unparsed JSON payloads, and conversational filler are purged completely.

The compacted summary replaces the raw execution history in context, freeing up 70% of the active token envelope while preserving complete epistemic continuity.

---

## 5. Architectural Invariants Summary

| Invariant Name | Rule / Contract | Failure Mode if Violated |
| :--- | :--- | :--- |
| **Prefix Determinism** | Static prompts and tools must remain byte-identical at context head | Invalidation of 100% of downstream KV-cache; high latency |
| **Surgical Read Scope** | Read only targeted sections (< 500 tokens) via AST reader | Context window exhaustion; "Lost in the Middle" hallucination |
| **Compaction Threshold** | Trigger atomic summary pass when context reaches 60% budget | Context window overflow; catastrophic reasoning degradation |
| **Bounded Allocation** | Limit agent reasoning envelopes to $\le 2,500$ tokens per turn | API budget depletion; runaway execution loops |
| **KV Cache Quantization** | Use FP8/NVFP4 for concurrent local inference | Out-Of-Memory (OOM) GPU crashes under multi-agent load |

---

## 6. Cross-Chapter Connections

- [[storage/the-single-writer-invariant|Storage Engines & SQLite WAL]]: How local SQLite shadow indices achieve $< 5\text{ms}$ retrieval without burning context tokens on runtime RAG.
- [[knowledge_compiler/three-tier-hierarchical-reading-protocol|Three-Tier Hierarchical Reading Protocol]]: The 3-Tier Reading Protocol that cuts out 95% of token bloat before loading data into memory.
- [[agent_architectures|Agent Cognitive Architectures & Toolchains]]: Preventing memory poisoning and context corruption across multi-agent tool execution loops.
- [[evaluations|Empirical Evaluations & Failure Modes]]: Benchmarking token burn, cache hit rates, and saturation degradation curves across agent fleets.
