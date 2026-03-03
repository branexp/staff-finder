# SQL Optimization Patterns for pera-contacts

This document captures SQL optimization patterns learned from the NCES district ID enrichment project. Use these patterns when writing or optimizing SQL queries in this repository.

---

## Index Design Principles

### Partial Indices for Filtered Queries

When queries always filter on a specific condition, use partial indices:

```sql
-- GOOD: Smaller index, only covers relevant rows
CREATE INDEX idx_contacts_organization_state_sd
ON contacts ("Organization", "State")
WHERE "OrganizationType" = 'School Districts';

-- BAD: Larger index, includes all rows
CREATE INDEX idx_contacts_organization_state
ON contacts ("Organization", "State");
```

**Impact:** Partial index is ~56 MB vs ~200+ MB for full index.

### Composite Index Column Order

Order columns by selectivity (most selective first) and query patterns:

```sql
-- For queries filtering by state_abbr then joining on organization
CREATE INDEX idx_ref_districts_state_name 
ON ref_districts (state_abbr, district_name);

-- For normalized exact matching
CREATE INDEX idx_ref_districts_normalized 
ON ref_districts (state_abbr, district_name_normalized);
```

### INCLUDE for Covering Indices (PostgreSQL 11+)

When you need columns that aren't in the WHERE clause:

```sql
CREATE INDEX idx_contacts_contactid_state_org
ON contacts ("ContactId")
INCLUDE ("State", "Organization")
WHERE "OrganizationType" = 'School Districts';
```

---

## Trigram Matching with GIN Indices

### Enable pg_trgm Extension

```sql
CREATE EXTENSION IF NOT EXISTS pg_trgm;
```

### GIN Index for Similarity Searches

```sql
-- Critical for fast similarity() and % operator queries
CREATE INDEX idx_ref_districts_name_trgm 
ON ref_districts USING GIN (district_name gin_trgm_ops);
```

### Understanding Trigram Thresholds

The `%` operator uses a default threshold of ~0.3, which is too permissive:

```sql
-- BAD: % operator matches too many false positives
SELECT * FROM ref_districts WHERE district_name % 'Chicago Public Schools';

-- GOOD: Use explicit similarity threshold
SELECT * FROM ref_districts 
WHERE district_name % 'Chicago Public Schools'  -- Uses GIN index for candidates
  AND similarity(district_name, 'Chicago Public Schools') >= 0.75;  -- Filter to high confidence
```

### Performance Comparison

| Approach | Time | Notes |
|----------|------|-------|
| No index, `similarity() >= 0.75` | ~900ms | Full table scan per query |
| GIN index, `%` operator | ~64ms | Index scan, but 0.3 threshold |
| GIN index + explicit threshold | ~70ms | Best balance of speed and accuracy |

---

## Normalization Functions

### Immutable Functions for Indexes

Functions used in indexes must be `IMMUTABLE`:

```sql
CREATE OR REPLACE FUNCTION normalize_district_name(org TEXT) RETURNS TEXT AS $$
BEGIN
    org := upper(org);
    org := regexp_replace(org, '\s+', ' ', 'g');  -- Normalize whitespace
    org := trim(org);
    
    -- Handle abbreviations (convert to standard form)
    org := regexp_replace(org, '\s+USD$', ' UNIFIED SCHOOL DISTRICT', 'i');
    org := regexp_replace(org, '\s+ISD$', ' INDEPENDENT SCHOOL DISTRICT', 'i');
    
    -- Remove suffixes (order matters - longer first)
    org := regexp_replace(org, ' UNIFIED SCHOOL DISTRICT$', '', 'i');
    org := regexp_replace(org, ' SCHOOL DISTRICT$', '', 'i');
    org := regexp_replace(org, ' PUBLIC SCHOOLS$', '', 'i');
    -- ... more suffixes
    
    RETURN trim(org);
END;
$$ LANGUAGE plpgsql IMMUTABLE;  -- IMMUTABLE is required for indexing
```

### Pre-Compute Normalized Values

Don't normalize on every query - pre-compute and index:

```sql
-- Add normalized column
ALTER TABLE ref_districts ADD COLUMN district_name_normalized TEXT;

-- Populate once
UPDATE ref_districts 
SET district_name_normalized = normalize_district_name(district_name);

-- Index for fast lookups
CREATE INDEX idx_ref_districts_normalized 
ON ref_districts (state_abbr, district_name_normalized);
```

---

## Data Quality Pre-Filtering

### Filter Obvious Non-Matches Early

Exclude garbage data before processing:

```sql
-- Data quality filters
WHERE "Organization" IS NOT NULL
  AND "Organization" != ''
  AND "Organization" !~ '^[0-9]+$'           -- Not phone numbers
  AND "Organization" !~ '^[0-9]'             -- Not starting with digit
  AND LENGTH("Organization") >= 3            -- Not too short
  AND "Organization" NOT ILIKE '%@%'         -- Not email addresses
  AND "Organization" NOT ILIKE 'http%'       -- Not URLs
  AND "Organization" NOT ILIKE '%university%' -- Not higher ed
  AND "Organization" NOT ILIKE '%college%'
  AND "Organization" NOT ILIKE '%hospital%'  -- Not medical
```

### Impact on Performance

| Scenario | Records Processed | Time Saved |
|----------|-------------------|------------|
| Without filtering | 4,189 orgs | Baseline |
| With filtering | 3,768 orgs | ~10% faster |

For this project, filtering removed 421 organizations (160K contacts) from processing.

---

## Batch Processing by State

### Why Batch by State?

1. **Avoids long table locks** - Each state commits independently
2. **Progress visibility** - Track completion per state
3. **Resumable** - Can pause/resume if interrupted
4. **Smaller transactions** - Less likely to timeout

### Progress Tracking Table

```sql
CREATE TABLE operation_progress (
    state_abbr TEXT PRIMARY KEY,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    items_total INT,
    items_processed INT,
    status TEXT DEFAULT 'pending'  -- pending, in_progress, completed, failed
);
```

### Batch Update Pattern

```sql
DO $$
DECLARE
    state_rec RECORD;
    processed_count INT;
BEGIN
    FOR state_rec IN 
        SELECT state_abbr, items_total 
        FROM operation_progress 
        WHERE status = 'pending'
        ORDER BY items_total DESC  -- Process largest first
    LOOP
        -- Mark in progress
        UPDATE operation_progress 
        SET status = 'in_progress', started_at = clock_timestamp()
        WHERE state_abbr = state_rec.state_abbr;
        
        COMMIT;  -- Release locks, make progress visible
        
        -- Do the work
        UPDATE target_table SET ... WHERE "State" = state_rec.state_abbr;
        GET DIAGNOSTICS processed_count = ROW_COUNT;
        
        -- Mark complete
        UPDATE operation_progress 
        SET status = 'completed',
            items_processed = processed_count,
            completed_at = clock_timestamp()
        WHERE state_abbr = state_rec.state_abbr;
        
        COMMIT;
    END LOOP;
END;
$$;
```

---

## Temp Tables vs CTEs

### When to Use Temp Tables

**Use temp tables when:**
- The result is used multiple times
- The query is expensive and repeated
- You need indices on the intermediate result
- The dataset is large and repeated scans are costly

```sql
-- GOOD: Materialize once, use multiple times
CREATE TEMP TABLE tmp_targets AS
SELECT DISTINCT "State", "Organization", normalize_district_name("Organization") AS org_normalized
FROM contacts
WHERE "OrganizationType" = 'School Districts' AND nces_district_id IS NULL;

CREATE INDEX idx_tmp_targets_state ON tmp_targets (state_abbr);

-- Now use tmp_targets in multiple queries...
```

**Use CTEs when:**
- The result is used once
- The query is simple
- You want query encapsulation

```sql
-- OK for single use
WITH targets AS (
    SELECT DISTINCT "State", "Organization"
    FROM contacts
    WHERE "OrganizationType" = 'School Districts'
)
SELECT * FROM targets JOIN ...;
```

---

## Progress Tracking Pattern

### Create Progress Table

```sql
CREATE TABLE operation_progress (
    batch_id TEXT PRIMARY KEY,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    items_total INT,
    items_processed INT DEFAULT 0,
    status TEXT DEFAULT 'pending',
    error_message TEXT
);
```

### Monitoring Query

```sql
SELECT 
    status,
    COUNT(*) as batches,
    SUM(items_processed) as total_processed,
    SUM(items_total) as total_items,
    ROUND(100.0 * SUM(items_processed) / NULLIF(SUM(items_total), 0), 1) as pct_complete
FROM operation_progress
GROUP BY status;
```

---

## Neon/PostgreSQL Specifics

### Parallel Query Support

Neon supports parallel execution. Design queries to leverage it:

```sql
-- GOOD: Parallel-friendly (ordered by indexed column)
SELECT DISTINCT "State", "Organization"
FROM contacts
WHERE "OrganizationType" = 'School Districts'
ORDER BY "State";

-- BAD: Forces single process (random ordering)
SELECT DISTINCT "State", "Organization"
FROM contacts
WHERE "OrganizationType" = 'School Districts'
ORDER BY random();
```

### Index-Only Scans

Check if index-only scans are possible:

```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT "State", "Organization"
FROM contacts
WHERE "OrganizationType" = 'School Districts';

-- If "Heap Fetches" is high, consider INCLUDE:
CREATE INDEX idx_covering ON contacts ("OrganizationType")
INCLUDE ("State", "Organization");
```

---

## Anti-Patterns to Avoid

### 1. Cross-Product Joins Without Filters

```sql
-- BAD: Compares every org to every district O(n*m)
SELECT t.org, d.district_name
FROM tmp_orgs t
JOIN ref_districts d ON similarity(t.org, d.district_name) > 0.8;

-- GOOD: Filter by state first O(n*m_s) where m_s << m
SELECT t.org, d.district_name
FROM tmp_orgs t
JOIN ref_districts d ON d.state_abbr = t.state_abbr
WHERE similarity(t.org, d.district_name) > 0.8;
```

### 2. Functions on Indexed Columns

```sql
-- BAD: Function prevents index usage
SELECT * FROM contacts WHERE LOWER("Organization") = 'abc';

-- GOOD: Use function-based index or normalized column
CREATE INDEX idx_org_lower ON contacts (LOWER("Organization"));
-- Or pre-compute normalized value
```

### 3. OR Conditions with Different Columns

```sql
-- BAD: OR prevents index usage
SELECT * FROM contacts
WHERE "State" = 'CA' OR "Organization" = 'Test';

-- GOOD: UNION with individual indexes
SELECT * FROM contacts WHERE "State" = 'CA'
UNION
SELECT * FROM contacts WHERE "Organization" = 'Test';
```

### 4. Large Transactions

```sql
-- BAD: Single transaction for millions of updates
BEGIN;
UPDATE contacts SET nces_district_id = ...;
COMMIT;  -- Holds locks for entire duration

-- GOOD: Batch by state with commits
FOR state IN states LOOP
    UPDATE contacts SET ... WHERE "State" = state;
    COMMIT;
END LOOP;
```

### 5. Implicit Type Conversions

```sql
-- BAD: Implicit cast prevents index usage
SELECT * FROM ref_districts WHERE nces_district_id = 123;  -- nces_district_id is TEXT

-- GOOD: Explicit type match
SELECT * FROM ref_districts WHERE nces_district_id = '123';
```

---

## Performance Checklist

Before running large-scale SQL operations:

- [ ] Create necessary indices (GIN for trigram, composite for joins)
- [ ] Pre-compute normalized/derived values
- [ ] Filter out invalid/unwanted data early
- [ ] Use temp tables for repeated expensive operations
- [ ] Process by state or other natural partition
- [ ] Implement progress tracking
- [ ] Test with `EXPLAIN (ANALYZE, BUFFERS)` on subset
- [ ] Estimate total runtime (test on 1% → multiply by 100)

---

## Example: Complete Optimization

### Before (12-24 hours)

```sql
-- No index on trigram
-- Single transaction
-- Repeated normalization
WITH targets AS (
    SELECT DISTINCT "State", "Organization"
    FROM contacts
    WHERE "OrganizationType" = 'School Districts' AND nces_district_id IS NULL
)
SELECT t.*, d.nces_district_id
FROM targets t
JOIN ref_districts d ON d.state_abbr = t."State"
  AND similarity(t."Organization", d.district_name) >= 0.75;
```

### After (15-30 minutes)

```sql
-- 1. Create indices
CREATE INDEX idx_ref_districts_name_trgm ON ref_districts USING GIN (district_name gin_trgm_ops);
CREATE INDEX idx_contacts_organization_state_sd ON contacts ("Organization", "State") WHERE "OrganizationType" = 'School Districts';

-- 2. Pre-compute normalized values
ALTER TABLE ref_districts ADD COLUMN district_name_normalized TEXT;
UPDATE ref_districts SET district_name_normalized = normalize_district_name(district_name);

-- 3. Materialize targets
CREATE TEMP TABLE tmp_targets AS
SELECT DISTINCT "State", "Organization", normalize_district_name("Organization") AS org_normalized
FROM contacts
WHERE "OrganizationType" = 'School Districts' AND nces_district_id IS NULL;

-- 4. Process by state with progress tracking
-- (See batch processing pattern above)
```

---

## References

- PostgreSQL pg_trgm: https://www.postgresql.org/docs/current/pgtrgm.html
- Neon Documentation: https://neon.tech/docs/introduction
- NCES CCD Data: https://nces.ed.gov/ccd/

---

*Document created: 2026-03-03*
*Last updated: 2026-03-03*
*Based on: NCES District ID Enrichment optimization session*
