# LLM-Wiki Skills Reference Guide

*A plain-language guide to every skill used in the living textbook research and `[[wikilinks]]` knowledge graph.*

---

## Overview

The **LLM-Wiki** system is an autonomous research engine and living technical textbook. Instead of keeping information trapped in chat history or unstructured text dumps, the system continuously harvests real-world implementations, filters out social media noise, and compiles battle-tested knowledge into structured Markdown chapters linked together with `[[wikilinks]]`.

To do this reliably without human micro-management, eight specialized **skills** collaborate in a closed loop. Below is a complete breakdown of each skill: its purpose, inputs, outputs, step-by-step logic, and how it handles wikilinks.

---

## 1. `deep-web-analysis` — The Research Engine Orchestrator

* **Skill Folder:** [`C:\Users\ASUS\.agents\skills\deep-web-analysis\`](file:///C:/Users/ASUS/.agents/skills/deep-web-analysis/SKILL.md)
* **Purpose (In Simple Terms):** 
  The project manager. It takes your research question, sets up a fresh workspace, coordinates the scraping of hundreds of posts across the web, triggers the filtering and textbook writing tools, and manages recurring timer cycles.

### Inputs:
* **`prompt` (Required):** The exact research question or objective (e.g. *"Cognitive frameworks for mental simulation"*).
* **`time_interval` (Optional):** How often to repeat the research (e.g. `15m`, `1h`, or cron expression).
* **`end_time` (Optional):** When to stop recurring cycles (evaluated in local Indian Standard Time - IST).

### Outputs:
* A fresh workspace directory (`Documents/deep-web-analysis/Research_<TopicSlug>/`).
* Raw candidate dump (`harvested_candidates.json`) containing $\ge 150$ multi-platform posts per cycle.
* Timestamped cycle digest reports in `reports/report_YYYY-MM-DD_HH-MM.md`.

### Step-by-Step Logic:
1. **Initialize Workspace:** Creates a dedicated research folder with `research_config.json` and an empty `query_manifest.json`.
2. **Generate Queries:** Calls `iterative-query-gen` to fill `query_manifest.json` with platform-specific search terms.
3. **Harvest Web Data:** Runs the harvester script (`runner.py`) across Reddit, Hacker News, Twitter/X, Lobsters, GitHub, and ArXiv, collecting at least 150 candidates.
4. **Filter Raw Posts:** Calls `filtering-raw-dump` to eliminate fluff and stage approved technical posts into the central database.
5. **Promote to Textbook:** Calls `wiki-reader` and `ast-markdown-patcher` to turn approved findings into textbook sections.
6. **Schedule Next Cycle:** If recurring mode was chosen, schedules a background timer to repeat the process until `end_time`.

### Interaction with `[[wikilinks]]`:
* Coordinates the promotion phase so that synthesized chapters reference other chapters via `[[chapter/slug|alias]]`.

---

## 2. `filtering-raw-dump` — The Noise Filter & Gatekeeper

* **Skill Folder:** [`C:\Users\ASUS\.agents\skills\filtering-raw-dump\`](file:///C:/Users/ASUS/.agents/skills/filtering-raw-dump/SKILL.md)
* **Purpose (In Simple Terms):** 
  The quality gatekeeper. Raw web scrapes are full of marketing fluff, beginner tutorials, lifestyle blogs ("how to wake up at 5 AM"), and generic chatter. This skill reads every scraped item and aggressively discards anything that isn't concrete, actionable engineering or strategic knowledge.

### Inputs:
* **`candidates_path` (Required):** Path to the raw JSON file of scraped posts (`harvested_candidates.json`).
* **`parent_prompt` (Required):** The user's core research objective, used as the benchmark for relevance.

### Outputs:
* **`approved_candidates`:** A vetted list of high-signal items that passed all evaluation checks.
* **Database Ingestion:** Automatically stages approved items into the central SQLite table (`raw_firehose`) via the Model Context Protocol (MCP) tool `llm_wiki_firehose_ingest`, stripping tracking parameters and skipping duplicate URLs.

### Step-by-Step Logic:
1. **Load Candidates:** Opens and parses `harvested_candidates.json`.
2. **Apply the 4-Point Adversarial Filter:**
   * *Point 1 (Direct Alignment):* Does this post directly address the user's core problem? (If it is generic advice or consumer note-taking app chatter $\rightarrow$ **Reject**).
   * *Point 2 (Technical Concreteness):* Does it provide code, a concrete failure post-mortem, quantitative metrics, or a formal model? (If vague fluff $\rightarrow$ **Reject**).
   * *Point 3 (Non-Triviality):* Does it provide an insight beyond basic common sense? (If beginner level $\rightarrow$ **Reject**).
   * *Point 4 (Actionability):* Can an engineer or founder act on or build with this information right now? (If purely speculative $\rightarrow$ **Reject**).
3. **Ingest via MCP:** Sends the approved items to `llm_wiki_firehose_ingest`. The server cleans tracking tags (`utm_*`, `ref`) and saves only unique rows into `raw_firehose.db`.

### Interaction with `[[wikilinks]]`:
* Prepares clean data for downstream skills so that only substantive concepts ever become candidates for `[[wikilinks]]`.

---

## 3. `wiki-reader` — The Surgical Knowledge Reader

* **Skill Folder:** [`C:\Users\ASUS\.agents\skills\wiki-reader\`](file:///C:/Users/ASUS/.agents/skills/wiki-reader/SKILL.md)
* **Purpose (In Simple Terms):** 
  The precision search and retrieval tool. It searches the existing textbook chapters to find where concepts are discussed, reads only the exact paragraphs needed (without loading giant 500-line files into memory), and follows existing `[[wikilinks]]` to related chapters.

### Inputs:
* **`parent_prompt` (Required):** The research topic or question to look up in the textbook.

### Outputs:
* Structured JSON with:
  * **`direct_findings`:** Full, unedited text of sections found directly through keyword and semantic search.
  * **`linked_findings`:** Full, unedited text of destination sections discovered by following existing `[[wikilinks]]`.

### Step-by-Step Logic:
1. **Prompt Decomposition:** Splits the parent prompt into two tracks:
   * *Semantic Phrases:* 2 to 4 short concept phrases (e.g. *"SQLite WAL reader snapshot pinning"*).
   * *Keyword Terms:* Exact technical names and acronyms (e.g. `BEGIN IMMEDIATE`, `PRAGMA wal_autocheckpoint`).
2. **Dual-Track Search:** Queries the textbook using two MCP tools:
   * `llm_wiki_search_similarity` (finds conceptually similar sections).
   * `llm_wiki_search_keyword` (finds exact keyword matches via SQLite FTS5).
3. **Surgical Section Reading:** For each matching section, calls `llm_wiki_read_section(file, heading)` to extract only that section's text. Loading entire files is strictly prohibited to save AI memory and prevent confusion.
4. **Follow Wikilinks Directly:** Scans the retrieved section for all `[[wikilinks]]`. For every link found, calls `llm_wiki_read_section` on the linked chapter and section. It trusts existing links without re-vetting them, gathering the complete surrounding context.

### Interaction with `[[wikilinks]]`:
* Reads existing `[[chapter/slug|alias]]` links inside sections and automatically traverses them to pull in 1-hop connected knowledge.

---

## 4. `ast-markdown-patcher` — The Surgical Writer & Link Weaver

* **Skill Folder:** [`C:\Users\ASUS\.agents\skills\ast-markdown-patcher\`](file:///C:/Users/ASUS/.agents/skills/ast-markdown-patcher/SKILL.md)
* **Purpose (In Simple Terms):** 
  The surgical editor. When new knowledge needs to be added to a chapter, this skill replaces or appends only that specific section using exact byte coordinates. It validates CommonMark syntax (preventing unclosed code fences or broken brackets), weaves verified `[[wikilinks]]`, and immediately pushes the update to GitHub.

### Inputs:
* **`file` (Required):** The target chapter file (e.g. `evaluations.md` or `storage.md`).
* **`heading` (Required):** The exact section heading to create or update.
* **`content` (Required):** The complete markdown text for that section.
* **`commit_message` (Optional):** A clear Git commit message explaining the change.

### Outputs:
* Modified chapter file on disk (`wiki/<file>`).
* Incremental update to SQLite shadow tables (`wiki_sections_index`, `wiki_sections_fts`, `wiki_links`).
* Fresh 384-dimensional vector embeddings generated for the modified section.
* Immediate atomic remote Git commit and push to `origin/main`.

### Step-by-Step Logic:
1. **Read-Before-Write:** Reads the existing section via `llm_wiki_read_section` to verify current claims and avoid duplicate text.
2. **Surgical Splice:** Calls `llm_wiki_patch_section`. The server uses a Concrete Syntax Tree (CST) parser to cut out only the target section's bytes and splice in the new text, leaving the rest of the file 100% byte-identical. The indexer incrementally re-indexes only this single modified file.
3. **Syntax Validation:** Checks that all code blocks (```` ``` ````) and brackets are balanced.
4. **Cross-Link Discovery:** Calls `llm_wiki_suggest_links(file, heading)` to find other chapters that discuss related ideas.
5. **5-Point Epistemic Link Audit:** Vets suggested link pairs:
   * *Point 1 (Causal Dependency):* Does one concept directly configure, rely on, or solve an issue described in the other? (Buzzword matches $\rightarrow$ **Reject**).
   * *Point 2 (Permanent Target):* Is the target an existing, permanent chapter section?
   * *Point 3 (Substantive Names):* Does it link a specific named mechanism rather than casual text?
   * *Point 4 (Explicit 1-Sentence Rationale):* The agent formulates a mandatory single sentence explaining *why* the connection exists.
   * *Point 5 (Cross-Domain Metaphor Ban):* Strictly bans linking across different engineering or discipline boundaries based on loose metaphors (e.g., no linking software lock contention to human company disputes).
6. **Weave Wikilinks & Register with Rationale:** Slices the verified `[[wikilinks]]` into the text via `llm_wiki_patch_section`, and immediately calls `llm_wiki_register_link` to store the link edge along with its 1-sentence rationale in the SQLite database.
7. **Atomic Remote Push:** Calls `llm_wiki_git_commit_and_push` to commit and push the updated chapter directly to GitHub.

### Interaction with `[[wikilinks]]`:
* It is the **primary creator and validator of `[[wikilinks]]`**. It audits each link against the 5-Point Audit, writes the link text into markdown, and explicitly registers the edge and its rationale in the SQLite `wiki_links` table via `llm_wiki_register_link`. The database graph is never populated mechanically by regex scanners.

---

## 5. `iterative-query-gen` — The Search Query Strategist

* **Skill Folder:** [`C:\Users\ASUS\.agents\skills\iterative-query-gen\`](file:///C:/Users/ASUS/.agents/skills/iterative-query-gen/SKILL.md)
* **Purpose (In Simple Terms):** 
  The research strategist. After each research cycle, it looks at what is already written in the textbook, finds what is still missing (knowledge voids or missing failure modes), and formulates targeted search queries for each platform's native dialect.

### Inputs:
* **`parent_prompt` (Required):** The overarching research objective.
* **`manifest_path` (Required):** Where to save the output (`<target_dir>/query_manifest.json`).

### Outputs:
* A structured `query_manifest.json` file tailored across 8 platforms: Reddit, Hacker News, Lobsters, GitHub, Twitter/X, ArXiv, Stack Overflow, and Hugging Face.

### Step-by-Step Logic:
1. **Audit Current Textbook:** Passes `parent_prompt` to `wiki-reader` to fetch all existing sections and cross-links.
2. **Find Gaps:** Passes those findings to `first-principle-reasoning` to identify missing failure modes, absent numbers, or unanswered questions.
3. **Rotate Research Phase:** Checks the current phase and advances it ($1 \rightarrow 2 \rightarrow 3 \rightarrow 4 \rightarrow 1$):
   * *Phase 1 (Landmarks):* Foundational architectures and standard reference repos.
   * *Phase 2 (Debates):* Post-mortems, controversy threads, and closed bug issues.
   * *Phase 3 (Zero-Day):* Bleeding-edge preprints and recently merged PRs.
   * *Phase 4 (Long-Tail):* Obscure production bugs and unhandled edge cases.
4. **Translate into Platform Dialects:**
   * *Reddit:* Symptom queries (e.g. `"wal file growing huge checkpoint not working"`).
   * *Hacker News:* High-level architectural debates and post-mortems (e.g. `"Ask HN: startup post-mortem"`).
   * *GitHub:* Segregated into `repo_queries`, `issue_queries`, and `pr_queries`.
   * *Twitter/X:* Punchy queries with boolean filters to remove noise (e.g. `(starvation OR deadlock) -filter:replies`).
   * *ArXiv:* Formal algorithmic and theoretical paper titles.
5. **Write Manifest:** Saves the complete JSON payload directly to `manifest_path`.

### Interaction with `[[wikilinks]]`:
* Uses existing `[[wikilinks]]` in the textbook to map out the knowledge graph, finding "unlinked islands" or missing concepts that need fresh search queries.

---

## 6. `first-principle-reasoning` — The Critical Interrogator

* **Skill Folder:** [`C:\Users\ASUS\.agents\skills\first-principle-reasoning\`](file:///C:/Users/ASUS/.agents/skills/first-principle-reasoning/SKILL.md)
* **Purpose (In Simple Terms):** 
  The ruthless technical skeptic. It strips away hype, marketing claims, and superficial advice by testing statements against physical, mathematical, and operational reality (like speed of light, network round trips, disk write speeds, and clock drift).

### Inputs:
* **`parent_prompt` (Required):** The technical objective.
* **`direct_findings` (Required):** Unedited sections retrieved directly from the textbook.
* **`linked_findings` (Required):** Unedited sections retrieved by following cross-links.

### Outputs:
* **`targeted_queries`:** 3 to 5 sharp, gap-focused search queries targeting missing mechanics, absent empirical numbers (latencies, saturation thresholds), and unhandled failure modes.

### Step-by-Step Logic:
1. **Test Physical Limits:** Tests claims against network round-trip times, RAM bandwidth, SSD write speeds, and clock drift. If a claim promises low latency without explaining how it avoids network or disk trips, it is flagged as unverified.
2. **Prioritize Deterministic Rules:** Rejects fuzzy heuristics where an exact mathematical rule or parser exists (e.g. CST parsing vs vector chunking).
3. **Hunt for Missing Numbers:** Identifies assertions that lack concrete metrics (e.g. p99 latency, RAM saturation ceilings, timeout limits).
4. **Surface Omitted Failure Modes:** Asks what happens when the network splits, memory runs out, two writers conflict, or an API dependency goes down.
5. **Output Targeted Queries:** Formulates queries specifically designed to locate those missing numbers and failure post-mortems.

### Interaction with `[[wikilinks]]`:
* Inspects whether cross-links connect functionally dependent concepts or merely represent superficial word associations.

---

## 7. `git-pr-arbiter` — The Version Control & Push Arbiter

* **Skill Folder:** [`C:\Users\ASUS\.agents\skills\git-pr-arbiter\`](file:///C:/Users/ASUS/.agents/skills/git-pr-arbiter/SKILL.md)
* **Purpose (In Simple Terms):** 
  The Git traffic cop. When multiple agents or repeated cycles edit the textbook, this skill enforces atomic, instant remote pushes (`git push origin main`) on every single change so edits never pile up in dirty working trees or collide with each other.

### Inputs:
* Path of file or directory to stage (`wiki/`).
* Descriptive commit message.
* Target branch (default: `main`).

### Outputs:
* Clean Git commit hash.
* Push confirmation output from remote GitHub repository.

### Step-by-Step Logic:
1. **Pre-Flight Verification:** Checks `git status` to ensure the repository is clean and up to date with remote tracking.
2. **Atomic Stage:** Stages modified files using `git add wiki/<file>`.
3. **Descriptive Commit:** Creates a conventional commit (e.g. `docs(evaluations): codify section 4.32 Platform Custody Risk`).
4. **Immediate Remote Push:** Runs `git push origin main` immediately on the spot. Zero batching is permitted—every discrete chapter change produces its own discrete push.

### Interaction with `[[wikilinks]]`:
* Guarantees that newly written `[[wikilinks]]` are backed up to GitHub immediately, preventing broken links if a process restarts.

---

## 8. `data-point-reasoning` — The LLM-Council Deep Analyzer

* **Skill Folder:** [`C:\Users\ASUS\.agents\skills\data-point-reasoning\`](file:///C:/Users/ASUS/.agents/skills/data-point-reasoning/SKILL.md)
* **Purpose (In Simple Terms):** 
  The peer-review council. When faced with large datasets or complex architectural designs, this skill spawns a fleet of sub-agents to analyze every single data point individually, synthesizes a unified design, and then convenes a separate "Review Council" of critic agents to challenge and harden the design before it is approved.

### Inputs:
* Large dataset of raw claims, architectural requirements, or candidate files.

### Outputs:
* Hardened, peer-reviewed design document and architectural synthesis.

### Step-by-Step Logic:
1. **Fleet Reasoning:** Divides candidate items across an array of worker agents, with each agent reasoning over a specific item's invariants and edge cases.
2. **Initial Synthesis:** Combines individual worker insights into a comprehensive initial architecture.
3. **Council Review:** Spawns a multi-agent Review Council to actively attempt to break the proposed architecture.
4. **Hardened Final Output:** Updates the design to address all council criticisms before submitting.

### Interaction with `[[wikilinks]]`:
* Uses the Council to verify that cross-chapter links represent true conceptual dependencies rather than superficial connections.

---

## Summary Comparison Matrix

| Skill | Primary Role | Key Input | Key Output | Wikilink Role |
| :--- | :--- | :--- | :--- | :--- |
| **`deep-web-analysis`** | Master Orchestrator | User Prompt + Timer | Scraped Dump + Reports | Coordinates full pipeline |
| **`filtering-raw-dump`** | Noise Filter | Raw Dump (`harvested_candidates.json`) | Approved rows in `raw_firehose.db` | Filters source material |
| **`wiki-reader`** | Surgical Reader | Concept query | Matching section markdown | Traverses `[[wikilinks]]` |
| **`ast-markdown-patcher`** | Surgical Editor | File + Heading + Text | Spliced file + Git Push | Authors & verifies `[[wikilinks]]` |
| **`iterative-query-gen`** | Query Strategist | User Prompt + Textbook state | `query_manifest.json` | Identifies unlinked voids |
| **`first-principle-reasoning`**| Technical Skeptic | Existing section text | 3–5 Gap search queries | Audits link dependency truth |
| **`git-pr-arbiter`** | Git Traffic Cop | File + Commit message | Remote GitHub push | Preserves link history |
| **`data-point-reasoning`** | Peer-Review Council | Large data batches | Hardened design | Multi-agent link audit |
