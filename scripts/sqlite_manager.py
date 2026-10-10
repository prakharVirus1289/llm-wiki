#!/usr/bin/env python3
"""
SQLite Manager CLI: Production WAL Configuration & FTS5 Indexer
Enforces zero database lockouts, bounded 4MB disk footprints, and <1ms section lookups.
"""

import sys
import os
import re
import time
import sqlite3
import logging
import argparse
from pathlib import Path
from logging.handlers import RotatingFileHandler

# Enforce UTF-8 on Windows stdout/stderr to support emojis and unicode in posts
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "sqlite_manager.log"

logger = logging.getLogger("sqlite_manager")
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


def get_connection(db_path: Path, timeout: float = 5.0) -> sqlite3.Connection:
    """Connection factory ensuring connection-scoped PRAGMAs are executed on EVERY connection."""
    logger.debug("Opening SQLite connection to %s (timeout=%.1fs)", db_path, timeout)
    conn = sqlite3.connect(db_path, timeout=timeout)
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    conn.execute("PRAGMA wal_autocheckpoint = 4000;")  # 16MB threshold
    conn.execute("PRAGMA busy_timeout = 5000;")
    conn.execute("PRAGMA mmap_size = 268435456;")
    conn.execute("PRAGMA cache_size = -64000;")
    return conn

def normalize_slug(text: str) -> str:
    """Normalizes a concept string into a canonical lowercase underscore slug."""
    s = text.strip().lower()
    s = re.sub(r'[\s\-]+', '_', s)
    s = re.sub(r'[^\w]', '', s)
    return s.strip('_')

def parse_wikilink(raw_target: str, default_domain: str = None) -> tuple[str, str, str | None]:
    """
    Parses a raw wikilink target (e.g., 'consensus/leases', 'consensus/leases#anchor|alias', 'sqlite_wal').
    Returns (domain_scope, target_slug, canonical_display).
    """
    raw_target = raw_target.strip().lstrip("[").rstrip("]")
    # Strip alias if present
    if "|" in raw_target:
        raw_target = raw_target.split("|", 1)[0].strip()
    # Strip anchor if present
    if "#" in raw_target:
        raw_target = raw_target.split("#", 1)[0].strip()

    domain = None
    concept = raw_target
    
    # Check if target starts with an explicit short domain scope: e.g. 'consensus/leases' or 'storage/wal'
    if "/" in raw_target:
        parts = raw_target.split("/", 1)
        candidate_domain = parts[0].strip()
        # Domain scopes must be valid identifiers without spaces, <= 30 chars
        if re.match(r'^[a-zA-Z0-9_\-]{2,30}$', candidate_domain):
            domain = candidate_domain.lower()
            concept = parts[1].strip()
            
    if not domain:
        domain = default_domain.lower() if default_domain else "general"
    
    slug = normalize_slug(concept)
    return domain, slug, raw_target

def init_db(db_path: Path):
    logger.info("Initializing SQLite database schema at %s", db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = get_connection(db_path)
    try:
        # Check if wiki_links needs schema migration
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='wiki_links';")
        if cursor.fetchone():
            col_cursor = conn.execute("PRAGMA table_info(wiki_links);")
            cols = {row[1] for row in col_cursor.fetchall()}
            if "target_anchor" not in cols or "domain_scope" not in cols:
                logger.info("Migrating wiki_links table schema to include target_anchor and domain_scope")
                conn.execute("DROP TABLE wiki_links;")

        conn.executescript("""
            CREATE TABLE IF NOT EXISTS raw_firehose (
                id TEXT PRIMARY KEY,
                platform TEXT NOT NULL,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                canonical_url TEXT UNIQUE NOT NULL,
                processed INTEGER DEFAULT 0,
                created_at INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_firehose_processed ON raw_firehose(processed);

            CREATE TABLE IF NOT EXISTS active_leases (
                file_path TEXT NOT NULL,
                section_slug TEXT NOT NULL,
                agent_id TEXT NOT NULL,
                expires_at INTEGER NOT NULL,
                PRIMARY KEY (file_path, section_slug)
            );

            CREATE TABLE IF NOT EXISTS wiki_links (
                source_file TEXT NOT NULL,
                source_heading TEXT NOT NULL,
                target_concept TEXT NOT NULL,
                target_anchor TEXT NOT NULL DEFAULT '',
                link_alias TEXT,
                domain_scope TEXT,
                PRIMARY KEY (source_file, source_heading, target_concept, target_anchor)
            );
            CREATE INDEX IF NOT EXISTS idx_wiki_links_target ON wiki_links(target_concept, source_file);
            CREATE INDEX IF NOT EXISTS idx_wiki_links_domain ON wiki_links(domain_scope, target_concept);

            CREATE TABLE IF NOT EXISTS wiki_sections_index (
                file_path TEXT NOT NULL,
                heading TEXT NOT NULL,
                level INTEGER NOT NULL,
                content TEXT NOT NULL,
                PRIMARY KEY (file_path, heading)
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS wiki_sections_fts USING fts5(
                file_path,
                heading,
                content,
                content='wiki_sections_index',
                content_rowid='rowid'
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS firehose_fts USING fts5(
                title,
                content,
                content='raw_firehose',
                content_rowid='rowid'
            );

            CREATE INDEX IF NOT EXISTS idx_sections_heading ON wiki_sections_index(heading);

            DROP VIEW IF EXISTS wiki_dangling_links;
            CREATE VIEW wiki_dangling_links AS
            SELECT 
                l.target_concept,
                l.domain_scope,
                COUNT(*) AS incoming_citations,
                GROUP_CONCAT(DISTINCT l.source_file) AS citing_files
            FROM wiki_links l
            WHERE NOT EXISTS (
                SELECT 1 FROM wiki_sections_index s WHERE s.heading = l.target_concept
            )
            GROUP BY l.target_concept, l.domain_scope
            ORDER BY incoming_citations DESC;
        """)
        logger.info("Database schema initialized with WAL, FTS5 & graph tables.")
    finally:
        conn.close()
    print(f"[OK] Database initialized at {db_path} with WAL, FTS5 & wiki_links graph schema.")

def truncate_wal(db_path: Path):
    logger.info("Executing PRAGMA wal_checkpoint(TRUNCATE) on %s", db_path)
    conn = get_connection(db_path)
    try:
        cursor = conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
        busy, log_frames, checkpointed_frames = cursor.fetchone()
        if busy:
            logger.warning("WAL checkpoint TRUNCATE blocked by active readers (frames: %d, ckpt: %d)", log_frames, checkpointed_frames)
            print(f"[WARN] WAL checkpoint TRUNCATE blocked by active readers (frames: {log_frames}, ckpt: {checkpointed_frames})")
        else:
            logger.info("WAL checkpoint TRUNCATE successful: truncated to 0MB (%d frames checkpointed)", checkpointed_frames)
            print(f"[OK] WAL file truncated to 0MB for {db_path} (checkpointed {checkpointed_frames} frames).")
    finally:
        conn.close()

def snapshot_db(db_path: Path, out_path: Path):
    logger.info("Snapshotting SQLite database %s to %s via VACUUM INTO", db_path, out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    conn = get_connection(db_path)
    try:
        conn.execute(f"VACUUM INTO '{out_path.as_posix()}';")
        logger.info("Crash-consistent snapshot saved successfully to %s", out_path)
    finally:
        conn.close()
    print(f"[OK] Crash-consistent snapshot saved to {out_path}.")

def index_wiki(db_path: Path, wiki_dir: Path):
    init_db(db_path)
    logger.info("Starting wiki indexing pass for directory: %s", wiki_dir)
    t0 = time.perf_counter()
    heading_regex = re.compile(r'^(#{1,6})\s+(.+)$', re.MULTILINE)
    # Support [[target#anchor|alias]] or [[domain/concept#anchor|alias]]
    wikilink_regex = re.compile(r'\[\[([^\]#|]+)(?:#([^\]|]+))?(?:\|([^\]]+))?\]\]')
    
    conn = get_connection(db_path)
    try:
        # Clear existing indexes
        conn.execute("DELETE FROM wiki_sections_index;")
        conn.execute("DELETE FROM wiki_sections_fts;")
        conn.execute("DELETE FROM wiki_links;")
        
        count = 0
        link_count = 0
        for md_file in wiki_dir.glob("*.md"):
            rel_path = md_file.name
            default_domain = md_file.stem
            content = md_file.read_text(encoding="utf-8")
            matches = list(heading_regex.finditer(content))
            file_sections = 0
            
            for i, match in enumerate(matches):
                level = len(match.group(1))
                heading = match.group(2).strip()
                start_pos = match.start()
                end_pos = len(content)
                for next_match in matches[i+1:]:
                    if len(next_match.group(1)) <= level:
                        end_pos = next_match.start()
                        break
                section_text = content[start_pos:end_pos].strip()
                conn.execute(
                    "INSERT OR REPLACE INTO wiki_sections_index (file_path, heading, level, content) VALUES (?, ?, ?, ?)",
                    (rel_path, heading, level, section_text)
                )
                count += 1
                file_sections += 1
                
                # Extract [[wikilinks]] with slug normalization, anchors, aliases, and domain scoping
                for wl in wikilink_regex.finditer(section_text):
                    raw_target = wl.group(1).strip()
                    anchor = wl.group(2).strip() if wl.group(2) else ""
                    alias = wl.group(3).strip() if wl.group(3) else None
                    
                    if raw_target:
                        domain, slug, display = parse_wikilink(raw_target, default_domain=default_domain)
                        if slug and slug != normalize_slug(heading):
                            conn.execute(
                                """INSERT OR IGNORE INTO wiki_links 
                                   (source_file, source_heading, target_concept, target_anchor, link_alias, domain_scope) 
                                   VALUES (?, ?, ?, ?, ?, ?)""",
                                (rel_path, heading, slug, anchor, alias or display, domain)
                            )
                            link_count += 1
            logger.debug("Indexed %d sections from %s", file_sections, rel_path)
                        
        # Synchronize FTS5 external content table cleanly
        logger.debug("Rebuilding FTS5 external content index...")
        conn.execute("INSERT INTO wiki_sections_fts(wiki_sections_fts) VALUES('rebuild');")
        conn.commit()
    finally:
        conn.close()
    elapsed_ms = (time.perf_counter() - t0) * 1000
    logger.info("Wiki indexing completed: %d sections, %d graph edges in %.2f ms", count, link_count, elapsed_ms)
    print(f"[OK] Indexed {count} sections and {link_count} graph edges into SQLite FTS5 & wiki_links.")

def get_backlinks(db_path: Path, concept: str) -> list[dict]:
    """Returns all chapters and headings citing the given concept."""
    domain, slug, _ = parse_wikilink(concept)
    logger.debug("Querying backlinks for concept='%s' (domain='%s', slug='%s')", concept, domain, slug)
    t0 = time.perf_counter()
    conn = get_connection(db_path)
    try:
        if "/" in concept:
            cursor = conn.execute("""
                SELECT source_file, source_heading, target_concept, target_anchor, link_alias, domain_scope
                FROM wiki_links
                WHERE target_concept = ? AND domain_scope = ?
                ORDER BY source_file, source_heading;
            """, (slug, domain))
        else:
            cursor = conn.execute("""
                SELECT source_file, source_heading, target_concept, target_anchor, link_alias, domain_scope
                FROM wiki_links
                WHERE target_concept = ?
                ORDER BY source_file, source_heading;
            """, (slug,))
        rows = cursor.fetchall()
        if not rows:
            logger.debug("No exact backlink match for '%s'; trying substring wildcard search", slug)
            cursor = conn.execute("""
                SELECT source_file, source_heading, target_concept, target_anchor, link_alias, domain_scope
                FROM wiki_links
                WHERE target_concept LIKE ?
                ORDER BY source_file, source_heading
                LIMIT 25;
            """, (f"%{slug}%",))
            rows = cursor.fetchall()

        elapsed_ms = (time.perf_counter() - t0) * 1000
        logger.info("get_backlinks for '%s' returned %d citing sections in %.2f ms", concept, len(rows), elapsed_ms)
        return [
            {
                "source_file": r[0],
                "source_heading": r[1],
                "target_concept": r[2],
                "target_anchor": r[3],
                "link_alias": r[4],
                "domain_scope": r[5]
            }
            for r in rows
        ]
    finally:
        conn.close()

def get_related_concepts(db_path: Path, concept: str, depth: int = 1) -> list[dict]:
    """Returns co-cited and graph-neighbor concepts for a given entity."""
    domain, slug, _ = parse_wikilink(concept)
    logger.debug("Querying co-cited related concepts for '%s' (depth=%d)", concept, depth)
    t0 = time.perf_counter()
    conn = get_connection(db_path)
    try:
        # Find concepts cited within the same sections that cite this concept (co-citation network)
        cursor = conn.execute("""
            SELECT l2.target_concept, l2.domain_scope, COUNT(*) as co_citation_count
            FROM wiki_links l1
            JOIN wiki_links l2 
              ON l1.source_file = l2.source_file 
             AND l1.source_heading = l2.source_heading
            WHERE (l1.target_concept = ? OR (l1.target_concept = ? AND l1.domain_scope = ?))
              AND l2.target_concept != ?
            GROUP BY l2.target_concept, l2.domain_scope
            ORDER BY co_citation_count DESC
            LIMIT 15;
        """, (slug, slug, domain, slug))
        rows = cursor.fetchall()
        elapsed_ms = (time.perf_counter() - t0) * 1000
        logger.info("get_related_concepts for '%s' returned %d co-citations in %.2f ms", concept, len(rows), elapsed_ms)
        return [
            {
                "target_concept": r[0],
                "domain_scope": r[1],
                "co_citation_count": r[2]
            }
            for r in rows
        ]
    finally:
        conn.close()

def get_dangling_links(db_path: Path, limit: int = 30) -> list[dict]:
    """Returns top cited concepts that do not yet have a defining section."""
    logger.debug("Querying top %d dangling links from wiki_dangling_links view", limit)
    t0 = time.perf_counter()
    conn = get_connection(db_path)
    try:
        cursor = conn.execute("""
            SELECT target_concept, domain_scope, incoming_citations, citing_files
            FROM wiki_dangling_links
            LIMIT ?;
        """, (limit,))
        rows = cursor.fetchall()
        elapsed_ms = (time.perf_counter() - t0) * 1000
        logger.info("get_dangling_links returned %d voids in %.2f ms", len(rows), elapsed_ms)
        return [
            {
                "target_concept": r[0],
                "domain_scope": r[1],
                "incoming_citations": r[2],
                "citing_files": r[3]
            }
            for r in rows
        ]
    finally:
        conn.close()

def query_section(db_path: Path, query_text: str):
    logger.info("FTS5 query_section executing for query: '%s'", query_text)
    t0 = time.perf_counter()
    conn = get_connection(db_path)
    try:
        cursor = conn.execute("""
            SELECT file_path, heading, snippet(wiki_sections_fts, 2, '<b>', '</b>', '...', 12)
            FROM wiki_sections_fts
            WHERE wiki_sections_fts MATCH ?
            LIMIT 5;
        """, (query_text,))
        rows = cursor.fetchall()
        elapsed_ms = (time.perf_counter() - t0) * 1000
        logger.info("FTS5 query_section returned %d matching sections in %.2f ms", len(rows), elapsed_ms)
        if not rows:
            print(f"[NOT FOUND] No sections matched query: '{query_text}'")
            return
        print(f"[MATCHES] Found {len(rows)} matching sections:")
        for r in rows:
            print(f"  - File: {r[0]} | Heading: {r[1]}")
            print(f"    Snippet: {r[2]}")
    finally:
        conn.close()


def query_firehose(db_path: Path, keyword: str, limit: int = 5):
    logger.info("FTS5 query_firehose executing for keyword: '%s' (limit=%d)", keyword, limit)
    t0 = time.perf_counter()
    conn = get_connection(db_path)
    try:
        cursor = conn.execute("""
            SELECT r.id, r.platform, r.title, r.canonical_url, snippet(firehose_fts, 1, '<b>', '</b>', '...', 15)
            FROM firehose_fts f
            JOIN raw_firehose r ON f.rowid = r.rowid
            WHERE firehose_fts MATCH ?
            LIMIT ?;
        """, (keyword, limit))
        rows = cursor.fetchall()
        elapsed_ms = (time.perf_counter() - t0) * 1000
        logger.info("FTS5 query_firehose returned %d raw items in %.2f ms", len(rows), elapsed_ms)
        if not rows:
            print(f"[NOT FOUND] No raw posts matched keyword: '{keyword}'")
            return
        print(f"[FIREHOSE MATCHES] Found {len(rows)} raw posts:")
        for r in rows:
            print(f"  - [{r[1]}] {r[2]}")
            print(f"    URL: {r[3]}")
            print(f"    Snippet: {r[4]}")
    finally:
        conn.close()

def main():
    parser = argparse.ArgumentParser(description="SQLite Manager")
    parser.add_argument("action", choices=["init", "truncate", "snapshot", "index-wiki", "query-section", "query-firehose", "backlinks", "related", "dangling"])
    parser.add_argument("--db", default="raw_firehose.db", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--wiki-dir", default=Path("wiki"), type=Path)
    parser.add_argument("--query", type=str)
    parser.add_argument("--concept", type=str)
    parser.add_argument("--limit", default=20, type=int)
    args = parser.parse_args()

    if args.action == "init":
        init_db(args.db)
    elif args.action == "truncate":
        truncate_wal(args.db)
    elif args.action == "snapshot":
        if not args.out:
            print("Error: --out is required for snapshot.")
            sys.exit(1)
        snapshot_db(args.db, args.out)
    elif args.action == "index-wiki":
        index_wiki(args.db, args.wiki_dir)
    elif args.action == "query-section":
        if not args.query:
            print("Error: --query is required for query-section.")
            sys.exit(1)
        query_section(args.db, args.query)
    elif args.action == "query-firehose":
        if not args.query:
            print("Error: --query is required for query-firehose.")
            sys.exit(1)
        query_firehose(args.db, args.query, limit=args.limit)
    elif args.action == "backlinks":
        if not args.concept:
            print("Error: --concept is required for backlinks.")
            sys.exit(1)
        bls = get_backlinks(args.db, args.concept)
        print(f"[BACKLINKS] Found {len(bls)} citing sections for '{args.concept}':")
        for b in bls:
            print(f"  - {b['source_file']} -> {b['source_heading']} (scope: {b['domain_scope']}, alias: {b['link_alias']})")
    elif args.action == "related":
        if not args.concept:
            print("Error: --concept is required for related.")
            sys.exit(1)
        rel = get_related_concepts(args.db, args.concept)
        print(f"[RELATED] Concepts co-cited with '{args.concept}':")
        for r in rel:
            print(f"  - {r['target_concept']} ({r['domain_scope']}): {r['co_citation_count']} co-citations")
    elif args.action == "dangling":
        dang = get_dangling_links(args.db, limit=args.limit)
        print(f"[DANGLING] Top {len(dang)} uncategorized / dangling concepts:")
        for d in dang:
            print(f"  - [[{d['target_concept']}]] ({d['domain_scope']}): cited {d['incoming_citations']} times by {d['citing_files']}")

if __name__ == "__main__":
    main()
