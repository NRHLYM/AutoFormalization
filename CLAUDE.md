# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is an auto-formalization system that translates informal mathematical statements into formal Lean 4 code. The system consists of three main components:

1. **Formalizer**: Python-based LLM-driven formalization pipeline implementing a two-stage approach (GoT decomposition + synthesis)
2. **LeanSearch**: Semantic search engine for Lean 4 projects with PostgreSQL backend and vector embeddings
3. **jixia**: Static analysis tool for Lean 4 that extracts metadata (declarations, symbols, elaboration info, etc.)

## Build and Development Commands

### Lean 4 Components

**Build the main Lean project:**
```bash
# From project root
lake build
```

**Build jixia (static analyzer):**
```bash
cd jixia
lake build
# Executable will be at: jixia/.lake/build/bin/jixia
```

**Run jixia on a file:**
```bash
# For standalone files (no lakefile):
lake env lean -o Example.olean Example.lean
jixia/.lake/build/bin/jixia -d Example.decl.json -s Example.sym.json -e Example.elab.json -l Example.lines.json Example.lean

# For files within a Lean project:
lake env jixia/.lake/build/bin/jixia -d Example.decl.json -s Example.sym.json Example.lean
```

Flags for jixia:
- `-d`: Declaration info
- `-s`: Symbol info
- `-e`: Elaboration info
- `-l`: Line info (proof states)
- `-a`: AST dump
- `-i`: Enable initializers (required for mathlib4)

### Python Components (LeanSearch & Formalizer)

**Set up LeanSearch:**
```bash
cd LeanSearch
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

**Configure environment:**
- Copy `.env.example` to `.env` and configure database connection and API keys
- Ensure PostgreSQL is running (or use `docker-compose up -d` for containerized setup)

**Index a Lean project:**
```bash
# 1. Extract metadata using jixia
python -m database jixia <project_root> <module_prefixes>
# Example: python -m database jixia /path/to/mathlib Init,Lean,Mathlib

# 2. Generate informal descriptions (uses OpenAI-compatible API)
python -m database informal

# 3. Create vector embeddings (uses e5-mistral-7b-instruct locally)
python -m database vector-db
```

**Search the database:**
```bash
python search.py "query1" "query2"
```

**Run the LeanSearch server:**
```bash
# From LeanSearch directory
# Server provides /search, /fetch, /augment, and /feedback endpoints
uvicorn server:app
```

### Formalizer Pipeline

**Setup:**
```bash
# Configure API keys in Formalizer/config.py
# Required: LLM_API_KEY, LLM_BASE_URL, LLM_MODEL_NAME
# Note: These should ideally be moved to .env in the future
```

**Run the complete pipeline:**
```bash
# From project root
python Formalizer/main.py
# Output will be written to output.lean
```

**Run individual stages:**
```bash
# Stage 1 only (decomposition):
python Formalizer/stage1_planner.py

# Stage 2 only (synthesis - requires Stage 1 output):
python Formalizer/stage2_synthesizer.py
```

**Test components:**
```bash
# Test grounding module:
python Formalizer/test_grounding.py

# Test LLM connection:
python Formalizer/test_llm.py
```

## Architecture

### Formalizer Pipeline (Two-Stage Approach)

**Stage 1: GoT (Graph of Thought) Decomposition** (`stage1_planner.py`)
- Breaks down informal mathematical concepts into a dependency graph
- For each concept node:
  - **Grounding Module**: Uses RAG to search LeanSearch for existing Mathlib definitions
  - **Expansion Module**: If not found, LLM decomposes it into sub-concepts
- Outputs a `ConceptualGraph` with nodes marked as either GROUNDED (found in Mathlib) or TO_SYNTHESIZE

**Stage 2: Synthesis** (`stage2_synthesizer.py`)
- Processes nodes in topological order (bottom-up)
- For TO_SYNTHESIZE nodes, generates Lean 4 definitions using LLM
- Uses reflection loop with Lean compiler feedback for error correction (max 16 attempts)

**Key modules:**
- `modules/llm_modules.py`: LLM interface for grounding and expansion
- `modules/external_tools.py`: LeanSearchClient integration
- `modules/data_structures.py`: ConceptualGraph, Node, NodeStatus
- `config.py`: Configuration (contains API keys - should be moved to .env)

### LeanSearch Database Schema

The system uses PostgreSQL with the following key tables:
- `module`: Lean module metadata (name, content, docstring)
- `declaration`: Declaration-level info (signature, value, kind, visibility)
- `symbol`: Symbol-level info after elaboration (type, references, dependencies)
- `dependency`: Dependency graph (type references and value references)
- `level`: Topological sort levels for symbols
- `record`: Denormalized view combining declaration + symbol + informal translation
- `query`, `feedback`: User interaction tracking

Vector embeddings are stored in ChromaDB (separate from PostgreSQL).

### jixia Plugin System

jixia uses a plugin-based architecture (`jixia/Analyzer/Process.lean`):
- Plugins register via `Process.plugins` array
- Each plugin implements:
  - `onLoad`: Optional setup hook (runs before file processing)
  - `getResult`: Required function to extract and return results
- Main plugins are in `jixia/Analyzer/Process/` (Declaration, Symbol, Elaboration, Line, Module)
- The `impl_parseOptions` and `impl_process` macros auto-generate option parsing from plugin list

## Important Environment Variables

**LeanSearch (.env):**
- `CONNECTION_STRING`: PostgreSQL connection (format: `postgresql://user:password@host:port/dbname`)
- `CHROMA_PATH`: Path to ChromaDB storage
- `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_MODEL`: For informal description generation (recommend DeepSeek v3)
- `EMBEDDING_DEVICE`: Device for embedding model (e.g., "cuda", "cpu")
- `LEAN_SYSROOT`: Path to Lean installation root (get via `lake env | grep LEAN_SYSROOT`)
- `JIXIA_PATH`: Path to jixia executable (e.g., `/path/to/jixia/.lake/build/bin/jixia`)

**Formalizer (config.py - should migrate to .env):**
- `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL_NAME`: LLM configuration
- `MAX_REFLECTION_ATTEMPTS`: Max retries for synthesis error correction (default: 16)
- `LEAN_SANDBOX_PATH`: Path to Lean project root for compilation (defaults to project root)
- `LEANSEARCH_API_URL`: LeanSearch API endpoint (default: https://leansearch.net/search)

## Version Requirements

- **Lean 4**: v4.24.0 (root project)
- **jixia**: Must be built with exact same Lean version as target files/projects
- **Mathlib4**: master branch (required dependency)
- **Python**: 3.11+ (based on venv structure)

## Database Setup

Use the provided `docker-compose.yml` for PostgreSQL:
```bash
docker-compose up -d
# Creates database: leansearch_db
# User: postgres, Password: 123456, Port: 5432
```

Schema is created automatically via `database/create_schema.py`.

## Common Workflows

**To formalize a new mathematical statement (full pipeline):**
1. Ensure LeanSearch is indexed with relevant Lean libraries (see Database Setup)
2. Edit the `initial_statement` variable in `Formalizer/main.py` with your informal mathematical statement
3. Run: `python Formalizer/main.py`
4. Output will be written to `output.lean` in the project root

**To formalize using individual stages:**
1. Stage 1 (Decomposition): `python Formalizer/stage1_planner.py`
   - Modify the test statement at the bottom of the file
   - Outputs a `ConceptualGraph` with dependency structure
2. Stage 2 (Synthesis): `python Formalizer/stage2_synthesizer.py`
   - Takes the graph from Stage 1 as input
   - Generates Lean code with compiler feedback loop

**To index a new Lean project for search:**
1. Start PostgreSQL: `docker-compose up -d`
2. Activate LeanSearch venv: `cd LeanSearch && source .venv/bin/activate`
3. Extract metadata: `python -m database jixia <project_root> <module_prefixes>`
4. Generate descriptions: `python -m database informal`
5. Build embeddings: `python -m database vector-db`

**To add new jixia analysis:**
1. Create new plugin in `jixia/Analyzer/Process/YourPlugin.lean`
2. Define namespace with `getResult` and optional `onLoad`
3. Register in `Process.plugins` array in `jixia/Analyzer/Process.lean`
4. Rebuild jixia: `cd jixia && lake build`

**To update the search index after Lean code changes:**
1. `python -m database jixia <project_root> <prefixes>` (re-extract metadata)
2. `python -m database informal` (regenerate descriptions for new declarations)
3. `python -m database vector-db` (update embeddings)

## File Locations

**Important files:**
- `Formalizer/main.py`: Entry point for full formalization pipeline
- `Formalizer/config.py`: Configuration (API keys, paths, LLM settings)
- `output.lean`: Default output file for formalized code (created at project root)
- `AriaTemp.lean`: Temporary file used by Lean compiler during synthesis (auto-deleted)
- `LeanSearch/.env`: Configuration for LeanSearch and database
- `docker-compose.yml`: PostgreSQL database setup

**Key directories:**
- `Formalizer/prompts/`: LLM prompts for grounding, expansion, synthesis, and reflection
- `Formalizer/modules/`: Core data structures and external tool clients
- `jixia/Analyzer/Process/`: Plugin implementations for static analysis
- `LeanSearch/database/`: Database schema, indexing, and embedding logic

## Data Flow

**Component interactions:**

1. **jixia → LeanSearch indexing:**
   - jixia extracts JSON metadata from Lean files (declarations, symbols, elaboration info)
   - `database/jixia_db.py` reads these JSON files and populates PostgreSQL tables
   - `database/informalize.py` uses LLM to generate informal descriptions for each declaration
   - `database/vector_db.py` creates embeddings and stores them in ChromaDB

2. **LeanSearch → Formalizer (Stage 1):**
   - Formalizer calls LeanSearch API via `modules/external_tools.py:LeanSearchClient`
   - Stage 1 grounding module queries for each concept node
   - Returns `LeanSearchResult` objects with Lean names and informal descriptions
   - Nodes marked GROUNDED if found in Mathlib, TO_SYNTHESIZE otherwise

3. **Stage 1 → Stage 2:**
   - Stage 1 outputs `ConceptualGraph` with dependency structure
   - Stage 2 calls `graph.get_build_order()` for topological sort
   - Processes nodes bottom-up (leaves first, root last)

4. **Formalizer → Lean compiler:**
   - Stage 2 uses `modules/external_tools.py:LeanCompilerClient`
   - Writes code to temporary file `AriaTemp.lean` in `src/` directory
   - Calls `lake env lean <file>` for compilation
   - Parses compiler errors and feeds back to LLM for reflection
   - Repeats up to MAX_REFLECTION_ATTEMPTS times per node

**Data formats:**
- jixia outputs: JSON files with `.decl.json`, `.sym.json`, `.elab.json`, `.lines.json` extensions
- LeanSearch API: JSON with structure `[[{result: {name: [...], informal_description: "..."}, distance: ...}, ...]]`
- ConceptualGraph: In-memory Python object with `ConceptNode` instances linked by dependencies
- Final output: Single `.lean` file with all synthesized definitions