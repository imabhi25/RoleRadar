-- Public-data audit repair, part 1: the pay rules the salary filter uses now match the ones ingestion and the UI use
-- (ingestion/pay_rules.py, frontend/src/utils/compensation.ts; parity fixtures in tests/fixtures/pay_rules.json):
-- an amount no pay period can reach ($179,300,152 a year) and a range whose top is over 10x its bottom are not pay,
-- ranges ingestion flagged "validation" are not pay, and on-target earnings (commission included) are not a salary.
-- db/migrate.py then runs the shared backfill (db/repair_public_data.py): locations, then pay stated in the posting text.
CREATE OR REPLACE FUNCTION roleradar_pay_ranges(pay jsonb) RETURNS jsonb
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
    parts jsonb := '[]'::jsonb;
    result jsonb := '[]'::jsonb;
    part jsonb;
    tier jsonb;
    lo numeric;
    hi numeric;
    currency text;
    period text;
    multiplier numeric;
    floor_amount numeric;
    ceiling_amount numeric;
BEGIN
    IF jsonb_typeof(pay) <> 'object' OR pay IS NULL THEN RETURN result; END IF;
    -- Ingestion marked the published figures unusable (placeholder, impossible, contradictory period): never pay.
    IF pay ? 'validation' THEN RETURN result; END IF;
    IF jsonb_typeof(pay->'ranges') = 'array' AND jsonb_array_length(pay->'ranges') > 0 THEN
        FOR part IN SELECT value FROM jsonb_array_elements(pay->'ranges') LOOP
            parts := parts || jsonb_build_array((pay - 'ranges') || part);
        END LOOP;
    ELSIF pay ? 'min' OR pay ? 'max' THEN
        parts := parts || jsonb_build_array(pay);
    END IF;
    IF jsonb_typeof(pay->'summaryComponents') = 'array' THEN
        parts := parts || (pay->'summaryComponents');
    END IF;
    IF jsonb_typeof(pay->'compensationTiers') = 'array' THEN
        FOR tier IN SELECT value FROM jsonb_array_elements(pay->'compensationTiers') LOOP
            IF jsonb_typeof(tier->'components') = 'array' THEN parts := parts || (tier->'components'); END IF;
        END LOOP;
    END IF;
    FOR part IN SELECT value FROM jsonb_array_elements(parts) LOOP
        IF jsonb_typeof(part) <> 'object' THEN CONTINUE; END IF;
        IF part ? 'compensationType' AND lower(part->>'compensationType') NOT IN ('salary','basesalary','hourly','wage') THEN CONTINUE; END IF;
        -- On-target earnings include commission: not a salary to filter on.
        IF part->>'kind' = 'ote' THEN CONTINUE; END IF;
        -- Pay the posting wrote for places that are none of this job's locations is not this job's pay.
        IF part->>'scope' = 'none' THEN CONTINUE; END IF;
        currency := upper(COALESCE(part->>'currencyCode', part->>'currency', ''));
        period := lower(COALESCE(part->>'interval', ''));
        multiplier := CASE WHEN period ~ 'year|annual' THEN 1 WHEN period ~ 'month' THEN 12
            WHEN period ~ 'week' THEN 52 WHEN period ~ 'day|daily' THEN 260 WHEN period ~ 'hour' THEN 2080 END;
        IF currency !~ '^[A-Z]{3}$' OR multiplier IS NULL THEN CONTINUE; END IF;
        lo := CASE WHEN COALESCE(part->>'minValue', part->>'min') ~ '^[0-9]+([.][0-9]+)?$'
            THEN COALESCE(part->>'minValue', part->>'min')::numeric END;
        hi := CASE WHEN COALESCE(part->>'maxValue', part->>'max') ~ '^[0-9]+([.][0-9]+)?$'
            THEN COALESCE(part->>'maxValue', part->>'max')::numeric END;
        floor_amount := CASE WHEN multiplier = 1 THEN 1000 WHEN multiplier = 12 THEN 100 WHEN multiplier = 52 THEN 25 ELSE 5 END;
        -- About 3,000,000 a year, expressed in the range's own period (mirrors ingestion/pay_rules.py).
        ceiling_amount := CASE WHEN multiplier = 1 THEN 3000000 WHEN multiplier = 12 THEN 250000 WHEN multiplier = 52 THEN 60000
            WHEN multiplier = 260 THEN 12000 ELSE 1500 END;
        IF (lo IS NULL AND hi IS NULL) OR COALESCE(lo, hi) <= 0 OR COALESCE(hi, lo) <= 0
            OR (lo IS NOT NULL AND hi IS NOT NULL AND lo > hi)
            OR (currency IN ('USD','CAD','AUD','GBP','EUR') AND LEAST(COALESCE(lo,hi),COALESCE(hi,lo)) < floor_amount)
            OR (currency IN ('USD','CAD','AUD','GBP','EUR') AND GREATEST(COALESCE(lo,hi),COALESCE(hi,lo)) > ceiling_amount)
            OR (currency IN ('USD','CAD','AUD','GBP','EUR') AND lo IS NOT NULL AND hi IS NOT NULL AND hi > lo * 10)
        THEN CONTINUE; END IF;
        result := result || jsonb_build_array(jsonb_build_object('currency', currency,
            'min_annual', COALESCE(lo,hi)*multiplier, 'max_annual', COALESCE(hi,lo)*multiplier, 'period', period));
    END LOOP;
    RETURN result;
END $$;

-- pay_ranges is a stored generated column: it is recomputed only when the row is written, so touch every row once.
UPDATE job_postings SET compensation = compensation WHERE compensation IS NOT NULL;
