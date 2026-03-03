# Deep-Module Audit: staff-finder

**Date:** 2025-01-24  
**Project:** ./staff-finder

---

## Phase 1: Discovery - Module Structure Map

### Module Inventory

| Module | Lines | Purpose | Dependencies (internal) |
|--------|-------|---------|------------------------|
| `config.py` | 413 | Settings management, env/TOML loading | - |
| `cli.py` | 214 | Typer CLI interface | config, batch_router, batch_tasks |
| `batch_router.py` | 231 | Batch orchestration, state mgmt | batch_tasks |
| `jina_client.py` | 117 | Async Jina search (unused directly) | config |
| `logging_setup.py` | 35 | Basic logging config | - |
| `io_csv.py` | 53 | CSV I/O helpers | - |
| `url_utils.py` | 31 | URL sanitization | - |
| **batch_tasks/** | | | |
| `base.py` | 121 | Abstract BatchTask base | errors |
| `jina_mixin.py` | 222 | JinaBatchTask mixin | base, errors |
| `registry.py` | 33 | Task registration | base |
| `errors.py` | 65 | Error hierarchy | - |
| `utils.py` | 82 | Shared utilities | - |
| `nces_enrichment.py` | 164 | NCES task impl | jina_mixin, registry, utils |
| `staff_directory.py` | 275 | Staff directory task | jina_mixin, registry, utils |
| `district_enrichment.py` | 154 | District task impl | jina_mixin, registry, utils |

**Total:** ~2,277 lines

---

## Phase 2: Evaluation - 8 Dimensions

### Scoring (1-5, 5=best)

| Dimension | Score | Notes |
|-----------|-------|-------|
| **1. Navigability** | 4 | Clear structure, good naming. `batch_tasks/` well-organized. |
| **2. Interface Clarity** | 3 | `__init__.py` exports many symbols. `batch_tasks/__init__.py` has 20+ exports. |
| **3. Boundary Enforcement** | 3 | `jina_client.py` is orphaned (uses Settings but separate from batch_tasks Jina logic). |
| **4. Implementation Depth** | 4 | Good abstraction in BatchTask/JinaBatchTask. Some code duplication in tasks. |
| **5. Test Coverage** | 3 | Tests exist but limited integration tests. |
| **6. Error Propagation** | 4 | Clean error hierarchy. Some generic exceptions in batch_router. |
| **7. Observability** | 2 | `logging_setup.py` exists but tasks don't consistently log. print() in some paths. |
| **8. Configuration Isolation** | 3 | `config.py` handles env vars but tasks also read env directly (JINA_API_KEY). |

**Overall Score: 26/40 (65%)**

---

## Phase 3: Red Flags & Prioritization

### Red Flags Identified

1. **Vague module names:**
   - `utils.py` (batch_tasks) - ⚠️ Contains 6 utility functions
   - `url_utils.py` - minimal but acceptable

2. **Public function count:**
   - `batch_tasks/__init__.py`: 20+ exports
   - Project-wide public API surface: 53,000+ (including .venv!) - analysis script issue

3. **Import breadth:**
   - `cli.py` imports from config, batch_router, batch_tasks - acceptable
   - `jina_mixin.py` imports from 5+ external packages - borderline

4. **Direct env var reads in business logic:**
   - ⚠️ `jina_mixin.py:get_jina_api_key()` reads `STAFF_FINDER_JINA_API_KEY` directly
   - ⚠️ `cli.py` reads `OPENAI_MODEL` directly

5. **Generic exceptions:**
   - `batch_router.py` uses bare `Exception` catches
   - `jina_mixin.py` swallows exceptions with empty returns

6. **Logging:**
   - ⚠️ No structured logging in batch task execution
   - `logging_setup.py` configured but not wired into tasks

7. **Duplicate code patterns:**
   - `validate_input()` in each task follows same pattern
   - `postprocess_data()` has repeated index validation logic

8. **Orphaned module:**
   - `jina_client.py` - async Jina client exists but tasks use `batchctl.core.clients.jina.JinaClient`

---

## Phase 4: Priority Actions & Recommended Patterns

### High Priority

1. **Delete orphaned `jina_client.py`** or consolidate Jina client logic
   - Pattern: *Remove Dead Code*
   - Impact: Removes confusion, reduces maintenance

2. **Extract config access from business logic**
   - Pattern: *Dependency Injection*
   - Move `get_jina_api_key()` to be passed as constructor param
   - Impact: Better testability, cleaner boundaries

3. **Consolidate exception handling in batch_router.py**
   - Pattern: *Introduce Typed Exceptions*
   - Replace `except Exception` with specific error types
   - Impact: Better error messages, debugging

### Medium Priority

4. **Extract common postprocess logic to base class**
   - Pattern: *Template Method*
   - Common: index validation, status checking, JSON parsing
   - Impact: ~30 lines saved per task, consistency

5. **Add structured logging to batch tasks**
   - Pattern: *Cross-Cutting Concern Extraction*
   - Add `structlog` or enrich existing logging
   - Impact: Observability, debugging production issues

6. **Rename `utils.py` → `dataframe_helpers.py` or split**
   - Pattern: *Rename to Clarify*
   - Impact: Better discoverability

### Low Priority

7. **Reduce batch_tasks/__init__.py exports**
   - Pattern: *Narrow Interface*
   - Keep only BatchTask, JinaBatchTask, get_task, list_tasks
   - Impact: Cleaner public API

8. **Split config.py**
   - Pattern: *Extract Class*
   - `settings.py` (dataclass), `loaders.py` (env/TOML), `validators.py`
   - Impact: Each file <150 lines

---

## Recommended Refactoring Sequence

1. ~~Delete `jina_client.py` (unused async client)~~ ✅ DONE
2. Extract common postprocess logic to `BatchTask.postprocess_common()` — DEFERRED
3. Inject Jina API key via constructor instead of env read — DEFERRED
4. ~~Add logging to `JinaBatchTask.preprocess_with_jina()`~~ ✅ DONE
5. ~~Rename `batch_tasks/utils.py` → `batch_tasks/dataframe_helpers.py`~~ ✅ DONE
6. ~~Narrow `batch_tasks/__init__.py` exports~~ ✅ DONE

---

## Refactoring Applied (2025-01-24)

### Completed via Codex CLI (gpt-5.3-codex)

1. **Deleted orphaned `jina_client.py`**
   - Removed `src/staff_finder/jina_client.py` (117 lines)
   - Removed `tests/test_networkless.py` (dependent test file)
   - No remaining imports in codebase

2. **Renamed utils module**
   - `batch_tasks/utils.py` → `batch_tasks/dataframe_helpers.py`
   - Updated all imports in 5 files

3. **Added structured logging to JinaBatchTask**
   - Module-level logger: `logging.getLogger(__name__)`
   - Log on preprocess start: rows, workers
   - Log on Jina query failure after retries
   - Log on preprocess complete: rows, succeeded, failed, workers
   - Introduced `JINA_FETCH_MAX_ATTEMPTS` constant

4. **Narrowed batch_tasks/__init__.py exports**
   - Before: 20+ exports
   - After: 9 essential public API exports
   - Removed utility functions (internal use)
   - Removed specific error subclasses (users catch BatchTaskError)

### Test Results
All tests passing (78 tests).

---

## Metrics Summary

| Metric | Before | After | Target |
|--------|--------|-------|--------|
| Orphaned modules | 1 | 0 | 0 ✅ |
| Public API exports | 20+ | 9 | <15 ✅ |
| Task files with logging | 0 | 1 | 3 |
| Lines removed | - | ~160 | - |
| Direct env reads in tasks | 2 | 2 | 0 |
| Generic exception catches | 4 | 4 | 0 |
| Duplicated postprocess lines | ~60 | ~60 | ~10 |

### Deferred for Future Work
- Extract common postprocess logic to base class (Template Method pattern)
- Inject Jina API key via constructor (Dependency Injection)
- Replace remaining generic `except Exception` catches
