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
from .indexer import (
    normalize_slug,
    parse_wikilink,
    index_wiki,
)
from .search import (
    get_embedding_model,
    query_section,
    query_firehose,
    query_hybrid,
)
from .graph import (
    get_backlinks,
    get_related_concepts,
    get_dangling_links,
)
from .main import main

__all__ = [
    "get_connection",
    "init_db",
    "truncate_wal",
    "snapshot_db",
    "logger",
    "normalize_slug",
    "parse_wikilink",
    "index_wiki",
    "get_embedding_model",
    "query_section",
    "query_firehose",
    "query_hybrid",
    "get_backlinks",
    "get_related_concepts",
    "get_dangling_links",
    "main",
]
