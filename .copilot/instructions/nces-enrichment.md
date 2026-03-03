# NCES District ID Enrichment

This document provides instructions for implementing and maintaining the NCES district ID enrichment process in the pera-contacts database.

## Overview

The NCES (National Center for Education Statistics) district ID enrichment process matches school district organizations in the `contacts` table to the official NCES CCD (Common Core of Data) district identifiers stored in the `ref_districts` table.

### Current Status (as of 2026-03-03)

| Metric | Value |
|--------|-------|
| Total SD contacts | 7,943,975 |
| With NCES ID | 6,128,094 (77.1%) |
| Unmapped | 1,815,881 (22.9%) |

---

## Database Schema

### contacts table

```sql
-- Key columns for NCES enrichment
"ContactId" INTEGER PRIMARY KEY,
"OrganizationType" TEXT,          -- Filter to 'School Districts'
"Organization" TEXT,              -- District name to match
"State" TEXT,                     -- State abbreviation
nces_district_id TEXT             -- Target column to populate
```

### ref_districts table

```sql
-- Reference data from NCES CCD
nces_district_id TEXT PRIMARY KEY,
district_name TEXT,
state_abbr TEXT,
domain TEXT,                      -- Optional: for domain-based matching
district_name_normalized TEXT     -- Pre-computed normalized name
```

### nces_district_mappings table

```sql
-- Cache of computed mappings
state_abbr TEXT,
organization TEXT,
nces_district_id TEXT,
match_type TEXT,                  -- 'normalized_exact', 'trigram_075', 'trigram_060', etc.
similarity_score REAL,
PRIMARY KEY (state_abbr, organization)
```

---

## Required Indices

```sql
-- GIN trigram index for fuzzy matching
CREATE INDEX idx_ref_districts_name_trgm 
ON ref_districts USING GIN (district_name gin_trgm_ops);

-- Composite index for state-filtered queries
CREATE INDEX idx_ref_districts_state_name 
ON ref_districts (state_abbr, district_name);

-- Normalized name index for exact matching
CREATE INDEX idx_ref_districts_normalized 
ON ref_districts (state_abbr, district_name_normalized);

-- Partial index on contacts for school districts
CREATE INDEX idx_contacts_organization_state_sd
ON contacts ("Organization", "State")
WHERE "OrganizationType" = 'School Districts';
```

---

## Matching Algorithm

### Phase 1: Normalized Exact Match

After normalizing both organization names and NCES district names, perform exact matches:

```sql
INSERT INTO nces_district_mappings (state_abbr, organization, nces_district_id, match_type, similarity_score)
SELECT 
    t.state_abbr,
    t.organization,
    d.nces_district_id,
    'normalized_exact',
    1.0
FROM tmp_unmapped_orgs t
JOIN ref_districts d 
    ON d.state_abbr = t.state_abbr 
    AND d.district_name_normalized = t.org_normalized;
```

### Phase 2: High-Confidence Trigram (≥0.75)

```sql
INSERT INTO nces_district_mappings (...)
SELECT DISTINCT ON (t.state_abbr, t.organization)
    t.state_abbr,
    t.organization,
    d.nces_district_id,
    'trigram_075',
    similarity(t.org_normalized, d.district_name_normalized)
FROM tmp_unmapped_orgs t
JOIN ref_districts d 
    ON d.state_abbr = t.state_abbr
    AND t.org_normalized % d.district_name_normalized  -- GIN index
WHERE similarity(t.org_normalized, d.district_name_normalized) >= 0.75;
```

### Phase 3: Medium-Confidence Trigram (0.60-0.75)

```sql
-- Similar to Phase 2, but with lower threshold
WHERE similarity(...) >= 0.60 AND similarity(...) < 0.75
```

---

## Normalization Function

```sql
CREATE OR REPLACE FUNCTION normalize_district_name(org TEXT) RETURNS TEXT AS $$
BEGIN
    org := upper(org);
    org := regexp_replace(org, '\s+', ' ', 'g');
    org := trim(org);
    
    -- Expand abbreviations
    org := regexp_replace(org, '\s+USD$', ' UNIFIED SCHOOL DISTRICT', 'i');
    org := regexp_replace(org, '\s+ISD$', ' INDEPENDENT SCHOOL DISTRICT', 'i');
    org := regexp_replace(org, '\s+CSD$', ' CONSOLIDATED SCHOOL DISTRICT', 'i');
    
    -- Remove common suffixes (order matters)
    org := regexp_replace(org, ' CONSOLIDATED INDEPENDENT SCHOOL DISTRICT$', '', 'i');
    org := regexp_replace(org, ' UNIFIED SCHOOL DISTRICT$', '', 'i');
    org := regexp_replace(org, ' INDEPENDENT SCHOOL DISTRICT$', '', 'i');
    org := regexp_replace(org, ' COUNTY SCHOOL DISTRICT$', '', 'i');
    org := regexp_replace(org, ' SCHOOL DISTRICT$', '', 'i');
    org := regexp_replace(org, ' PUBLIC SCHOOLS?$', '', 'i');
    org := regexp_replace(org, ' COUNTY SCHOOLS?$', '', 'i');
    org := regexp_replace(org, ' CITY SCHOOLS?$', '', 'i');
    org := regexp_replace(org, ' SCHOOLS?$', '', 'i');
    org := regexp_replace(org, ' SCHOOL SYSTEM$', '', 'i');
    org := regexp_replace(org, ' UNIFIED$', '', 'i');
    org := regexp_replace(org, ' ELEMENTARY$', '', 'i');
    org := regexp_replace(org, ' HIGH$', '', 'i');
    org := regexp_replace(org, ' (CITY|COUNTY)$', '', 'i');
    
    RETURN trim(org);
END;
$$ LANGUAGE plpgsql IMMUTABLE;
```

---

## Data Quality Filters

Exclude obvious non-matches before processing:

```sql
CREATE TEMP TABLE tmp_unmapped_orgs AS
SELECT DISTINCT 
    "State" AS state_abbr,
    "Organization" AS organization,
    normalize_district_name("Organization") AS org_normalized
FROM contacts
WHERE "OrganizationType" = 'School Districts'
  AND nces_district_id IS NULL
  -- Data quality filters
  AND "Organization" IS NOT NULL
  AND "Organization" != ''
  AND "Organization" !~ '^[0-9]+$'
  AND "Organization" !~ '^[0-9]'
  AND LENGTH("Organization") >= 3
  AND "Organization" NOT ILIKE '%@%'
  AND "Organization" NOT ILIKE 'http%'
  AND "Organization" NOT ILIKE 'www.%'
  AND "Organization" NOT ILIKE '%university%'
  AND "Organization" NOT ILIKE '%college%'
  AND "Organization" NOT ILIKE '%hospital%'
  AND "Organization" NOT ILIKE '%medical%'
  AND "Organization" NOT ILIKE '%health%';
```

---

## Update Process

### State-by-State Updates

```sql
DO $$
DECLARE
    state_rec RECORD;
BEGIN
    FOR state_rec IN 
        SELECT DISTINCT state_abbr 
        FROM nces_district_mappings 
        WHERE nces_district_id IS NOT NULL
        ORDER BY state_abbr
    LOOP
        UPDATE contacts c
        SET nces_district_id = m.nces_district_id
        FROM nces_district_mappings m
        WHERE c."State" = m.state_abbr
          AND c."Organization" = m.organization
          AND c."OrganizationType" = 'School Districts'
          AND c.nces_district_id IS NULL
          AND c."State" = state_rec.state_abbr;
        
        COMMIT;
    END LOOP;
END;
$$;
```

---

## SQL Scripts Reference

The following scripts are located in `sql_queries_pg/nces_enrichment/`:

### 00 SETUP OPTIMIZED v2.sql

Creates indices, normalization function, and temp tables.

**Key operations:**
- Creates GIN trigram index on `ref_districts.district_name`
- Creates normalization function `normalize_district_name()`
- Adds `district_name_normalized` column to `ref_districts`
- Creates `tmp_unmapped_orgs` temp table with data quality filters

**Runtime:** ~2-3 minutes

### 01 MAPPING OPTIMIZED v2.sql

Runs all three matching phases in a single script.

**Key operations:**
- Phase 1: Normalized exact matching
- Phase 2: Trigram matching ≥0.75
- Phase 3: Trigram matching 0.60-0.75
- Progress tracking updates

**Runtime:** ~5-10 minutes

### 01 MAPPING STATE BY STATE v2.sql

Alternative: processes one state at a time with detailed logging.

**Use when:**
- You need visibility into per-state progress
- You want to pause/resume processing
- You're debugging state-specific issues

**Runtime:** ~10-15 minutes

### 02 UPDATE CONTACTS OPTIMIZED.sql

Updates the `contacts` table with matched NCES IDs.

**Key operations:**
- Creates progress tracking table
- Updates contacts by state
- Reports final counts

**Runtime:** ~15-20 minutes

### 03 ANALYZE UNMATCHED v2.sql

Analyzes organizations that couldn't be matched.

**Key outputs:**
- Unmatched orgs by contact count
- Similarity score distribution
- Pattern analysis (why they didn't match)
- Cleanup suggestions

**Runtime:** ~30 seconds

---

## Troubleshooting

### Common Issues

1. **Low match rate for a state**
   - Check for data quality issues (malformed state abbreviations)
   - Review naming conventions unique to that state (e.g., LA uses "Parish")
   - Consider adding state-specific normalization rules

2. **Slow updates**
   - Verify indices exist and are being used (`EXPLAIN ANALYZE`)
   - Process smaller batches
   - Check for long-running transactions blocking updates

3. **False positive matches**
   - Increase similarity threshold (0.75 → 0.80)
   - Add manual review step for medium-confidence matches

### Query to Find Problem States

```sql
SELECT 
    "State",
    COUNT(*) as total,
    COUNT(nces_district_id) as mapped,
    ROUND(100.0 * COUNT(nces_district_id) / COUNT(*), 1) as pct
FROM contacts
WHERE "OrganizationType" = 'School Districts'
GROUP BY "State"
ORDER BY pct ASC
LIMIT 10;
```

### Query to Find Close Matches Needing Review

```sql
SELECT 
    t.organization,
    t.state_abbr,
    d.district_name as closest_nces,
    similarity(t.org_normalized, d.district_name_normalized) as sim
FROM tmp_unmapped_orgs t
CROSS JOIN LATERAL (
    SELECT district_name, district_name_normalized
    FROM ref_districts
    WHERE state_abbr = t.state_abbr
    ORDER BY similarity(t.org_normalized, district_name_normalized) DESC
    LIMIT 1
) d
WHERE similarity(t.org_normalized, d.district_name_normalized) BETWEEN 0.5 AND 0.75
ORDER BY sim DESC;
```

---

## Refreshing NCES Data

To update the `ref_districts` table with new NCES CCD data:

1. Download latest CCD LEA data from https://nces.ed.gov/ccd/
2. Prepare CSV with columns: `nces_district_id`, `district_name`, `state_abbr`
3. Truncate and reload:

```sql
TRUNCATE ref_districts;

COPY ref_districts (nces_district_id, district_name, state_abbr)
FROM '/path/to/nces_districts.csv' DELIMITER ',' CSV HEADER;

-- Re-compute normalized names
UPDATE ref_districts 
SET district_name_normalized = normalize_district_name(district_name);

-- Re-create indices if needed
```

---

## Performance Benchmarks

| Operation | Time | Notes |
|-----------|------|-------|
| Setup (indices, temp tables) | 2-3 min | One-time |
| Phase 1 (normalized exact) | ~10 sec | Btree index |
| Phase 2 (trigram ≥0.75) | ~2 min | GIN index |
| Phase 3 (trigram 0.60-0.75) | ~5 min | GIN index |
| Update contacts (by state) | ~15 min | Depends on dataset |
| **Total** | **~25 min** | vs 12-24 hours before optimization |

---

## Match Type Confidence Levels

| Match Type | Similarity | Confidence | Action |
|------------|------------|------------|--------|
| `normalized_exact` | 1.0 | Highest | Auto-apply |
| `trigram_075` | ≥0.75 | High | Auto-apply |
| `trigram_060` | 0.60-0.75 | Medium | Review recommended |

---

*Document created: 2026-03-03*
*Last updated: 2026-03-03*
