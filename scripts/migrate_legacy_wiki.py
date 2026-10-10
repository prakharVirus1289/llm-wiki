#!/usr/bin/env python3
"""
Legacy Wiki Migration Utility:
Splits monolithic LIVING_WIKI.md into modular, thematic textbook chapters
and builds the master wiki/index.md catalog.
"""

import re
import sys
from pathlib import Path
from collections import defaultdict

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
WIKI_DIR = WORKSPACE_ROOT / "wiki"
LEGACY_FILE = Path(r"C:\Users\ASUS\Documents\deep-web-analysis\Research_Evolve_stress_test_LLM\LIVING_WIKI.md")

DOMAINS = {
    "storage": [
        "sqlite", "wal", "database", "disk", "b-tree", "acid", "persistence", "lock", "transaction", "storage"
    ],
    "consensus": [
        "consensus", "raft", "paxos", "split-brain", "distributed", "coordination", "leader", "quorum", "replication", "lease"
    ],
    "networking": [
        "network", "socket", "http", "stream", "pipeline", "backpressure", "firehose", "ingestion", "queue", "rate limit"
    ],
    "caching": [
        "cache", "caching", "lru", "eviction", "memory", "redis", "ttl", "context window", "token limit", "kv cache"
    ],
    "agent_architectures": [
        "agent", "architecture", "prompt", "mcp", "subagent", "tool", "workflow", "developer", "comprehension", "cursor", "copilot", "reasoning", "cognitive"
    ],
    "evaluations": [
        "benchmark", "eval", "evaluation", "stress test", "failure mode", "metric", "case study", "empirical"
    ]
}

DOMAIN_TITLES = {
    "storage": ("Storage Engines & SQLite WAL", "Deep dive into local persistence, ACID durability, SQLite WAL mode, B-Trees, and lock-free concurrency."),
    "consensus": ("Distributed Consensus & Coordination", "Analysis of Raft, Paxos, quorum mechanisms, distributed state machines, and split-brain mitigation."),
    "networking": ("Ingestion Pipelines & Network Backpressure", "High-throughput firehose ingestion, backpressure regulation, WebSocket multiplexing, and network partitioning."),
    "caching": ("Memory Budgets & Context Caching", "Memory budgeting, prompt/KV-cache reuse, LRU eviction patterns, and context exhaustion mitigation."),
    "agent_architectures": ("Agent Cognitive Architectures & Toolchains", "Autonomous coding agent workflows, MCP protocols, context degradation, and human-in-the-loop coordination."),
    "evaluations": ("Empirical Evaluations & Failure Modes", "Rigorous stress tests, benchmark results, production failure modes, and architectural trade-off comparisons.")
}

def classify_text(heading: str, body: str) -> str:
    combined = (heading + " " + body).lower()
    scores = defaultdict(int)
    for domain, keywords in DOMAINS.items():
        for kw in keywords:
            if kw in combined:
                # Weight heading matches higher
                weight = 3 if kw in heading.lower() else 1
                scores[domain] += weight
    
    if not scores:
        return "agent_architectures"
    return max(scores.items(), key=lambda x: x[1])[0]

def migrate():
    if not LEGACY_FILE.exists():
        print(f"Error: Legacy file {LEGACY_FILE} not found.", file=sys.stderr)
        sys.exit(1)

    print(f"Reading legacy wiki from {LEGACY_FILE}...")
    raw_text = LEGACY_FILE.read_text(encoding="utf-8")
    
    # Split by level 3 headings: ### [[...]]
    heading_pattern = re.compile(r'^(###\s+\[\[.+?\]\].*?)$', re.MULTILINE)
    matches = list(heading_pattern.finditer(raw_text))
    
    print(f"Found {len(matches)} individual technical assets in legacy wiki.")
    
    chapters = defaultdict(list)
    for i, match in enumerate(matches):
        heading_line = match.group(1).strip()
        start_pos = match.start()
        end_pos = matches[i+1].start() if i + 1 < len(matches) else len(raw_text)
        section_text = raw_text[start_pos:end_pos].strip()
        
        domain = classify_text(heading_line, section_text)
        chapters[domain].append(section_text)
    
    WIKI_DIR.mkdir(parents=True, exist_ok=True)
    
    # Write each chapter
    index_entries = []
    for domain, sections in chapters.items():
        title, desc = DOMAIN_TITLES.get(domain, (domain.title(), "Technical domain reference"))
        chapter_file = WIKI_DIR / f"{domain}.md"
        
        md_lines = [
            f"# {title}",
            f"*{desc}*",
            "",
            f"Total Empirical Assets: {len(sections)}",
            "",
            "---",
            ""
        ]
        md_lines.extend(sections)
        chapter_file.write_text("\n\n".join(md_lines) + "\n", encoding="utf-8")
        print(f"[OK] Wrote {len(sections)} sections to {chapter_file.name}")
        index_entries.append((domain, title, desc, len(sections)))

    # Build wiki/index.md (Master Catalog)
    index_lines = [
        "# LLM-Wiki Knowledge Master Catalog",
        "*Deterministic routing map for the living technical textbook.*",
        "",
        "## Domain Chapters",
        ""
    ]
    for domain, title, desc, count in sorted(index_entries):
        index_lines.append(f"- [[{domain}]]: **{title}** (`wiki/{domain}.md`) — {desc} (*{count} assets*)")
    
    index_lines.extend([
        "",
        "## Navigation Protocol",
        "- **Tier 1:** Route domain queries directly via the catalog above.",
        "- **Tier 2:** Query specific sub-topics via SQLite FTS5 index (`wiki_sections_fts`) in `<1ms`.",
        "- **Tier 3:** If a topic falls outside existing domains, create a new chapter file and register it here.",
        ""
    ])
    
    (WIKI_DIR / "index.md").write_text("\n".join(index_lines), encoding="utf-8")
    print(f"[OK] Wrote master index to {WIKI_DIR / 'index.md'}")

if __name__ == "__main__":
    migrate()
