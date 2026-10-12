#!/usr/bin/env python3
"""
Firehose Module: Raw Item Ingestion & FTS5 Querying
Handles candidate ingestion, canonical URL deduplication, and full-text search.
"""

import time
from pathlib import Path
from .connection import get_connection, init_db, logger


def ingest_candidates(db_path: Path, items: list[dict]) -> dict:
    """Ingests raw candidate items into raw_firehose with automatic canonical URL deduplication."""
    if not items:
        return {"status": "success", "ingested": 0, "duplicates_skipped": 0, "total_processed": 0, "message": "No items provided"}

    init_db(db_path)
    conn = get_connection(db_path)
    now = int(time.time())
    ingested = 0
    duplicates_skipped = 0

    try:
        with conn:
            for item in items:
                cid = item.get("canonical_id") or item.get("id") or ""
                curl = item.get("canonical_url") or item.get("url") or ""
                if not curl:
                    continue

                cursor = conn.execute(
                    "SELECT 1 FROM raw_firehose WHERE id = ? OR canonical_url = ? LIMIT 1;",
                    (cid, curl)
                )
                if cursor.fetchone():
                    duplicates_skipped += 1
                    continue

                conn.execute("""
                    INSERT OR IGNORE INTO raw_firehose (id, platform, title, content, canonical_url, processed, created_at, domain)
                    VALUES (?, ?, ?, ?, ?, 0, ?, ?);
                """, (
                    cid,
                    item.get("platform", "Unknown"),
                    item.get("title", "") or "Untitled",
                    item.get("content", "") or item.get("text", "") or item.get("summary", ""),
                    curl,
                    now,
                    item.get("domain", "general")
                ))
                ingested += 1

            # Sync external content FTS5 table
            conn.execute("INSERT INTO firehose_fts(firehose_fts) VALUES('rebuild');")

        logger.info("ingest_candidates: %d new ingested, %d duplicates skipped", ingested, duplicates_skipped)
        return {
            "status": "success",
            "ingested": ingested,
            "duplicates_skipped": duplicates_skipped,
            "total_processed": len(items)
        }
    except Exception as e:
        logger.exception("ingest_candidates error: %s", e)
        return {"status": "error", "error": str(e)}
    finally:
        conn.close()


def query_firehose_raw(db_path: Path, keyword: str, limit: int = 10) -> list[dict]:
    """Executes FTS5 lexical search across raw scraped items and returns structured dict list."""
    if not db_path.exists():
        return []

    conn = get_connection(db_path)
    try:
        cursor = conn.execute("""
            SELECT r.id, r.platform, r.title, r.canonical_url, snippet(firehose_fts, 1, '<b>', '</b>', '...', 15)
            FROM firehose_fts f
            JOIN raw_firehose r ON f.rowid = r.rowid
            WHERE firehose_fts MATCH ?
            LIMIT ?;
        """, (keyword, limit))
        return [
            {"id": row[0], "platform": row[1], "title": row[2], "url": row[3], "snippet": row[4]}
            for row in cursor.fetchall()
        ]
    except Exception as e:
        logger.warning("query_firehose_raw error for keyword '%s': %s", keyword, e)
        return []
    finally:
        conn.close()
