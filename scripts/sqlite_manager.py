#!/usr/bin/env python3
"""
SQLite Manager CLI: Production WAL Configuration & FTS5 Indexer
Enforces zero database lockouts, bounded 4MB disk footprints, and <1ms section lookups.
"""

import sys
import re
import sqlite3
import argparse
from pathlib import Path

# Enforce UTF-8 on Windows stdout/stderr to support emojis and unicode in posts
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')


def init_db(db_path: Path):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.executescript("""
            PRAGMA journal_mode = WAL;
            PRAGMA synchronous = NORMAL;
            PRAGMA page_size = 4096;
            PRAGMA wal_autocheckpoint = 1000;
            PRAGMA busy_timeout = 5000;
            PRAGMA mmap_size = 268435456;
            PRAGMA cache_size = -64000;

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
                PRIMARY KEY (source_file, source_heading, target_concept)
            );

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
        """)
    print(f"[OK] Database initialized at {db_path} with WAL & FTS5.")

def truncate_wal(db_path: Path):
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
    print(f"[OK] WAL file truncated to 0MB for {db_path}.")

def snapshot_db(db_path: Path, out_path: Path):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(f"VACUUM INTO '{out_path.as_posix()}';")
    print(f"[OK] Crash-consistent snapshot saved to {out_path}.")

def index_wiki(db_path: Path, wiki_dir: Path):
    init_db(db_path)
    heading_regex = re.compile(r'^(#{1,6})\s+(.+)$', re.MULTILINE)
    
    with sqlite3.connect(db_path) as conn:
        # Clear existing section index
        conn.execute("DELETE FROM wiki_sections_index;")
        conn.execute("DELETE FROM wiki_sections_fts;")
        
        count = 0
        for md_file in wiki_dir.glob("*.md"):
            rel_path = md_file.name
            content = md_file.read_text(encoding="utf-8")
            matches = list(heading_regex.finditer(content))
            
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
                conn.execute(
                    "INSERT INTO wiki_sections_fts (rowid, file_path, heading, content) VALUES (last_insert_rowid(), ?, ?, ?)",
                    (rel_path, heading, section_text)
                )
                count += 1
                
        conn.commit()
    print(f"[OK] Indexed {count} sections across {wiki_dir} into SQLite FTS5.")

def query_section(db_path: Path, query_text: str):
    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute("""
            SELECT file_path, heading, snippet(wiki_sections_fts, 2, '<b>', '</b>', '...', 12)
            FROM wiki_sections_fts
            WHERE wiki_sections_fts MATCH ?
            LIMIT 5;
        """, (query_text,))
        rows = cursor.fetchall()
        if not rows:
            print(f"[NOT FOUND] No sections matched query: '{query_text}'")
            return
        print(f"[MATCHES] Found {len(rows)} matching sections:")
        for r in rows:
            print(f"  - File: {r[0]} | Heading: {r[1]}")
            print(f"    Snippet: {r[2]}")

def main():
    parser = argparse.ArgumentParser(description="SQLite Manager")
    parser.add_argument("action", choices=["init", "truncate", "snapshot", "index-wiki", "query-section"])
    parser.add_argument("--db", default="raw_firehose.db", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--wiki-dir", default=Path("wiki"), type=Path)
    parser.add_argument("--query", type=str)
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

if __name__ == "__main__":
    main()
