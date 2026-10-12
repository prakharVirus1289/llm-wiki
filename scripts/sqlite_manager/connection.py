#!/usr/bin/env python3
"""
Database Connection & Schema Initializer
Provides WAL-configured SQLite connections, schema DDL, and maintenance routines.
"""

import sys
import sqlite3
import logging
from pathlib import Path
from logging.handlers import RotatingFileHandler

# Enforce UTF-8 on Windows stdout/stderr
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

LOG_DIR = Path(__file__).resolve().parent.parent.parent / "logs"
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


def init_db(db_path: Path):
    """Initializes tables, indexes, and full-text virtual tables."""
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

        # Check if wiki_sections_index needs schema migration for embedding and heading_slug columns
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='wiki_sections_index';")
        if cursor.fetchone():
            col_cursor = conn.execute("PRAGMA table_info(wiki_sections_index);")
            cols = {row[1] for row in col_cursor.fetchall()}
            if "embedding" not in cols:
                logger.info("Migrating wiki_sections_index table schema to include embedding BLOB column")
                conn.execute("ALTER TABLE wiki_sections_index ADD COLUMN embedding BLOB;")
            if "heading_slug" not in cols:
                logger.info("Migrating wiki_sections_index table schema to include heading_slug column")
                conn.execute("ALTER TABLE wiki_sections_index ADD COLUMN heading_slug TEXT NOT NULL DEFAULT '';")

        # Check if raw_firehose needs schema migration for domain column
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='raw_firehose';")
        if cursor.fetchone():
            col_cursor = conn.execute("PRAGMA table_info(raw_firehose);")
            cols = {row[1] for row in col_cursor.fetchall()}
            if "domain" not in cols:
                logger.info("Migrating raw_firehose table schema to include domain column")
                conn.execute("ALTER TABLE raw_firehose ADD COLUMN domain TEXT NOT NULL DEFAULT 'general';")

        conn.executescript("""
            CREATE TABLE IF NOT EXISTS raw_firehose (
                id TEXT PRIMARY KEY,
                platform TEXT NOT NULL,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                canonical_url TEXT UNIQUE NOT NULL,
                processed INTEGER DEFAULT 0,
                created_at INTEGER NOT NULL,
                domain TEXT NOT NULL DEFAULT 'general'
            );
            CREATE INDEX IF NOT EXISTS idx_firehose_processed ON raw_firehose(processed);
            CREATE INDEX IF NOT EXISTS idx_firehose_domain ON raw_firehose(domain);

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
                heading_slug TEXT NOT NULL DEFAULT '',
                level INTEGER NOT NULL,
                content TEXT NOT NULL,
                embedding BLOB,
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
            CREATE INDEX IF NOT EXISTS idx_sections_slug ON wiki_sections_index(heading_slug);

            DROP VIEW IF EXISTS wiki_dangling_links;
            CREATE VIEW wiki_dangling_links AS
            SELECT 
                l.target_concept,
                l.domain_scope,
                COUNT(*) AS incoming_citations,
                GROUP_CONCAT(DISTINCT l.source_file) AS citing_files
            FROM wiki_links l
            WHERE NOT EXISTS (
                SELECT 1 FROM wiki_sections_index s 
                WHERE s.heading_slug = l.target_concept 
                   OR s.file_path = l.target_concept || '.md'
            )
            GROUP BY l.target_concept, l.domain_scope
            ORDER BY incoming_citations DESC;

            DROP VIEW IF EXISTS wiki_resolved_links;
            CREATE VIEW wiki_resolved_links AS
            SELECT 
                l.source_file,
                l.source_heading,
                COALESCE(s.file_path, s_file.file_path) AS target_file,
                COALESCE(s.heading, s_file.heading) AS target_heading,
                l.target_concept,
                l.target_anchor,
                l.link_alias,
                l.domain_scope,
                CASE WHEN (s.file_path IS NOT NULL OR s_file.file_path IS NOT NULL) THEN 1 ELSE 0 END AS is_resolved,
                CASE WHEN l.source_file != COALESCE(s.file_path, s_file.file_path) THEN 1 ELSE 0 END AS is_cross_chapter
            FROM wiki_links l
            LEFT JOIN wiki_sections_index s 
              ON s.heading_slug = l.target_concept
            LEFT JOIN wiki_sections_index s_file
              ON (s_file.file_path = l.target_concept || '.md' AND s_file.level = 1);
        """)
        logger.info("Database schema initialized with WAL, FTS5 & graph tables.")
    finally:
        conn.close()
    print(f"[OK] Database initialized at {db_path} with WAL, FTS5 & wiki_links graph schema.", file=sys.stderr)


def truncate_wal(db_path: Path):
    """Executes PRAGMA wal_checkpoint(TRUNCATE) to reclaim disk space."""
    logger.info("Executing PRAGMA wal_checkpoint(TRUNCATE) on %s", db_path)
    conn = get_connection(db_path)
    try:
        cursor = conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
        busy, log_frames, checkpointed_frames = cursor.fetchone()
        if busy:
            logger.warning("WAL checkpoint TRUNCATE blocked by active readers (frames: %d, ckpt: %d)", log_frames, checkpointed_frames)
            print(f"[WARN] WAL checkpoint TRUNCATE blocked by active readers (frames: {log_frames}, ckpt: {checkpointed_frames})", file=sys.stderr)
        else:
            logger.info("WAL checkpoint TRUNCATE successful: truncated to 0MB (%d frames checkpointed)", checkpointed_frames)
            print(f"[OK] WAL file truncated to 0MB for {db_path} (checkpointed {checkpointed_frames} frames).", file=sys.stderr)
    finally:
        conn.close()


def snapshot_db(db_path: Path, out_path: Path):
    """Saves a crash-consistent point-in-time snapshot of the database."""
    logger.info("Snapshotting SQLite database %s to %s via VACUUM INTO", db_path, out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    conn = get_connection(db_path)
    try:
        conn.execute(f"VACUUM INTO '{out_path.as_posix()}';")
        logger.info("Crash-consistent snapshot saved successfully to %s", out_path)
    finally:
        conn.close()
    print(f"[OK] Crash-consistent snapshot saved to {out_path}.", file=sys.stderr)
