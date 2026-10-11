"""
sqlite_manager package
Modular database, search, and knowledge graph engine for LLM-Wiki.
"""

from .connection import (
    get_connection,
    init_db,
    truncate_wal,
    snapshot_db,
    logger,
)
from .firehose import (
    ingest_candidates,
    query_firehose_raw,
)
from .indexer import (
    normalize_slug,
    parse_wikilink,
    index_wiki,
)
from .search import (
    get_embedding_model,
    search_keywords,
    search_similarity,
    search_section,
    query_section,
    query_firehose,
    search_hybrid,
    query_hybrid,
)
from .graph import (
    get_backlinks,
    get_related_concepts,
    get_dangling_links,
)
from .cross_linker import (
    build_concept_dictionary,
    scan_and_link_text,
    find_cross_chapter_similarities,
)
from .main import main

__all__ = [
    "get_connection",
    "init_db",
    "truncate_wal",
    "snapshot_db",
    "logger",
    "ingest_candidates",
    "query_firehose_raw",
    "normalize_slug",
    "parse_wikilink",
    "index_wiki",
    "get_embedding_model",
    "search_keywords",
    "search_similarity",
    "search_section",
    "query_section",
    "query_firehose",
    "search_hybrid",
    "query_hybrid",
    "get_backlinks",
    "get_related_concepts",
    "get_dangling_links",
    "build_concept_dictionary",
    "scan_and_link_text",
    "find_cross_chapter_similarities",
    "main",
]
