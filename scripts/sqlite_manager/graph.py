#!/usr/bin/env python3
"""
Graph Analysis Module
Handles topological edge queries, backlinks, co-citation networks, and dangling concept detection.
"""

import time
from pathlib import Path
from .connection import get_connection, logger
from .indexer import parse_wikilink


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
