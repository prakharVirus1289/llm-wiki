#!/usr/bin/env python3
"""
Wiki Markdown Indexer & AST Section Parser
Parses Markdown files into headings, extracts [[wikilinks]], rebuilds FTS5, and manages embeddings.
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


def index_wiki(db_path: Path, wiki_dir: Path, embed: bool = False):
    """Indexes all Markdown files in wiki_dir into SQLite FTS5 and topological wiki_links graph."""
    init_db(db_path)
    logger.info("Starting wiki indexing pass for directory: %s (embed=%s)", wiki_dir, embed)
    t0 = time.perf_counter()
    heading_regex = re.compile(r'^(#{1,6})\s+(.+)$', re.MULTILINE)
    # Support [[target#anchor|alias]] or [[domain/concept#anchor|alias]]
    wikilink_regex = re.compile(r'\[\[([^\]#|]+)(?:#([^\]|]+))?(?:\|([^\]]+))?\]\]')
    
    conn = get_connection(db_path)
    try:
        # Clear existing graph links to refresh topological edges
        conn.execute("DELETE FROM wiki_links;")
        
        count = 0
        link_count = 0
        active_sections = []
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
                
                # Extract [[wikilinks]] with slug normalization, anchors, aliases, and domain scoping
                # Mask fenced code blocks and inline code backticks so code examples are not indexed as graph edges
                text_without_code = re.sub(r'```[\s\S]*?```', '', section_text)
                text_without_code = re.sub(r'`[^`\n]+`', '', text_without_code)
                for wl in wikilink_regex.finditer(text_without_code):
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

        # Prune deleted sections
        existing_rows = conn.execute("SELECT file_path, heading FROM wiki_sections_index;").fetchall()
        active_set = set(active_sections)
        to_delete = [r for r in existing_rows if (r[0], r[1]) not in active_set]
        if to_delete:
            conn.executemany("DELETE FROM wiki_sections_index WHERE file_path = ? AND heading = ?", to_delete)
                        
        # Synchronize FTS5 external content table cleanly
        logger.debug("Rebuilding FTS5 external content index...")
        conn.execute("INSERT INTO wiki_sections_fts(wiki_sections_fts) VALUES('rebuild');")
        conn.commit()

        # If embedding requested, calculate embeddings for any new or updated sections
        if embed:
            cursor = conn.execute("SELECT file_path, heading, content FROM wiki_sections_index WHERE embedding IS NULL;")
            unembedded = cursor.fetchall()
            if unembedded:
                print(f"[EMBEDDING] Generating vector embeddings for {len(unembedded)} new/modified sections using all-MiniLM-L6-v2...")
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
                print(f"[OK] Successfully generated embeddings for {len(unembedded)} sections in {emb_elapsed:.2f}s.")
            else:
                print("[EMBEDDING] All sections already have up-to-date embeddings.")
    finally:
        conn.close()
    elapsed_ms = (time.perf_counter() - t0) * 1000
    logger.info("Wiki indexing completed: %d sections, %d graph edges in %.2f ms", count, link_count, elapsed_ms)
    print(f"[OK] Indexed {count} sections and {link_count} graph edges into SQLite FTS5 & wiki_links.")
