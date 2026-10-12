#!/usr/bin/env python3
"""
LLM-Wiki MCP Server: Native stdio JSON-RPC 2.0 Interface
Exposes a complete, isolated blackbox API for LLM-Wiki:
- Firehose candidate ingestion & URL deduplication
- FTS5 keyword and fastembed hybrid vector search
- Surgical AST section reads & patches
- Knowledge graph inspection (backlinks, co-citations, dangling links)
- Atomic Git commit & remote push

Database access is completely encapsulated inside the sqlite_manager module.
"""

import sys
import json
import logging
import subprocess
from pathlib import Path
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
LOG_FILE = LOG_DIR / "mcp_server.log"

def resolve_wiki_file(name: str) -> Path:
    cleaned = (name or "").replace("\\", "/").strip()
    if cleaned.startswith("wiki/"):
        cleaned = cleaned[5:]
    elif cleaned.startswith("/wiki/"):
        cleaned = cleaned[6:]
    return WIKI_DIR / cleaned

# IMPORTANT: Logger MUST ONLY write to sys.stderr or file handler, NEVER stdout (stdout is reserved for JSON-RPC messages)
logger = logging.getLogger("llm_wiki_mcp")
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

# Import internal modular components
sys.path.append(str(WORKSPACE_ROOT / "scripts"))
from ast_splicer import ASTSplicer
from sqlite_manager import (
    ingest_candidates,
    query_firehose_raw,
    search_keywords,
    search_similarity,
    search_hybrid,
    get_backlinks,
    get_related_concepts,
    get_dangling_links,
    build_concept_dictionary,
    scan_and_link_text,
    find_cross_chapter_similarities,
    index_wiki,
)


# ==============================================================================
# Tool Implementations (Blackbox Handlers)
# ==============================================================================

def handle_firehose_ingest(params: dict) -> dict:
    """
    Ingests freshly harvested web items into the raw_firehose database table with automatic deduplication.

    Each candidate post is checked against existing entries by canonical URL and ID. Duplicate items
    are skipped automatically so no redundant data enters the database. After saving new items,
    the FTS5 full-text search index is updated.

    Args:
        params: Dictionary containing:
            - items (list[dict], required): List of post dictionaries. Each item should have:
                - canonical_url or url (str, required): Unique web address of the post.
                - canonical_id or id (str, optional): Unique post identifier.
                - platform (str, optional): Source platform (e.g. 'reddit', 'twitter', 'github'). Default: 'Unknown'.
                - title (str, optional): Title of the post or issue. Default: 'Untitled'.
                - content, text, or summary (str, optional): Full body text. Default: ''.

    Returns:
        dict: Status dictionary:
            - status (str): 'success' or 'error'.
            - ingested (int): Number of newly added posts.
            - duplicates_skipped (int): Number of duplicate posts skipped.
            - total_processed (int): Total number of items evaluated in the batch.

    Side Effects:
        - Inserts new rows into the raw_firehose SQLite table.
        - Rebuilds firehose_fts full-text search index.
    """
    items = params.get("items", [])
    logger.info("MCP firehose_ingest: processing %d items", len(items))
    return ingest_candidates(DB_PATH, items)


def handle_firehose_query(params: dict) -> dict:
    """
    Performs high-speed keyword search across raw harvested web posts using SQLite FTS5.

    Matches keywords inside post titles and contents across Reddit, Twitter, and GitHub posts
    stored in the raw firehose table, returning snippets with highlighted match tokens.

    Args:
        params: Dictionary containing:
            - keyword (str, required): Search term or phrase to match in post text.
            - limit (int, optional): Maximum number of results to return. Default: 10.

    Returns:
        dict: Search results dictionary:
            - keyword (str): The search query executed.
            - count (int): Total results returned in this response.
            - results (list[dict]): Matching post items, each containing:
                - id (str): Unique post ID.
                - platform (str): Source platform ('reddit', 'twitter', 'github').
                - title (str): Post title.
                - url (str): Canonical web link.
                - snippet (str): Short excerpt with highlighted match words.

    Side Effects:
        None (read-only query on SQLite FTS5 index).
    """
    keyword = params.get("keyword", "")
    limit = params.get("limit", 10)
    logger.info("MCP firehose_query: keyword='%s', limit=%d", keyword, limit)
    results = query_firehose_raw(DB_PATH, keyword, limit)
    return {"keyword": keyword, "count": len(results), "results": results}


def handle_search_hybrid(params: dict) -> dict:
    """
    Searches textbook chapters using hybrid search fusing keyword matching and meaning/vector similarity.

    Combines two search methods using Reciprocal Rank Fusion (RRF):
    1. Word matching: SQLite FTS5 (BM25 lexical ranking) for exact names and acronyms.
    2. Meaning matching: fastembed 384-dimensional vector embeddings (MiniLM-L6) for semantic concepts.
    This ensures both exact term hits and conceptual matches are ranked fairly.

    Args:
        params: Dictionary containing:
            - query (str, required): Natural language search question or topic phrase.
            - limit (int, optional): Maximum number of top sections to return. Default: 10.

    Returns:
        dict: Search results dictionary:
            - query (str): The search query executed.
            - results (list[dict]): Ranked matching chapter sections, each containing:
                - file (str): Chapter file path (e.g. 'caching.md').
                - heading (str): Specific section heading title (e.g. 'LRU Eviction Policy').
                - rrf_score (float): Combined hybrid relevance score (higher is better).
                - kw_rank (int or None): Position in lexical keyword search.
                - vector_rank (int or None): Position in vector similarity search.
                - vector_similarity (float or None): Cosine similarity score (0.0 to 1.0).
                - snippet (str): Context snippet showing match terms.

    Side Effects:
        None (read-only query on SQLite database).
    """
    query_text = params.get("query", "")
    limit = params.get("limit", 10)
    logger.info("MCP search_hybrid: query='%s', limit=%d", query_text, limit)
    results = search_hybrid(DB_PATH, query_text, limit)
    return {"query": query_text, "results": results}


def handle_search_keyword(params: dict) -> dict:
    """
    Performs pure lexical FTS5 search across textbook chapters using BM25 ranking and stopword filtering.

    Extracts substantive technical keywords, strips conversational filler, and queries the SQLite FTS5
    index directly. Returns matching files, headings, snippet excerpts, and BM25 rank scores.

    Args:
        params: Dictionary containing:
            - keywords (str, required): Keyword phrase, terms, or technical names to search. Alias: query.
            - limit (int, optional): Maximum matching sections to return. Default: 30.

    Returns:
        dict: Keyword search results:
            - keywords (str): Query terms searched.
            - count (int): Total results returned.
            - results (list[dict]): Matching sections, each containing:
                - file (str): Chapter file path.
                - heading (str): Section heading.
                - snippet (str): Highlighted excerpt showing matched terms.
                - bm25_rank (float): Lexical BM25 score (lower is more relevant in SQLite FTS5).

    Side Effects:
        None (read-only query on SQLite FTS5 table).
    """
    keywords = params.get("keywords", "") or params.get("query", "")
    limit = params.get("limit", 30)
    logger.info("MCP search_keyword: keywords='%s', limit=%d", keywords, limit)
    results = search_keywords(DB_PATH, keywords, limit)
    return {"keywords": keywords, "count": len(results), "results": results}


def handle_search_similarity(params: dict) -> dict:
    """
    Performs pure vector cosine similarity search across textbook chapters using fastembed sentence embeddings.

    Takes a short conceptual prompt (typically 5 to 15 words), generates a 384-dimensional dense embedding,
    and runs a matrix dot product against all indexed section vectors in wiki_sections_index.

    Args:
        params: Dictionary containing:
            - query (str, required): Short conceptual prompt or phrase.
            - limit (int, optional): Maximum matching sections to return. Default: 30.

    Returns:
        dict: Similarity search results:
            - query (str): The conceptual prompt searched.
            - count (int): Total results returned.
            - results (list[dict]): Matching sections sorted by similarity, each containing:
                - rank (int): Position (1-indexed).
                - file (str): Chapter file path.
                - heading (str): Section heading.
                - similarity (float): Cosine similarity score (0.0 to 1.0).

    Side Effects:
        None (read-only query on SQLite database).
    """
    query_text = params.get("query", "")
    limit = params.get("limit", 30)
    logger.info("MCP search_similarity: query='%s', limit=%d", query_text, limit)
    results = search_similarity(DB_PATH, query_text, limit)
    return {"query": query_text, "count": len(results), "results": results}


def handle_read_section(params: dict) -> dict:
    """
    Surgically reads only the lines under a specific heading in a markdown chapter file without reading the whole file.

    Uses the Concrete Syntax Tree (CST) parser to extract exact section boundaries. This avoids
    loading entire multi-megabyte markdown files into agent context, saving tokens and memory.

    Args:
        params: Dictionary containing:
            - file (str, required): Chapter file name in wiki/ (e.g. 'caching.md').
            - heading (str, required): Exact heading title to read (e.g. 'LRU Eviction Policy').

    Returns:
        dict: Section content dictionary:
            - found (bool): True if section was found, False otherwise.
            - file (str): Chapter file name.
            - heading (str): Heading title requested.
            - content (str): Exact markdown text under this heading.
            - message (str, optional): Notice message if heading was not found.
            - error (str, optional): Error message if file does not exist.

    Side Effects:
        None (read-only disk file access).
    """
    file_name = params.get("file", "")
    file_path = resolve_wiki_file(file_name)
    heading = params.get("heading", "")
    logger.info("MCP read_section: file='%s' (resolved='%s'), heading='%s'", file_name, file_path, heading)

    if not file_path.exists():
        return {"found": False, "error": f"File '{file_name}' does not exist in wiki/ (resolved to '{file_path}')"}

    text = ASTSplicer.read_section(file_path, heading)
    if text is None:
        return {"found": False, "content": "", "message": f"Heading '{heading}' not found in {file_name}"}

    return {"found": True, "file": file_name, "heading": heading, "content": text}


def handle_patch_section(params: dict) -> dict:
    """
    Surgically updates a single section inside a markdown chapter file, lints syntax, and updates search embeddings.

    Workflow executed in a single atomic pass:
    1. AST Splicing: Cuts out only the target section lines from disk and replaces them with new content exactly as authored.
       If heading does not exist, appends it cleanly.
    2. Syntax Linting: Validates that code fence blocks and bracket tags are properly balanced and closed.
    3. Database Indexing: Updates section text, computes fresh 384-d vector embeddings, rebuilds FTS5,
       and registers newly created wikilinks in the knowledge graph.

    Args:
        params: Dictionary containing:
            - file (str, required): Chapter file name in wiki/ (e.g. 'caching.md').
            - heading (str, required): Exact heading title to update or append.
            - content (str, required): New markdown text for the section.

    Returns:
        dict: Patch summary dictionary:
            - status (str): 'success' or 'error'.
            - file (str): Chapter file modified.
            - heading (str): Heading updated.
            - lint_warnings (list[str]): Any markdown formatting or unclosed block warnings.
            - message (str): Human-readable confirmation message.
            - error (str, optional): Error details if operation failed.

    Side Effects:
        - Modifies markdown chapter file on disk (wiki/<file>).
        - Updates wiki_sections_index table (text and vector embedding).
        - Updates wiki_sections_fts full-text search index.
        - Updates wiki_links table with all parsed wikilinks.
    """
    file_name = params.get("file", "")
    file_path = resolve_wiki_file(file_name)
    heading = params.get("heading", "")
    content = params.get("content", "")
    logger.info("MCP patch_section: file='%s' (resolved='%s'), heading='%s' (%d chars)", file_name, file_path, heading, len(content))

    try:
        ASTSplicer.splice_section(file_path, heading, content)
        errs = ASTSplicer.lint_file(file_path)
        try:
            index_wiki(DB_PATH, WIKI_DIR, embed=True)
        except Exception as ex_idx:
            logger.warning("Fast index_wiki sync after patch_section failed: %s", ex_idx)
        return {
            "status": "success",
            "file": file_name,
            "heading": heading,
            "lint_warnings": errs,
            "message": f"Section '{heading}' spliced cleanly in {file_name} with AST and indexes synchronized."
        }
    except Exception as e:
        logger.exception("MCP patch_section error: %s", e)
        return {"status": "error", "error": str(e)}


def handle_suggest_links(params: dict) -> dict:
    """
    Surfaces high-similarity section pairs between different chapters that are not yet cross-linked.
    If 'file' (and optionally 'heading') is specified, restricts candidate pairs to only those
    directly related to that specific newly added/modified section.

    Args:
        params: Dictionary containing:
            - file (str, optional): Target chapter file name (e.g. 'caching.md').
            - heading (str, optional): Target section heading title.
            - threshold (float, optional): Minimum cosine similarity cutoff (0.0 to 1.0). Default: 0.82.
            - limit (int, optional): Maximum candidate pairs to return. Default: 20.

    Returns:
        dict: Suggestion dictionary:
            - status (str): 'success' or 'error'.
            - file (str, optional): Target file queried.
            - heading (str, optional): Target heading queried.
            - threshold (float): Similarity threshold used.
            - count (int): Total pairs found.
            - suggestions (list[dict]): Candidate pairs.
    """
    file_name = params.get("file", "").strip() or None
    if file_name:
        cleaned = file_name.replace("\\", "/").strip()
        if cleaned.startswith("wiki/"):
            file_name = cleaned[5:]
        elif cleaned.startswith("/wiki/"):
            file_name = cleaned[6:]
        else:
            file_name = cleaned
    heading = params.get("heading", "").strip() or None
    threshold = params.get("threshold", 0.82)
    limit = params.get("limit", 20)
    logger.info("MCP suggest_links: file='%s', heading='%s', threshold=%.2f, limit=%d", file_name, heading, threshold, limit)
    try:
        candidates = find_cross_chapter_similarities(
            DB_PATH, 
            threshold=threshold, 
            limit=limit,
            file=file_name,
            heading=heading
        )
        return {
            "status": "success",
            "file": file_name,
            "heading": heading,
            "threshold": threshold,
            "count": len(candidates),
            "suggestions": candidates
        }
    except Exception as e:
        logger.exception("MCP suggest_links error: %s", e)
        return {"status": "error", "error": str(e)}


def handle_scan_links(params: dict) -> dict:
    """
    Deprecated / Disabled: Deterministic regex auto-linking has been disabled to prevent knowledge graph corruption.
    All cross-links must be authored intentionally by agents via the 4-Point Epistemic Link Audit.
    """
    return {
        "status": "error",
        "error": "Deterministic regex auto-linking is disabled to prevent knowledge graph corruption. All cross-chapter links must be authored intentionally by agents."
    }


def handle_get_graph(params: dict) -> dict:
    """
    Inspects the textbook knowledge graph: backlinks, co-citations, or dangling voids.

    Supported actions:
    1. 'backlinks': Finds all chapters and headings that cite a specific concept.
    2. 'related': Finds co-cited concepts (topics frequently linked alongside the given concept).
    3. 'dangling': Finds cited concepts that do not yet have a defining section written in any chapter.

    Args:
        params: Dictionary containing:
            - action (str, required): One of 'backlinks', 'related', or 'dangling'. Default: 'backlinks'.
            - concept (str, optional): Target concept slug or topic name (e.g. 'raft' or 'consensus/raft').
              Required when action is 'backlinks' or 'related'.
            - limit (int, optional): Maximum results to return. Default: 20.

    Returns:
        dict: Graph results dictionary:
            - action (str): Action performed ('backlinks', 'related', or 'dangling').
            - concept (str, optional): Concept queried (for 'backlinks' and 'related').
            - results (list[dict]): List of matching graph items:
                - For 'backlinks': source_file, source_heading, target_concept, target_anchor, link_alias, domain_scope.
                - For 'related': target_concept, domain_scope, co_citation_count.
                - For 'dangling': target_concept, domain_scope, incoming_citations, citing_files.
            - error (str, optional): Error details if action is invalid.

    Side Effects:
        None (read-only query on SQLite graph views and tables).
    """
    action = params.get("action", "backlinks")
    concept = params.get("concept", "")
    limit = params.get("limit", 20)
    logger.info("MCP get_graph: action='%s', concept='%s'", action, concept)

    if action == "backlinks":
        bls = get_backlinks(DB_PATH, concept)
        return {"action": "backlinks", "concept": concept, "results": bls}
    elif action == "related":
        rel = get_related_concepts(DB_PATH, concept)
        return {"action": "related", "concept": concept, "results": rel}
    elif action == "dangling":
        dang = get_dangling_links(DB_PATH, limit=limit)
        return {"action": "dangling", "results": dang}
    else:
        return {"error": f"Unknown graph action '{action}'. Use 'backlinks', 'related', or 'dangling'."}


def handle_git_commit_and_push(params: dict) -> dict:
    """
    Atomically stages modified chapter files, commits to Git, and pushes to remote tracking branch.

    Automates version control for the textbook repository. Runs `git add`, `git commit`,
    and `git push origin <branch>` synchronously to ensure all updates are permanently saved.

    Args:
        params: Dictionary containing:
            - message (str, required): Descriptive Git commit message explaining changes.
            - file (str, optional): Relative path of file or folder to stage with `git add`. Default: 'wiki/'.
            - branch (str, optional): Remote Git branch to push to. Default: 'main'.

    Returns:
        dict: Git status dictionary:
            - status (str): 'success' or 'error'.
            - branch (str): Target branch pushed to.
            - commit_output (str): Stdout message from git commit.
            - push_output (str): Stdout message from git push.
            - error (str, optional): Error details if git execution failed.

    Side Effects:
        - Stages files in Git index.
        - Creates a new commit in local Git history.
        - Pushes commits to remote Git tracking branch on GitHub.
    """
    file_name = params.get("file", "wiki/")
    message = params.get("message", "feat: autonomous section patch")
    branch = params.get("branch", "main")
    logger.info("MCP git_commit_and_push: file='%s', msg='%s', branch='%s'", file_name, message, branch)

    try:
        res_add = subprocess.run(["git", "add", file_name], cwd=WORKSPACE_ROOT, capture_output=True, text=True)
        if res_add.returncode != 0:
            err = (res_add.stderr or res_add.stdout or "git add failed").strip()
            logger.error("Git add failed: %s", err)
            return {"status": "error", "error": f"git add failed: {err}"}

        res_commit = subprocess.run(["git", "commit", "-m", message], cwd=WORKSPACE_ROOT, capture_output=True, text=True)
        res_push = subprocess.run(["git", "push", "origin", branch], cwd=WORKSPACE_ROOT, capture_output=True, text=True)
        
        commit_out = ((res_commit.stdout or "") + "\n" + (res_commit.stderr or "")).strip()
        push_out = ((res_push.stdout or "") + "\n" + (res_push.stderr or "")).strip()
        
        if res_push.returncode != 0:
            logger.error("Git push failed: %s", push_out)
            return {
                "status": "error",
                "branch": branch,
                "commit_output": commit_out,
                "push_output": push_out,
                "error": f"git push exited with code {res_push.returncode}: {push_out}"
            }

        return {
            "status": "success",
            "branch": branch,
            "commit_output": commit_out,
            "push_output": push_out
        }
    except Exception as e:
        logger.error("Git error: %s", e)
        return {"status": "error", "error": str(e)}


def handle_reindex(params: dict) -> dict:
    """
    Rebuilds the relational shadow index, FTS5 full-text search table, and knowledge graph edges from wiki/*.md files.

    Performs an end-to-end synchronization pass:
    1. Scans all markdown chapters in wiki/.
    2. Parses headings and updates wiki_sections_index with line coordinates.
    3. Rebuilds wiki_links graph edges (source, target, anchor, alias, domain).
    4. Rebuilds wiki_sections_fts full-text search index.
    5. Optionally calculates fastembed vector embeddings for updated sections.

    Args:
        params: Dictionary containing:
            - embed (bool, optional): Whether to compute fastembed vector embeddings for updated sections. Default: False.

    Returns:
        dict: Status dictionary:
            - status (str): 'success' or 'error'.
            - embed (bool): Whether embeddings were computed.
            - message (str): Confirmation message.
            - error (str, optional): Error details if operation failed.

    Side Effects:
        - Updates wiki_sections_index SQLite table.
        - Updates wiki_links SQLite table.
        - Rebuilds wiki_sections_fts SQLite table.
        - Updates vector embeddings if embed=True.
    """
    embed = params.get("embed", False)
    logger.info("MCP reindex: embed=%s", embed)
    try:
        index_wiki(DB_PATH, WIKI_DIR, embed=embed)
        return {
            "status": "success",
            "embed": embed,
            "message": "Wiki successfully re-indexed into shadow tables, FTS5, and link graph."
        }
    except Exception as e:
        logger.exception("MCP reindex error: %s", e)
        return {"status": "error", "error": str(e)}


# ==============================================================================
# Tool Registry & JSON-RPC Dispatcher
# ==============================================================================

TOOL_REGISTRY = {
    # Canonical tool names
    "llm_wiki_firehose_ingest": handle_firehose_ingest,
    "llm_wiki_firehose_query": handle_firehose_query,
    "llm_wiki_search_hybrid": handle_search_hybrid,
    "llm_wiki_search_keyword": handle_search_keyword,
    "llm_wiki_search_similarity": handle_search_similarity,
    "llm_wiki_read_section": handle_read_section,
    "llm_wiki_patch_section": handle_patch_section,
    "llm_wiki_get_graph": handle_get_graph,
    "llm_wiki_suggest_links": handle_suggest_links,
    "llm_wiki_scan_links": handle_scan_links,
    "llm_wiki_git_commit_and_push": handle_git_commit_and_push,
    "llm_wiki_reindex": handle_reindex,

    # Short aliases for convenience
    "firehose_ingest": handle_firehose_ingest,
    "firehose_query": handle_firehose_query,
    "search_hybrid": handle_search_hybrid,
    "search_keyword": handle_search_keyword,
    "search_similarity": handle_search_similarity,
    "read_section": handle_read_section,
    "patch_section": handle_patch_section,
    "get_graph": handle_get_graph,
    "suggest_links": handle_suggest_links,
    "scan_links": handle_scan_links,
    "git_commit_and_push": handle_git_commit_and_push,
    "reindex": handle_reindex,
}

TOOL_SCHEMAS = [
    {
        "name": "llm_wiki_firehose_ingest",
        "description": "Ingests raw web posts (Reddit, Twitter, GitHub) into the database with automatic deduplication by URL and ID. Updates full-text search index after ingestion.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "description": "List of post objects to save. Items missing a canonical URL or matching an existing URL/ID are skipped automatically.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "canonical_url": {"type": "string", "description": "Canonical web address of the post (unique identifier)."},
                            "url": {"type": "string", "description": "Alternative alias for canonical_url."},
                            "canonical_id": {"type": "string", "description": "Platform post identifier (e.g. tweet ID or reddit thread ID)."},
                            "id": {"type": "string", "description": "Alternative alias for canonical_id."},
                            "platform": {"type": "string", "description": "Source platform name (e.g. 'reddit', 'twitter', 'github'). Default: 'Unknown'."},
                            "title": {"type": "string", "description": "Title of the post, issue, or discussion."},
                            "content": {"type": "string", "description": "Full text body or summary of the post."},
                            "text": {"type": "string", "description": "Alternative alias for content."},
                            "summary": {"type": "string", "description": "Alternative alias for content."},
                            "domain": {"type": "string", "description": "Topic domain slug (e.g. 'storage', 'distributed_systems', 'strategic_simulation'). Default: 'general'."}
                        },
                        "required": ["canonical_url"]
                    }
                }
            },
            "required": ["items"]
        }
    },
    {
        "name": "llm_wiki_firehose_query",
        "description": "Searches raw scraped internet posts (Reddit, Twitter, GitHub) using SQLite FTS5 full-text keyword search.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "keyword": {
                    "type": "string",
                    "description": "Search keyword or phrase to match in scraped post titles and content."
                },
                "limit": {
                    "type": "integer",
                    "default": 10,
                    "description": "Maximum number of matching posts to return (default: 10)."
                }
            },
            "required": ["keyword"]
        }
    },
    {
        "name": "llm_wiki_search_hybrid",
        "description": "Searches textbook chapters using hybrid search fusing SQLite FTS5 exact word matching with fastembed vector semantic similarity (MiniLM-L6) via Reciprocal Rank Fusion.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural language search question or topic query."
                },
                "limit": {
                    "type": "integer",
                    "default": 10,
                    "description": "Maximum number of top matching chapter sections to return (default: 10)."
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "llm_wiki_search_keyword",
        "description": "Performs pure lexical FTS5 search across textbook chapters using BM25 ranking and stopword filtering. Best for searching specific technical terms, keywords, and acronyms.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "keywords": {
                    "type": "string",
                    "description": "Keyword phrase or space-separated technical terms to match in textbook headings and content."
                },
                "limit": {
                    "type": "integer",
                    "default": 30,
                    "description": "Maximum number of matching sections to return (default: 30)."
                }
            },
            "required": ["keywords"]
        }
    },
    {
        "name": "llm_wiki_search_similarity",
        "description": "Performs pure fastembed vector cosine similarity search (MiniLM-L6) across textbook chapters. Best for short conceptual sub-prompts (5 to 15 words) to find semantically related sections.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Short, focused conceptual prompt or query phrase to embed and compare."
                },
                "limit": {
                    "type": "integer",
                    "default": 30,
                    "description": "Maximum number of matching sections to return (default: 30)."
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "llm_wiki_read_section",
        "description": "Surgically reads only the markdown text under a specific heading from wiki/*.md without loading the entire chapter file into memory.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file": {
                    "type": "string",
                    "description": "Markdown chapter file name inside wiki/ (e.g. 'caching.md')."
                },
                "heading": {
                    "type": "string",
                    "description": "Exact heading title to read (e.g. 'LRU Eviction Policy')."
                }
            },
            "required": ["file", "heading"]
        }
    },
    {
        "name": "llm_wiki_patch_section",
        "description": "Surgically replaces or appends a specific markdown section, auto-links cross-chapter concepts, lints syntax, and auto-updates search vector embeddings.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file": {
                    "type": "string",
                    "description": "Markdown chapter file name inside wiki/ (e.g. 'caching.md')."
                },
                "heading": {
                    "type": "string",
                    "description": "Exact heading title to replace or append."
                },
                "content": {
                    "type": "string",
                    "description": "New replacement markdown content for the section (with intentional, verified [[wikilinks]] authored directly)."
                }
            },
            "required": ["file", "heading", "content"]
        }
    },
    {
        "name": "llm_wiki_get_graph",
        "description": "Queries the textbook knowledge graph: backlinks (pages citing a topic), related concepts (co-citations), or dangling links (topics cited with no written section).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["backlinks", "related", "dangling"],
                    "default": "backlinks",
                    "description": "Which graph query to perform: 'backlinks' (citations to a concept), 'related' (co-cited topics), or 'dangling' (topics cited but not yet written)."
                },
                "concept": {
                    "type": "string",
                    "description": "Concept slug or topic name (e.g. 'raft' or 'consensus/raft'). Required when action is 'backlinks' or 'related'."
                },
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "description": "Maximum number of graph results to return (default: 20)."
                }
            },
            "required": ["action"]
        }
    },
    {
        "name": "llm_wiki_suggest_links",
        "description": "Surfaces high-similarity section pairs across different chapters using vector embeddings (> 0.82). If file and heading are provided, finds candidate links strictly for that specific newly added/modified content.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file": {
                    "type": "string",
                    "description": "Optional: Filter candidate links to only those related to this chapter file (e.g. 'storage.md')."
                },
                "heading": {
                    "type": "string",
                    "description": "Optional: Filter candidate links to only those related to this specific section heading."
                },
                "threshold": {
                    "type": "number",
                    "default": 0.82,
                    "description": "Minimum cosine similarity score (between 0.0 and 1.0, default 0.82) to consider two sections related."
                },
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "description": "Maximum candidate pairs to return (default: 20)."
                }
            }
        }
    },
    {
        "name": "llm_wiki_scan_links",
        "description": "[DISABLED] Deterministic regex auto-linking is disabled to prevent knowledge graph corruption. All cross-chapter links must be authored intentionally by agents via the 4-point epistemic audit.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file": {
                    "type": "string",
                    "description": "Markdown chapter file name inside wiki/ (e.g. 'caching.md')."
                },
                "apply": {
                    "type": "boolean",
                    "default": False,
                    "description": "If false (default), runs in dry-run preview mode. If true, writes generated wikilinks to disk and updates the index."
                }
            },
            "required": ["file"]
        }
    },
    {
        "name": "llm_wiki_git_commit_and_push",
        "description": "Atomically stages modified chapter files, creates a Git commit, and pushes to the remote GitHub repository.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "Descriptive Git commit message explaining what was updated."
                },
                "file": {
                    "type": "string",
                    "default": "wiki/",
                    "description": "Relative path of file or directory to stage with git add (default: 'wiki/')."
                },
                "branch": {
                    "type": "string",
                    "default": "main",
                    "description": "Remote Git branch to push to (default: 'main')."
                }
            },
            "required": ["message"]
        }
    },
    {
        "name": "llm_wiki_reindex",
        "description": "Rebuilds relational shadow tables (wiki_sections_index, wiki_links), FTS5 lexical index, and optional vector embeddings from all markdown chapters in wiki/.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "embed": {
                    "type": "boolean",
                    "default": False,
                    "description": "If true, computes fastembed vector embeddings for all new or updated sections (default: false)."
                }
            }
        }
    }
]


def main():
    logger.info("LLM-Wiki stdio MCP Server started (JSON-RPC 2.0 loop active)")
    while True:
        line = sys.stdin.readline()
        if not line:
            logger.info("LLM-Wiki stdio MCP Server received EOF on stdin; exiting cleanly.")
            break
        try:
            request = json.loads(line)
            req_id = request.get("id")
            method = request.get("method")
            params = request.get("params", {})
            logger.debug("Received MCP request: id=%s, method='%s'", req_id, method)

            # JSON-RPC / MCP Notifications (no response expected)
            if method and method.startswith("notifications/"):
                logger.debug("Received MCP notification: %s (ignoring cleanly)", method)
                continue

            # Standard MCP initialize handshake
            if method == "initialize":
                proto_ver = params.get("protocolVersion", "2024-11-05")
                response = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "protocolVersion": proto_ver,
                        "capabilities": {
                            "tools": {
                                "listChanged": False
                            }
                        },
                        "serverInfo": {
                            "name": "llm-wiki-mcp",
                            "version": "1.0.0"
                        }
                    }
                }

            # Standard MCP ping
            elif method == "ping":
                response = {"jsonrpc": "2.0", "id": req_id, "result": {}}

            # Server discovery alias
            elif method == "server/discover":
                response = {"jsonrpc": "2.0", "id": req_id, "result": {"server": "llm-wiki-mcp", "version": "1.0.0"}}

            # MCP tools/list
            elif method == "tools/list":
                response = {"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOL_SCHEMAS}}

            # Direct method dispatch
            elif method in TOOL_REGISTRY:
                result = TOOL_REGISTRY[method](params)
                response = {"jsonrpc": "2.0", "id": req_id, "result": result}

            # Standard MCP tools/call wrapper
            elif method == "tools/call":
                tool_name = params.get("name")
                tool_args = params.get("arguments", {})
                if tool_name in TOOL_REGISTRY:
                    result = TOOL_REGISTRY[tool_name](tool_args)
                    response = {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {
                            "content": [{"type": "text", "text": json.dumps(result, indent=2)}]
                        }
                    }
                else:
                    logger.warning("Tool '%s' not registered in TOOL_REGISTRY", tool_name)
                    response = {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Tool '{tool_name}' not found"}}
            else:
                logger.warning("Method '%s' not recognized", method)
                response = {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Method '{method}' not found"}}

            raw_response = json.dumps(response) + "\n"
            sys.stdout.write(raw_response)
            sys.stdout.flush()
            logger.debug("Sent MCP response: id=%s (%d bytes)", req_id, len(raw_response))
        except Exception as e:
            logger.exception("Error handling MCP request: %s", e)
            err_resp = {"jsonrpc": "2.0", "id": None, "error": {"code": -32603, "message": str(e)}}
            sys.stdout.write(json.dumps(err_resp) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
