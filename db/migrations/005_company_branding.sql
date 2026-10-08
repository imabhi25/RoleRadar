-- =============================================================================
-- Migration 005: Company-Level Branding and Logo System
-- Phase 6C Additive Migration for Jobber
-- =============================================================================

-- 1. Extend companies table with authentic logo and website metadata
ALTER TABLE companies
    ADD COLUMN IF NOT EXISTS logo_url VARCHAR(500),
    ADD COLUMN IF NOT EXISTS logo_source_url VARCHAR(500),
    ADD COLUMN IF NOT EXISTS logo_status VARCHAR(50) NOT NULL DEFAULT 'unresolved',
    ADD COLUMN IF NOT EXISTS website_url VARCHAR(500),
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP;

-- 2. Validate logo_status constraint
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'check_company_logo_status'
    ) THEN
        ALTER TABLE companies
            ADD CONSTRAINT check_company_logo_status
            CHECK (logo_status IN ('verified', 'unresolved', 'custom'));
    END IF;
END $$;

-- 3. Query performance index for logo status
CREATE INDEX IF NOT EXISTS idx_companies_logo_status
    ON companies(logo_status);

-- 4. Initial backfill of priority verified companies if already present
UPDATE companies SET logo_url = '/logos/carta.png', logo_source_url = 'https://s3-recruiting.cdn.greenhouse.io/external_greenhouse_job_boards/logos/400/110/100/original/CartaLogo_Black_(1).png', logo_status = 'verified', website_url = 'https://carta.com', updated_at = NOW() WHERE LOWER(name) = 'carta';
UPDATE companies SET logo_url = '/logos/faire.png', logo_source_url = 'https://www.faire.com/apple-touch-icon.png', logo_status = 'verified', website_url = 'https://faire.com', updated_at = NOW() WHERE LOWER(name) = 'faire';
UPDATE companies SET logo_url = '/logos/figma.svg', logo_source_url = 'https://upload.wikimedia.org/wikipedia/commons/3/33/Figma-logo.svg', logo_status = 'verified', website_url = 'https://figma.com', updated_at = NOW() WHERE LOWER(name) = 'figma';
UPDATE companies SET logo_url = '/logos/plaid.png', logo_source_url = 'https://plaid.com/assets/img/favicons/apple-touch-icon.png', logo_status = 'verified', website_url = 'https://plaid.com', updated_at = NOW() WHERE LOWER(name) = 'plaid';
UPDATE companies SET logo_url = '/logos/pointclickcare.png', logo_source_url = 'https://lever-client-logos.s3.us-west-2.amazonaws.com/458c92e4-e8e4-4bcb-b79a-4d9663eaf4b8-1760615686801.png', logo_status = 'verified', website_url = 'https://pointclickcare.com', updated_at = NOW() WHERE LOWER(name) = 'pointclickcare';
UPDATE companies SET logo_url = '/logos/scaleai.svg', logo_source_url = 'https://scale.com/favicon.svg', logo_status = 'verified', website_url = 'https://scale.com', updated_at = NOW() WHERE LOWER(name) IN ('scale ai', 'scale');
UPDATE companies SET logo_url = '/logos/stabilityai.png', logo_source_url = 'https://images.squarespace-cdn.com/content/v1/6213c340453c3f502425776e/a3485d53-7e65-42b5-bc62-e2e55f8409b9/stability-ai-white-dot-desktop.png', logo_status = 'verified', website_url = 'https://stability.ai', updated_at = NOW() WHERE LOWER(name) = 'stability ai';
UPDATE companies SET logo_url = '/logos/waabi.png', logo_source_url = 'https://lever-client-logos.s3.us-west-2.amazonaws.com/99d3bf4f-9035-4cb6-9d7c-51c8ad9412a8-1757943910265.png', logo_status = 'verified', website_url = 'https://waabi.ai', updated_at = NOW() WHERE LOWER(name) = 'waabi';
UPDATE companies SET logo_url = '/logos/linear.svg', logo_source_url = 'https://simpleicons.org/', logo_status = 'verified', website_url = 'https://linear.app', updated_at = NOW() WHERE LOWER(name) = 'linear';
UPDATE companies SET logo_url = '/logos/openai.svg', logo_source_url = 'https://simpleicons.org/', logo_status = 'verified', website_url = 'https://openai.com', updated_at = NOW() WHERE LOWER(name) = 'openai';
UPDATE companies SET logo_url = '/logos/palantir.svg', logo_source_url = 'https://simpleicons.org/', logo_status = 'verified', website_url = 'https://palantir.com', updated_at = NOW() WHERE LOWER(name) = 'palantir';
UPDATE companies SET logo_url = '/logos/notion.svg', logo_source_url = 'https://simpleicons.org/', logo_status = 'verified', website_url = 'https://notion.so', updated_at = NOW() WHERE LOWER(name) = 'notion';
UPDATE companies SET logo_url = '/logos/stripe.svg', logo_source_url = 'https://simpleicons.org/', logo_status = 'verified', website_url = 'https://stripe.com', updated_at = NOW() WHERE LOWER(name) = 'stripe';
