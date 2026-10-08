-- =============================================================================
-- Migration 004: Expand Location Column Length to TEXT
-- Phase 6B.2 Additive Migration for Jobber
-- =============================================================================

-- Expand locations.location from VARCHAR(255) to TEXT to support legitimate
-- long multi-location strings from vendor ATS feeds (e.g. Datadog Greenhouse).
-- Preserves existing NOT NULL, existing data, and UNIQUE (location, country) constraint.

ALTER TABLE locations
    ALTER COLUMN location TYPE TEXT;
