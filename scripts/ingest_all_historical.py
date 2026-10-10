#!/usr/bin/env python3
"""
Complete Historical Ingestion & Knowledge Graph Compiler for LLM-Wiki:
Ingests every single deep-web-analysis research run, database, living wiki,
and report digest across all historical workspaces into llm-wiki.
"""

import sys
import os
import re
import time
import sqlite3
import logging
from pathlib import Path
from collections import defaultdict
from logging.handlers import RotatingFileHandler

# Enforce UTF-8 on Windows stdout/stderr
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
WIKI_DIR = WORKSPACE_ROOT / "wiki"
DB_PATH = WORKSPACE_ROOT / "raw_firehose.db"
LOG_DIR = WORKSPACE_ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "ingest_historical.log"

logger = logging.getLogger("ingest_historical")
if not logger.handlers:
    logger.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        '[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    fh = RotatingFileHandler(LOG_FILE, maxBytes=10 * 1024 * 1024, backupCount=3, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(formatter)
    logger.addHandler(fh)

    sh = logging.StreamHandler(sys.stderr)
    sh.setLevel(logging.INFO)
    sh.setFormatter(formatter)
    logger.addHandler(sh)

sys.path.append(str(WORKSPACE_ROOT / "scripts"))
from ast_splicer import ASTSplicer
import sqlite_manager

HISTORICAL_WORKSPACES = [
    Path(r"C:\Users\ASUS\Documents\deep-web-analysis\Research_Autonomous_Technical_Knowledge_Engine"),
    Path(r"C:\Users\ASUS\Documents\deep-web-analysis\Research_Evolve_stress_test_LLM"),
    Path(r"C:\Users\ASUS\Documents\deep-web-analysis\Research_Karpathy_LLM_Wiki_Coding"),
    Path(r"C:\Users\ASUS\Documents\SharedContextResearch")
]

DOMAINS = {
    "storage": [
        "sqlite", "wal", "database", "disk", "b-tree", "acid", "persistence", "lock", "transaction", "storage", "io", "write-ahead"
    ],
    "consensus": [
        "consensus", "raft", "paxos", "split-brain", "distributed", "coordination", "leader", "quorum", "replication", "lease"
    ],
    "networking": [
        "network", "socket", "http", "stream", "pipeline", "backpressure", "firehose", "ingestion", "queue", "rate limit", "partition"
    ],
    "caching": [
        "cache", "caching", "lru", "eviction", "memory", "redis", "ttl", "context window", "token limit", "kv cache"
    ],
    "agent_architectures": [
        "agent", "architecture", "prompt", "mcp", "subagent", "tool", "workflow", "developer", "comprehension", "cursor", "copilot", "reasoning", "cognitive", "swarm"
    ],
    "evaluations": [
        "benchmark", "eval", "evaluation", "stress test", "failure mode", "metric", "case study", "empirical", "accuracy", "latency"
    ],
    "knowledge_compiler": [
        "llm-wiki", "llm wiki", "karpathy", "knowledge graph", "shadow table", "governed schema", "two-hop", "traversal", "ast splicing", "compiler", "textbook", "wikilink"
    ]
}

DOMAIN_TITLES = {
    "storage": ("Storage Engines & SQLite WAL", "Deep dive into local persistence, ACID durability, SQLite WAL mode, B-Trees, and lock-free concurrency."),
    "consensus": ("Distributed Consensus & Coordination", "Analysis of Raft, Paxos, quorum mechanisms, distributed state machines, and split-brain mitigation."),
    "networking": ("Ingestion Pipelines & Network Backpressure", "High-throughput firehose ingestion, backpressure regulation, WebSocket multiplexing, and network partitioning."),
    "caching": ("Memory Budgets & Context Caching", "Memory budgeting, prompt/KV-cache reuse, LRU eviction patterns, and context exhaustion mitigation."),
    "agent_architectures": ("Agent Cognitive Architectures & Toolchains", "Autonomous coding agent workflows, MCP protocols, context degradation, and human-in-the-loop coordination."),
    "evaluations": ("Empirical Evaluations & Failure Modes", "Rigorous stress tests, benchmark results, production failure modes, and architectural trade-off comparisons."),
    "knowledge_compiler": ("Karpathy LLM-Wiki & Knowledge Compilers", "Living technical textbooks, governed schemas, relational shadow tables, AST surgical patching, and two-hop graph traversal.")
}

def classify_text(heading: str, body: str) -> str:
    combined = (heading + " " + body).lower()
    scores = defaultdict(int)
    for domain, keywords in DOMAINS.items():
        for kw in keywords:
            if kw in combined:
                weight = 3 if kw in heading.lower() else 1
                scores[domain] += weight
    
    if not scores:
        return "agent_architectures"
    return max(scores.items(), key=lambda x: x[1])[0]

def step1_ingest_raw_firehose():
    print("\n--- STEP 1: Ingesting All Raw Items into raw_firehose.db ---")
    sqlite_manager.init_db(DB_PATH)
    
    conn = sqlite3.connect(DB_PATH)
    total_scanned = 0
    total_inserted = 0
    now = int(time.time())
    
    with conn:
        for ws in HISTORICAL_WORKSPACES:
            db_file = ws / "dedup_state.sqlite"
            if not db_file.exists():
                continue
            print(f"Reading raw items from {ws.name} ({db_file.name})...")
            try:
                src_conn = sqlite3.connect(db_file)
                cols = [c[1] for c in src_conn.execute("PRAGMA table_info(processed_items);").fetchall()]
                if "is_high_signal" in cols:
                    query = "SELECT canonical_id, platform, title, summary, canonical_url, is_high_signal FROM processed_items;"
                else:
                    query = "SELECT canonical_id, platform, title, summary, canonical_url, 0 FROM processed_items;"
                
                rows = src_conn.execute(query).fetchall()
                src_conn.close()
                
                print(f"  Found {len(rows)} items in {ws.name}")
                total_scanned += len(rows)
                
                for r in rows:
                    cid, platform, title, summary, curl, is_high = r
                    title = title or "Untitled Discovery"
                    summary = summary or ""
                    curl = curl or f"urn:local:{cid}"
                    
                    cursor = conn.execute("""
                        INSERT OR IGNORE INTO raw_firehose (id, platform, title, content, canonical_url, processed, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?);
                    """, (cid, platform, title, summary, curl, 1 if is_high else 0, now))
                    if cursor.rowcount > 0:
                        total_inserted += 1
                        # Insert into FTS
                        conn.execute("""
                            INSERT INTO firehose_fts (rowid, title, content)
                            VALUES (last_insert_rowid(), ?, ?);
                        """, (title, summary))
            except Exception as e:
                print(f"  Error reading {db_file}: {e}")
                
    conn.close()
    print(f"[OK] Step 1 Complete: Scanned {total_scanned} total raw items across 4 workspaces. Unique items in raw_firehose.db: {total_inserted}")

def step2_compile_knowledge_graph():
    print("\n--- STEP 2: Compiling All Technical Wiki Assets & Report Digests ---")
    
    seen_urls = set()
    seen_titles = set()
    collected_sections = []
    
    def add_section(title, platform, url, summary):
        norm_title = re.sub(r'[^\w\s]', '', title.lower()).strip()
        norm_url = url.strip().lower()
        if norm_url and norm_url in seen_urls:
            return
        if norm_title and norm_title in seen_titles:
            return
            
        if norm_url:
            seen_urls.add(norm_url)
        if norm_title:
            seen_titles.add(norm_title)
            
        clean_title = re.sub(r'[^\w\s\-\./]', '', title).strip()[:90]
        domain = classify_text(clean_title, summary)
        
        # Balance code fence if odd count of ```
        clean_summary = summary.strip()
        if clean_summary.count("```") % 2 != 0:
            clean_summary += "\n```"
        
        md_block = f"""### [[{clean_title}]]
- **Platform:** {platform}
- **URL:** {url}
- **Synthesis & Architectural Value:**
  {clean_summary}"""
        
        collected_sections.append((domain, clean_title, md_block))

    # 1. Parse all living wikis
    wiki_sources = [
        Path(r"C:\Users\ASUS\Documents\deep-web-analysis\Research_Evolve_stress_test_LLM\LIVING_WIKI.md"),
        Path(r"C:\Users\ASUS\Documents\deep-web-analysis\Research_Autonomous_Technical_Knowledge_Engine\LIVING_WIKI.md"),
        Path(r"C:\Users\ASUS\Documents\SharedContextResearch\TEAM_WIKI_IDEAS.md")
    ]
    
    for wf in wiki_sources:
        if not wf.exists():
            continue
        print(f"Parsing technical assets from {wf.name} ({wf.parent.name})...")
        raw_text = wf.read_text(encoding="utf-8", errors="replace")
        
        if wf.name == "TEAM_WIKI_IDEAS.md":
            team_regex = re.compile(
                r'###\s+\[\[(.+?)\]\]\s*\n'
                r'-\s+URL:\s*(.+?)\n'
                r'-\s+(?:Summary|Production Analysis):\s*([\s\S]+?)(?=\n###|\Z)',
                re.MULTILINE
            )
            matches = list(team_regex.finditer(raw_text))
            print(f"  Extracted {len(matches)} structured technical assets from {wf.name}")
            for m in matches:
                t = m.group(1).strip()
                u = m.group(2).strip()
                s = m.group(3).strip()
                p = "Reddit / Web / X"
                add_section(t, p, u, s)
        else:
            asset_regex = re.compile(
                r'###\s+\[\[(.+?)\]\]\s*\n'
                r'-\s+\*\*Platform:\*\*\s*(.+?)\n'
                r'-\s+\*\*URL:\*\*\s*(.+?)\n'
                r'-\s+\*\*Synthesis & Architectural Value:\*\*\s*\n([\s\S]+?)(?=\n###|\Z)',
                re.MULTILINE
            )
            matches = list(asset_regex.finditer(raw_text))
            print(f"  Extracted {len(matches)} structured technical assets from {wf.name}")
            for m in matches:
                t = m.group(1).strip()
                p = m.group(2).strip()
                u = m.group(3).strip()
                s = m.group(4).strip()
                add_section(t, p, u, s)


    # 2. Parse all high-signal discoveries from report files across all 4 workspaces
    report_count = 0
    report_asset_count = 0
    for ws in HISTORICAL_WORKSPACES:
        rep_dir = ws / "reports"
        if not rep_dir.exists():
            continue
        for rep_file in rep_dir.glob("*.md"):
            report_count += 1
            content = rep_file.read_text(encoding="utf-8", errors="replace")
            
            # Pattern: #### [HIGH-SIGNAL] <title> \n - **Platform:** ... \n - **Canonical URL:** ... \n - **Analysis:** ...
            rep_regex = re.compile(
                r'####\s+\[(?:HIGH-SIGNAL|DISCUSSION/PERSPECTIVE)\]\s*(.+?)\n'
                r'-\s+\*\*Platform:\*\*\s*(.+?)\n'
                r'-\s+\*\*Canonical URL:\*\*\s*(.+?)\n'
                r'-\s+\*\*Analysis:\*\*\s*(.+?)(?=\n####|\Z)',
                re.MULTILINE
            )
            for m in rep_regex.finditer(content):
                t = m.group(1).strip()
                p = m.group(2).strip()
                u = m.group(3).strip()
                s = m.group(4).strip()
                add_section(t, p, u, s)
                report_asset_count += 1
                
    print(f"Parsed {report_count} report digests; extracted {report_asset_count} candidate assets.")
    print(f"Total Unique Technical Assets Compiled: {len(collected_sections)}")
    
    # Group by domain
    chapter_groups = defaultdict(list)
    for domain, title, md_block in collected_sections:
        chapter_groups[domain].append(md_block)
        
    WIKI_DIR.mkdir(parents=True, exist_ok=True)
    index_entries = []
    
    for domain, title_desc in DOMAIN_TITLES.items():
        title, desc = title_desc
        sections = chapter_groups[domain]
        chapter_file = WIKI_DIR / f"{domain}.md"
        
        md_lines = [
            f"# {title}",
            f"*{desc}*",
            "",
            f"**Total Compiled Empirical Assets:** `{len(sections)}`",
            "",
            "---",
            ""
        ]
        md_lines.extend(sections)
        chapter_file.write_text("\n\n".join(md_lines) + "\n", encoding="utf-8")
        print(f"[OK] Wrote {len(sections)} sections to wiki/{chapter_file.name}")
        index_entries.append((domain, title, desc, len(sections)))
        
    # Build master catalog wiki/index.md
    index_lines = [
        "# LLM-Wiki Knowledge Master Catalog",
        "*Deterministic routing map for the living technical textbook.*",
        f"*Compiled from {len(collected_sections)} verified multi-platform empirical assets.*",
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
    print(f"[OK] Wrote master index to wiki/index.md")

def step3_reindex_fts():
    print("\n--- STEP 3: Rebuilding SQLite FTS5 Index for wiki/ ---")
    sqlite_manager.index_wiki(DB_PATH, WIKI_DIR)

def step4_lint_all():
    print("\n--- STEP 4: Linting All Markdown Chapters ---")
    all_ok = True
    for md_file in WIKI_DIR.glob("*.md"):
        errs = ASTSplicer.lint_file(md_file)
        if errs:
            print(f"[LINT WARNING] {md_file.name}: {errs}")
            all_ok = False
        else:
            print(f"  ✓ {md_file.name} passed linting.")
    if all_ok:
        print("[OK] All wiki chapters 100% clean.")

def main():
    print("=================================================================")
    print("   COMPLETE HISTORICAL COMPILATION & INGESTION FOR LLM-WIKI      ")
    print("=================================================================")
    step1_ingest_raw_firehose()
    step2_compile_knowledge_graph()
    step3_reindex_fts()
    step4_lint_all()
    print("\n=================================================================")
    print("       HISTORICAL INGESTION & COMPILATION COMPLETE (100%)        ")
    print("=================================================================\n")

if __name__ == "__main__":
    main()
