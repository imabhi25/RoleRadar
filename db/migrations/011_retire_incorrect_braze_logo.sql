-- The old Braze SVG contains Delivery Hero artwork. Retire the known local URL
-- and exact copied bytes, including durable /api/company-logos caches. Leave
-- independently sourced replacement assets and other employers untouched.
UPDATE companies
SET logo_url = NULL,
    logo_source_url = NULL,
    logo_status = 'unresolved',
    logo_data = NULL,
    logo_content_type = NULL,
    website_url = COALESCE(website_url, 'https://www.braze.com'),
    updated_at = NOW()
WHERE LOWER(TRIM(name)) ~ '^braze([,. ]+(inc|incorporated|llc|ltd|limited|corp|corporation)\.?)?$'
  AND (logo_url = '/logos/braze.svg'
       OR md5(logo_data) = 'ec90fbc8377806180d1310252a084b54');
