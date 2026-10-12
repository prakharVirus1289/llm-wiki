#!/usr/bin/env python3
"""
Wiki Markdown Indexer & AST Section Parser
Parses Markdown files into headings, rebuilds FTS5, and manages embeddings.
Link edges and rationales are managed intentionally via graph.py / MCP tools.
"""

import re
import time
from pathlib import Path
from .connection import get_connection, init_db, logger


def normalize_slug(text: str) -> str:
    """Normalizes a concept string into a canonical lowercase underscore slug."""
    s = text.strip().lower()
    s = s.replace('&', 'and')
    # Strip leading section numbers like "2.1 ", "1. ", "3.2.1 "
    stripped = re.sub(r'^[0-9]+(\.[0-9]+)*\s*', '', s)
    if stripped:
        s = stripped
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


def index_wiki(db_path: Path, wiki_dir: Path, target_file: str | Path = None, embed: bool = False):
    """
    Indexes Markdown files in wiki_dir into SQLite FTS5 and vector index.
    If target_file is provided, incrementally indexes only that specific file.
    Link graph edges are intentionally managed via graph.py, never wiped by indexer.
    """
    init_db(db_path)
    t0 = time.perf_counter()
    heading_regex = re.compile(r'^(#{1,6})\s+(.+)$', re.MULTILINE)

    # Resolve target file list
    if target_file:
        target_path = Path(target_file)
        if not target_path.is_absolute():
            # If target_file starts with wiki/ or is bare filename
            cleaned = str(target_file).replace("\\", "/")
            if cleaned.startswith("wiki/"):
                cleaned = cleaned[5:]
            target_path = wiki_dir / cleaned
        if not target_path.exists():
            logger.warning("Target file %s does not exist; skipping incremental index.", target_path)
            return
        files_to_index = [target_path]
        logger.info("Incremental wiki indexing pass for file: %s (embed=%s)", target_path.name, embed)
    else:
        files_to_index = list(wiki_dir.glob("*.md"))
        logger.info("Full wiki indexing pass for directory: %s (%d files, embed=%s)", wiki_dir, len(files_to_index), embed)

    conn = get_connection(db_path)
    try:
        count = 0
        active_sections = []

        for md_file in files_to_index:
            rel_path = md_file.name
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
                active_sections.append((rel_path, heading))
                section_slug = normalize_slug(heading)
                conn.execute("""
                    INSERT INTO wiki_sections_index (file_path, heading, heading_slug, level, content)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(file_path, heading) DO UPDATE SET
                        heading_slug = excluded.heading_slug,
                        level = excluded.level,
                        embedding = CASE WHEN wiki_sections_index.content = excluded.content THEN wiki_sections_index.embedding ELSE NULL END,
                        content = excluded.content
                """, (rel_path, heading, section_slug, level, section_text))
                count += 1
                file_sections += 1

            logger.debug("Indexed %d sections from %s", file_sections, rel_path)

        # Prune deleted sections: scoped to target file if incremental, or all files if full
        if target_file and files_to_index:
            target_name = files_to_index[0].name
            existing_rows = conn.execute("SELECT heading FROM wiki_sections_index WHERE file_path = ?;", (target_name,)).fetchall()
            active_set = {h for f, h in active_sections if f == target_name}
            to_delete = [(target_name, r[0]) for r in existing_rows if r[0] not in active_set]
            if to_delete:
                conn.executemany("DELETE FROM wiki_sections_index WHERE file_path = ? AND heading = ?", to_delete)
                logger.info("Pruned %d deleted sections from %s", len(to_delete), target_name)
        else:
            existing_rows = conn.execute("SELECT file_path, heading FROM wiki_sections_index;").fetchall()
            active_set = set(active_sections)
            to_delete = [r for r in existing_rows if (r[0], r[1]) not in active_set]
            if to_delete:
                conn.executemany("DELETE FROM wiki_sections_index WHERE file_path = ? AND heading = ?", to_delete)
                logger.info("Pruned %d deleted sections repository-wide", len(to_delete))

        # Synchronize FTS5 external content table cleanly
        logger.debug("Rebuilding FTS5 external content index...")
        conn.execute("INSERT INTO wiki_sections_fts(wiki_sections_fts) VALUES('rebuild');")
        conn.commit()

        # If embedding requested, calculate embeddings for any new or updated sections
        if embed:
            if target_file and files_to_index:
                target_name = files_to_index[0].name
                cursor = conn.execute("SELECT file_path, heading, content FROM wiki_sections_index WHERE file_path = ? AND embedding IS NULL;", (target_name,))
            else:
                cursor = conn.execute("SELECT file_path, heading, content FROM wiki_sections_index WHERE embedding IS NULL;")
            unembedded = cursor.fetchall()
            if unembedded:
                logger.info("[EMBEDDING] Generating vector embeddings for %d new/modified sections using all-MiniLM-L6-v2...", len(unembedded))
                from .search import get_embedding_model
                model = get_embedding_model()
                import numpy as np
                batch_size = 64
                t_emb0 = time.perf_counter()
                for i in range(0, len(unembedded), batch_size):
                    batch = unembedded[i:i + batch_size]
                    texts = [f"{r[1]}: {r[2][:500]}" for r in batch]
                    batch_embs = list(model.embed(texts, batch_size=len(texts)))
                    updates = [
                        (np.array(emb, dtype=np.float32).tobytes(), r[0], r[1])
                        for r, emb in zip(batch, batch_embs)
                    ]
                    conn.executemany(
                        "UPDATE wiki_sections_index SET embedding = ? WHERE file_path = ? AND heading = ?",
                        updates
                    )
                    conn.commit()
                emb_elapsed = time.perf_counter() - t_emb0
                logger.info("[OK] Successfully generated embeddings for %d sections in %.2fs.", len(unembedded), emb_elapsed)
            else:
                logger.debug("[EMBEDDING] All indexed sections have up-to-date embeddings.")
    finally:
        conn.close()

    elapsed_ms = (time.perf_counter() - t0) * 1000
    logger.info("Wiki indexing completed: %d files, %d sections in %.2f ms", len(files_to_index), count, elapsed_ms)
