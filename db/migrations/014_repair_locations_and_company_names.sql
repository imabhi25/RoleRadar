-- Marker migration. db/migrate.py re-runs db/repair_public_data.py for this version so stored locations
-- (e.g. "Remote - , Canada" left over from before the normalizer fix) are re-normalised with the current rules,
-- and restores the configured spelling of company names (e.g. "OpenAI", not "Openai").
SELECT 1;
