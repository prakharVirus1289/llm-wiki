# End-to-End LLM-Wiki Iteration Architecture

> For internal tool execution logic, database table interactions, and exact SQL statements, see the [MCP Tools Reference](file:///C:/Users/ASUS/Documents/llm-wiki/docs/mcp_tools.md).

This document outlines the high-level architecture of the autonomous textbook iteration loop. Tool calls are treated as clean service boundaries—internal database queries, full-text index rebuilds, and AST file manipulation are encapsulated entirely inside the MCP server.

### System Workflow Overview
1. **Web Harvesting (`deep-web-analysis`):** Multi-platform discovery across Reddit, Twitter/X, and GitHub.
2. **Adversarial Curation & Ingestion (`filtering-raw-dump`):** Non-deterministic 4-point relevance filtering followed by atomic deduplication and storage in `raw_firehose` via `llm_wiki_firehose_ingest`.
3. **LLM-Council Deep Reasoning (`data-point-reasoning`):** Two-phase deliberation (Raw Data Council followed by Adversarial Review Council).
4. **Targeted Textbook Reading (`wiki-reader`):** Dual-track prompt decomposition, MCP similarity & keyword search, relevance filtering, and surgical cross-link destination audit.
5. **Surgical Patching (`ast-markdown-patcher`):** Single-section updates, automatic cross-chapter wikilinking, and index synchronization.
6. **Remote Version Control (`git-pr-arbiter`):** Atomic Git staging, commit creation, and remote push.
7. **Query Steering & Gap Traversal (`iterative-query-gen` & `first-principle-reasoning`):** Supplies `parent_prompt` to `wiki-reader`, runs first-principles gap reasoning on vetted findings, and synthesizes platform-tailored manifests across Reddit, Hacker News, GitHub, Twitter/X, Lobsters, ArXiv, Stack Overflow, and Hugging Face.

---

```mermaid
flowchart TD
    %% ==========================================
    %% STAGE 1: WEB RESEARCH & HARVESTING
    %% ==========================================
    subgraph S1 ["Stage 1: Web Research & Harvesting"]
        Trigger["User Request / Scheduled Timer / Backlog"] --> SkillDWA["Skill: deep-web-analysis"]
        SkillDWA -->|"Scrapes Reddit, Twitter/X, GitHub"| RawJSON["harvested_candidates.json (Raw Web Posts)"]
    end

    %% ==========================================
    %% STAGE 2: ADVERSARIAL CURATION & INGESTION
    %% ==========================================
    subgraph S2 ["Stage 2: Adversarial Curation & Ingestion (filtering-raw-dump)"]
        RawJSON --> SkillFRD["Skill: filtering-raw-dump"]
        SkillFRD -->|"Applies 4-Point Filter & Tool Call: llm_wiki_firehose_ingest(approved)"| ToolIngest["MCP Tool: llm_wiki_firehose_ingest"]
        ToolIngest -->|"Returns: Ingested count, duplicates skipped"| IngestedClean["Clean Batch Stored in Central DB (raw_firehose)"]
    end

    %% ==========================================
    %% STAGE 3: DATA-POINT REASONING (LLM-COUNCIL)
    %% ==========================================
    subgraph S3 ["Stage 3: Data-Point Reasoning (LLM-Council)"]
        IngestedClean --> SkillDPR["Skill: data-point-reasoning"]
        SkillDPR -->|"Partitions raw posts into atomic items"| ChunkPartition["Item Partitioning Engine"]
        
        subgraph Phase1 ["Phase 1: Raw Data Council"]
            ChunkPartition -->|"invoke_subagent (Parallel Fleet)"| SubAgents["Sub-Agent Fleet (Reasoning on Every Item)"]
            SubAgents -->|"Synthesizes individual findings"| InitialSynth["Initial Synthesis (V1 Draft)"]
        end
        
        subgraph Phase2 ["Phase 2: Adversarial Review Council"]
            InitialSynth -->|"invoke_subagent (Specialist Personas)"| ReviewCouncil["Review Council (Adversarial Critique)"]
            ReviewCouncil -->|"Hardens facts & discards hype"| HardenedFacts["Hardened Truth & Architectural Invariants"]
        end
    end

    %% ==========================================
    %% STAGE 4: CHECK EXISTING TEXTBOOK (ZERO BLOAT)
    %% ==========================================
    subgraph S4 ["Stage 4: Read Existing Textbook"]
        HardenedFacts --> SkillReader["Skill: wiki-reader"]
        SkillReader -->|"Tool Call: llm_wiki_search_hybrid(query)"| ToolSearch["MCP Tool: llm_wiki_search_hybrid"]
        ToolSearch -->|"Returns: Ranked matching sections"| MatchList["Target Chapter & Heading Identified"]
        
        MatchList -->|"Tool Call: llm_wiki_read_section(file, heading)"| ToolRead["MCP Tool: llm_wiki_read_section"]
        ToolRead -->|"Returns: Exact section markdown (Zero token bloat)"| SectionText["Existing Section Text"]
        SectionText --> AgentCompare["Agent Compares Existing Text vs New Facts"]
    end

    %% ==========================================
    %% STAGE 5: SURGICAL FILE PATCH & RE-INDEXING
    %% ==========================================
    subgraph S5 ["Stage 5: Surgical Section Patching"]
        AgentCompare --> SkillPatch["Skill: ast-markdown-patcher"]
        SkillPatch -->|"Tool Call: llm_wiki_patch_section(file, heading, content)"| ToolPatch["MCP Tool: llm_wiki_patch_section"]
        ToolPatch -->|"Returns: Spliced cleanly, cross-links created, search updated"| PatchedChapter["Chapter Updated on Disk (wiki/*.md)"]
    end

    %% ==========================================
    %% STAGE 6: REMOTE VERSION CONTROL
    %% ==========================================
    subgraph S6 ["Stage 6: Version Control & Remote Sync"]
        PatchedChapter --> SkillPR["Skill: git-pr-arbiter"]
        SkillPR -->|"Tool Call: llm_wiki_git_commit_and_push(file, message)"| ToolGit["MCP Tool: llm_wiki_git_commit_and_push"]
        ToolGit -->|"Returns: Staged, committed, and pushed"| RemoteRepo["GitHub Remote Tracking Branch"]
    end

    %% ==========================================
    %% STAGE 7: DYNAMIC QUERY STEERING & REASONING
    %% ==========================================
    subgraph S7 ["Stage 7: Dynamic Query Steering & Reasoning (iterative-query-gen)"]
        RemoteRepo --> InputsIQG["Inputs from deep-web-analysis:<br/>• parent_prompt<br/>• manifest_path (Required)"]
        
        InputsIQG --> SkillReaderIQG["Skill: wiki-reader<br/>(Supply: parent_prompt)"]
        
        SkillReaderIQG -->|"Returns: direct_findings & linked_findings"| Step5Gaps["Skill: first-principle-reasoning<br/>(Critiques findings, surfaces missing numbers & failure modes)"]
        
        Step5Gaps --> Step6Dialects["Step 3: Multi-Platform Dialect Synthesis<br/>(Reddit, HN, Lobsters, GitHub, Twitter, ArXiv, SO, HF)"]
        
        Step6Dialects --> Manifest["Write Platform-Tailored query_manifest.json<br/>(Directly to required manifest_path)"]
        Manifest -->|"Feeds next harvesting iteration"| SkillDWA
    end

    %% Styling
    classDef skill fill:#2d3748,stroke:#4a5568,color:#fff,stroke-width:2px;
    classDef mcp fill:#4c51bf,stroke:#667eea,color:#fff,stroke-width:2px;
    classDef data fill:#276749,stroke:#38a169,color:#fff,stroke-width:2px;
    classDef council fill:#553c9a,stroke:#805ad5,color:#fff,stroke-width:2px;
    classDef steer fill:#744210,stroke:#d69e2e,color:#fff,stroke-width:2px;

    class SkillDWA,SkillFRD,SkillDPR,SkillReader,SkillPatch,SkillPR,SkillReaderIQG,Step5Gaps skill;
    class ToolIngest,ToolSearch,ToolRead,ToolPatch,ToolGit mcp;
    class RawJSON,IngestedClean,PatchedChapter,RemoteRepo,Manifest data;
    class SubAgents,ReviewCouncil,InitialSynth,HardenedFacts,ChunkPartition council;
    class InputsIQG,Step6Dialects steer;
```
