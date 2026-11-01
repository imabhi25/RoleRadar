import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import type { JobDetail } from '../src/api/client';
import {
  buildJobPostingSchema,
  buildSchemaBaseSalary,
  buildSchemaPlace,
  mapEmploymentType,
  safeJsonLdString,
  resolveApplicantLocationRequirements,
  resolveMatchingSalaryInterval
} from '../src/utils/jobPostingSchema';
import { updateJobStructuredData } from '../src/utils/injectStructuredData';
import { sanitizeJobHtml, validateApplyUrl } from '../src/utils/sanitizeJobHtml';
import { parseAppRoute } from '../src/utils/appRoute';
import { parseUrlSearch } from '../src/utils/urlState';

describe('JobPosting Schema.org Structured Data Generation', () => {
  const baseJob: JobDetail = {
    job_id: 'ashby:cb981ecd-a161-482c-8d8e-5f19bb6e7fdd',
    title: 'Senior Security Engineer',
    company: 'Cohere',
    company_website_url: 'https://cohere.com',
    company_logo_url: '/api/company-logos/138',
    location: 'Toronto, Ontario, Canada',
    country: 'Canada',
    workplace_type: 'hybrid',
    role_type: 'full_time',
    source_name: 'ashby',
    skills: [],
    posted_at: '2026-10-31T15:33:10.669000Z',
    company_apply_url: 'https://jobs.ashbyhq.com/cohere/cb981ecd/application',
    description: '<p>Cohere is the leading security-first enterprise AI company. We build cutting-edge models.</p><p>Requirements: 5+ years experience in AppSec.</p>',
    compensation: {
      summaryComponents: [
        {
          compensationType: 'Salary',
          currencyCode: 'CAD',
          interval: '1 YEAR',
          minValue: 260000,
          maxValue: 310000
        }
      ]
    }
  };

  it('generates fully compliant Schema.org JobPosting object with all required and recommended Google fields', () => {
    const schema = buildJobPostingSchema(baseJob, { siteUrl: 'https://roleradar-jobs.vercel.app' });
    expect(schema).not.toBeNull();
    expect(schema!['@context']).toBe('https://schema.org');
    expect(schema!['@type']).toBe('JobPosting');
    expect(schema!.title).toBe('Senior Security Engineer');
    expect(schema!.datePosted).toBe('2026-10-31T15:33:10.669Z');
    expect(schema!.description).toContain('Cohere is the leading security-first enterprise AI company');

    // Organization
    expect(schema!.hiringOrganization).toEqual({
      '@type': 'Organization',
      name: 'Cohere',
      sameAs: 'https://cohere.com',
      logo: 'https://roleradar-jobs.vercel.app/api/company-logos/138'
    });

    // Remote Telecommute requirements: generic job.country is NOT inferred as applicant restriction.
    // Omit TELECOMMUTE when source does not support applicant restrictions to prevent Google critical error
    expect(schema!.jobLocationType).toBeUndefined();
    expect(schema!.applicantLocationRequirements).toBeUndefined();

    // Employment type
    expect(schema!.employmentType).toBe('FULL_TIME');

    // Identifier
    expect(schema!.identifier).toEqual({
      '@type': 'PropertyValue',
      name: 'Cohere',
      value: 'ashby:cb981ecd-a161-482c-8d8e-5f19bb6e7fdd'
    });

    // Base salary
    expect(schema!.baseSalary).toEqual({
      '@type': 'MonetaryAmount',
      currency: 'CAD',
      value: {
        '@type': 'QuantitativeValue',
        minValue: 260000,
        maxValue: 310000,
        unitText: 'YEAR'
      }
    });
  });

  it('safely escapes script breakout tags in safeJsonLdString', () => {
    const malicious = {
      description: '</script><script>alert("xss")</script>',
      title: 'Hacker & Developer'
    };
    const serialized = safeJsonLdString(malicious);
    expect(serialized).not.toContain('</script>');
    expect(serialized).toContain('\\u003c/script\\u003e');
    expect(serialized).toContain('\\u0026');
  });

  it('does not treat office or job-location countries as proof of remote applicant eligibility', () => {
    // 1. Generic country on remote job is NOT proof of remote applicant eligibility
    expect(resolveApplicantLocationRequirements(baseJob)).toBeUndefined();

    // 2. Office / hiring location countries on remote jobs are NOT proof of remote applicant eligibility
    const jobWithOffices = {
      ...baseJob,
      locations: [
        { location: 'Toronto', country: 'Canada' },
        { location: 'San Francisco', country: 'United States' }
      ]
    };
    expect(resolveApplicantLocationRequirements(jobWithOffices)).toBeUndefined();

    // 3. Non-remote job has no applicant location requirements
    const onSiteJob = { ...baseJob, workplace_type: 'on_site' };
    expect(resolveApplicantLocationRequirements(onSiteJob)).toBeUndefined();
  });

  it('omits JobPosting markup for remote-only jobs when source does not establish applicant locations', () => {
    // 1. Remote-only job without applicant requirements
    const remoteOnlyNoReqs: JobDetail = {
      ...baseJob,
      workplace_type: 'remote'
    };
    const schema = buildJobPostingSchema(remoteOnlyNoReqs);
    expect(schema).toBeNull();

    // 2. Remote-only job with office locations from ATS but no applicant requirements:
    // Omitting TELECOMMUTE must NOT make a remote-only job look office-based.
    // Omit JobPosting entirely rather than misrepresenting the job or inventing details.
    const remoteWithOfficesNoReqs: JobDetail = {
      ...baseJob,
      workplace_type: 'remote',
      locations: [{ location: 'Toronto, Ontario, Canada', country: 'Canada' }]
    };
    const schemaWithOffices = buildJobPostingSchema(remoteWithOfficesNoReqs);
    expect(schemaWithOffices).toBeNull();
  });

  it('includes remote applicant eligibility only when the source explicitly supports it', () => {
    const explicitMulti = {
      ...baseJob,
      workplace_type: 'remote',
      applicant_location_requirements: ['Canada', 'United States']
    } as unknown as JobDetail;

    const reqMulti = resolveApplicantLocationRequirements(explicitMulti);
    expect(reqMulti).toEqual([
      { '@type': 'Country', name: 'Canada' },
      { '@type': 'Country', name: 'United States' }
    ]);

    const explicitSingle = {
      ...baseJob,
      workplace_type: 'remote',
      applicant_location_requirements: ['Canada']
    } as unknown as JobDetail;

    const reqSingle = resolveApplicantLocationRequirements(explicitSingle);
    expect(reqSingle).toEqual([{ '@type': 'Country', name: 'Canada' }]);

    const schema = buildJobPostingSchema(explicitSingle);
    expect(schema!.jobLocationType).toBe('TELECOMMUTE');
    expect(schema!.applicantLocationRequirements).toEqual({
      '@type': 'Country',
      name: 'Canada'
    });
    // For 100% remote jobs, jobLocation is omitted per Google guidelines so it does not appear office-based
    expect(schema!.jobLocation).toBeUndefined();
  });

  it('omits baseSalary when compensation is null, unverified, or invalid', () => {
    const jobWithoutPay = { ...baseJob, compensation: null };
    const schema = buildJobPostingSchema(jobWithoutPay);
    expect(schema!.baseSalary).toBeUndefined();

    const jobWithInvalidPay = {
      ...baseJob,
      compensation: {
        min: 200000,
        max: 100000, // inverted min > max
        currency: 'USD',
        interval: 'year'
      }
    };
    const schemaInvalid = buildJobPostingSchema(jobWithInvalidPay);
    expect(schemaInvalid!.baseSalary).toBeUndefined();
  });

  it('handles Greenhouse/Lever single fixed salary (min === max)', () => {
    const comp = {
      min: 191100,
      max: 191100,
      currency: 'CAD',
      interval: 'year'
    };
    const salary = buildSchemaBaseSalary(comp);
    expect(salary).toEqual({
      '@type': 'MonetaryAmount',
      currency: 'CAD',
      value: {
        '@type': 'QuantitativeValue',
        value: 191100,
        unitText: 'YEAR'
      }
    });
  });

  it('maps employment types correctly according to Schema.org standard values', () => {
    expect(mapEmploymentType('full_time')).toBe('FULL_TIME');
    expect(mapEmploymentType('part_time')).toBe('PART_TIME');
    expect(mapEmploymentType('contract')).toBe('CONTRACTOR');
    expect(mapEmploymentType('contractor')).toBe('CONTRACTOR');
    expect(mapEmploymentType('temporary')).toBe('TEMPORARY');
    expect(mapEmploymentType('internship')).toBe('INTERN');
    expect(mapEmploymentType('co_op')).toBe('INTERN');
    expect(mapEmploymentType('unknown_type')).toBeUndefined();
    expect(mapEmploymentType(null)).toBeUndefined();
  });

  it('builds SchemaPlace objects with locality, region, country, and street address', () => {
    const place1 = buildSchemaPlace('Toronto, Ontario, Canada');
    expect(place1).toEqual({
      '@type': 'Place',
      address: {
        '@type': 'PostalAddress',
        addressLocality: 'Toronto',
        addressRegion: 'Ontario',
        addressCountry: 'Canada'
      }
    });

    const place2 = buildSchemaPlace('Canada');
    expect(place2).toEqual({
      '@type': 'Place',
      address: {
        '@type': 'PostalAddress',
        addressCountry: 'Canada'
      }
    });

    const placeWithProvinceAndDefaultCountry = buildSchemaPlace('Toronto, Ontario', 'Canada');
    expect(placeWithProvinceAndDefaultCountry).toEqual({
      '@type': 'Place',
      address: {
        '@type': 'PostalAddress',
        addressLocality: 'Toronto',
        addressRegion: 'Ontario',
        addressCountry: 'Canada'
      }
    });

    const placeWithStreet = buildSchemaPlace('66 Wellington St W, Toronto, Ontario, Canada');
    expect(placeWithStreet).toEqual({
      '@type': 'Place',
      address: {
        '@type': 'PostalAddress',
        streetAddress: '66 Wellington St W',
        addressLocality: 'Toronto',
        addressRegion: 'Ontario',
        addressCountry: 'Canada'
      }
    });
  });

  it('supports pay period from evidence or ranges when top-level interval is missing, but omits periodless pay', () => {
    // 1. Evidence states "per year"
    const compWithEvidence = {
      min: 133000,
      max: 183000,
      currency: 'CAD',
      evidence: 'CAN base pay range per year: CAD $133,000 - $183,000.'
    };
    const salaryWithEvidence = buildSchemaBaseSalary(compWithEvidence);
    expect(salaryWithEvidence).toEqual({
      '@type': 'MonetaryAmount',
      currency: 'CAD',
      value: {
        '@type': 'QuantitativeValue',
        minValue: 133000,
        maxValue: 183000,
        unitText: 'YEAR'
      }
    });

    // 2. Evidence states hourly
    const compHourly = {
      min: 45,
      max: 65,
      currency: 'USD',
      evidence: '$45 - $65 / hr'
    };
    const salaryHourly = buildSchemaBaseSalary(compHourly);
    expect(salaryHourly?.value.unitText).toBe('HOUR');

    // 3. Periodless compensation without stated period (like Workday TD posting)
    // Never guesses annual or hourly; omits baseSalary to prevent invalid schema or false claims
    const periodlessComp = {
      min: 81600,
      max: 115200,
      currency: 'CAD',
      evidence: '$81,600 - $115,200 CAD'
    };
    expect(buildSchemaBaseSalary(periodlessComp)).toBeUndefined();
  });

  it('ensures a pay period from an unrelated salary range is never applied to the job salary', () => {
    // 1. Multiple ranges where an unrelated range has an interval (e.g. intern hourly rate)
    // The primary role pay is $81,600 - $115,200 (periodless), but a second range specifies "hour"
    const compWithUnrelatedHourlyRange = {
      min: 81600,
      max: 115200,
      currency: 'CAD',
      ranges: [
        { min: 81600, max: 115200, currency: 'CAD' }, // primary role range: no interval
        { min: 35, max: 50, currency: 'CAD', interval: 'hour' } // unrelated intern rate
      ]
    };
    expect(resolveMatchingSalaryInterval(compWithUnrelatedHourlyRange)).toBeUndefined();
    expect(buildSchemaBaseSalary(compWithUnrelatedHourlyRange)).toBeUndefined();

    // 2. Unrelated range in evidence mentioning a different rate or role
    const compWithMultipleEvidenceRanges = {
      min: 100000,
      max: 150000,
      currency: 'USD',
      evidence: 'Contractors: $40 - $60 / hr. Full-time base salary: $100,000 - $150,000 USD.'
    };
    // Must NOT mistakenly apply "/ hr" to the $100,000 - $150,000 full-time salary
    expect(resolveMatchingSalaryInterval(compWithMultipleEvidenceRanges)).toBeUndefined();
    expect(buildSchemaBaseSalary(compWithMultipleEvidenceRanges)).toBeUndefined();

    // 3. Matched range correctly applies its own interval
    const compWithMatchedRange = {
      min: 120000,
      max: 150000,
      currency: 'USD',
      ranges: [
        { min: 120000, max: 150000, currency: 'USD', interval: 'year' },
        { min: 40, max: 60, currency: 'USD', interval: 'hour' }
      ]
    };
    expect(resolveMatchingSalaryInterval(compWithMatchedRange)).toBe('year');
    const salary = buildSchemaBaseSalary(compWithMatchedRange);
    expect(salary?.value.unitText).toBe('YEAR');
    expect(salary?.value.minValue).toBe(120000);
    expect(salary?.value.maxValue).toBe(150000);

    // 4. Single mismatched range: fallback is removed unless amounts and currency match
    const compWithSingleMismatchedAmount = {
      min: 81600,
      max: 115200,
      currency: 'CAD',
      ranges: [
        { min: 35, max: 50, currency: 'CAD', interval: 'hour' } // amounts differ
      ]
    };
    expect(resolveMatchingSalaryInterval(compWithSingleMismatchedAmount)).toBeUndefined();
    expect(buildSchemaBaseSalary(compWithSingleMismatchedAmount)).toBeUndefined();

    const compWithSingleMismatchedCurrency = {
      min: 81600,
      max: 115200,
      currency: 'CAD',
      ranges: [
        { min: 81600, max: 115200, currency: 'USD', interval: 'year' } // currency differs
      ]
    };
    expect(resolveMatchingSalaryInterval(compWithSingleMismatchedCurrency)).toBeUndefined();
    expect(buildSchemaBaseSalary(compWithSingleMismatchedCurrency)).toBeUndefined();

    // 5. Evidence with multiple amounts where currency symbols are NOT repeated
    // $ only precedes the first rate; 60, 100,000, and 150,000 have no currency symbol
    const compMultiAmountsNoRepeatSymbol = {
      min: 100000,
      max: 150000,
      currency: 'CAD',
      evidence: '$40 - 60 / hr, 100,000 - 150,000 CAD'
    };
    // / hr is tied to 40 - 60, NOT to 100,000 - 150,000; salary markup must be omitted
    expect(resolveMatchingSalaryInterval(compMultiAmountsNoRepeatSymbol)).toBeUndefined();
    expect(buildSchemaBaseSalary(compMultiAmountsNoRepeatSymbol)).toBeUndefined();

    const compMultiAmountsInverted = {
      min: 100000,
      max: 150000,
      currency: 'USD',
      evidence: '$100,000 - 150,000 or 40 - 60 / hr'
    };
    expect(resolveMatchingSalaryInterval(compMultiAmountsInverted)).toBeUndefined();
    expect(buildSchemaBaseSalary(compMultiAmountsInverted)).toBeUndefined();

    const compMultiAmountsBonus = {
      min: 100000,
      max: 150000,
      currency: 'USD',
      evidence: 'Base salary $100,000 - 150,000, plus 10,000 bonus / year'
    };
    expect(resolveMatchingSalaryInterval(compMultiAmountsBonus)).toBeUndefined();
    expect(buildSchemaBaseSalary(compMultiAmountsBonus)).toBeUndefined();

    // 6. Evidence where period IS clearly tied to the matching amount
    const compTiedPeriod = {
      min: 100000,
      max: 150000,
      currency: 'CAD',
      evidence: '$100,000 - 150,000 CAD per year'
    };
    expect(resolveMatchingSalaryInterval(compTiedPeriod)).toBe('year');
    expect(buildSchemaBaseSalary(compTiedPeriod)?.value.unitText).toBe('YEAR');
  });
});

describe('Sanitization and Security Utilities', () => {
  it('sanitizes script injection, styles, and iframes using maintained server-compatible sanitizer', () => {
    const maliciousHtml = '<p>Great job</p><script>alert("xss")</script><iframe src="https://evil.com"></iframe><style>body{display:none}</style>';
    const sanitized = sanitizeJobHtml(maliciousHtml);
    expect(sanitized).not.toContain('<script');
    expect(sanitized).not.toContain('<iframe');
    expect(sanitized).not.toContain('<style');
    expect(sanitized).toContain('<p>Great job</p>');
  });

  it('strips inline event handlers completely', () => {
    const htmlWithEvents = '<p onclick="alert(1)">Click</p><span onmouseover="alert(2)" onerror="alert(3)">Text</span>';
    const sanitized = sanitizeJobHtml(htmlWithEvents);
    expect(sanitized).not.toContain('onclick');
    expect(sanitized).not.toContain('onmouseover');
    expect(sanitized).not.toContain('onerror');
    expect(sanitized).toContain('<p>Click</p>');
    expect(sanitized).toContain('<span>Text</span>');
  });

  it('safely normalizes and repairs malformed HTML', () => {
    const malformed = '<div><p>Unclosed paragraph<b>bold and unclosed<a href="https://example.com"">link</a>';
    const sanitized = sanitizeJobHtml(malformed);
    expect(sanitized).toContain('Unclosed paragraph');
    expect(sanitized).toContain('</a>');
    expect(sanitized).toContain('</b>');
    expect(sanitized).toContain('</p>');
  });

  it('neutralizes unsafe URLs in links and validates Apply URLs', () => {
    const badLinks = '<a href="javascript:alert(1)">Bad JS</a><a href="data:text/html,bad">Bad Data</a><a href="https://good.com">Good</a>';
    const sanitized = sanitizeJobHtml(badLinks);
    expect(sanitized).not.toContain('javascript:');
    expect(sanitized).not.toContain('data:text');
    expect(sanitized).toContain('href="https://good.com"');
    expect(sanitized).toContain('target="_blank"');
    expect(sanitized).toContain('rel="noopener noreferrer"');

    expect(validateApplyUrl('https://example.com/apply')).toBe('https://example.com/apply');
    expect(validateApplyUrl('http://example.org/apply')).toBe('http://example.org/apply');
    expect(validateApplyUrl('javascript:alert(1)')).toBeNull();
    expect(validateApplyUrl('data:text/html,xss')).toBeNull();
    expect(validateApplyUrl('vbscript:msgbox')).toBeNull();
    expect(validateApplyUrl('')).toBeNull();
    expect(validateApplyUrl(null)).toBeNull();
  });

  it('routes /jobs/:jobId to jobs view and parses target jobId', () => {
    const path = '/jobs/ashby%3Acb981ecd-a161-482c-8d8e-5f19bb6e7fdd';
    const route = parseAppRoute(path, '');
    expect(route.view).toBe('jobs');
    expect(route.company).toBeNull();

    const parsedState = parseUrlSearch('', path);
    expect(parsedState.jobId).toBe('ashby:cb981ecd-a161-482c-8d8e-5f19bb6e7fdd');
  });
});

describe('updateJobStructuredData DOM injection and cleanup', () => {
  beforeEach(() => {
    document.head.innerHTML = '';
  });

  afterEach(() => {
    document.head.innerHTML = '';
  });

  const mockJob: JobDetail = {
    job_id: 'test:123',
    title: 'Full Stack Engineer',
    company: 'Acme',
    location: 'Remote',
    country: 'United States',
    workplace_type: 'remote',
    role_type: 'full_time',
    source_name: 'test',
    skills: [],
    posted_at: '2026-10-30T12:00:00Z',
    applicant_location_requirements: ['United States'],
    description: '<p>Acme is looking for a software engineer with TypeScript skills.</p>'
  };

  it('injects JobPosting JSON-LD script and canonical link when job is ready', () => {
    const cleanupFn = updateJobStructuredData('ready', mockJob, 'https://roleradar-jobs.vercel.app');
    const script = document.getElementById('role-radar-job-posting-ld-json') as HTMLScriptElement;
    const canonical = document.getElementById('role-radar-canonical-link') as HTMLLinkElement;
    expect(script).not.toBeNull();
    expect(script.type).toBe('application/ld+json');
    expect(canonical).not.toBeNull();
    expect(canonical.href).toBe('https://roleradar-jobs.vercel.app/jobs/test%3A123');

    const parsed = JSON.parse(script.textContent || '{}');
    expect(parsed.title).toBe('Full Stack Engineer');
    expect(parsed.hiringOrganization.name).toBe('Acme');

    cleanupFn();
    expect(document.getElementById('role-radar-job-posting-ld-json')).toBeNull();
    expect(document.getElementById('role-radar-canonical-link')).toBeNull();
  });

  it('injects noindex and removes structured data when job is unavailable (expired / 404)', () => {
    // First ready
    updateJobStructuredData('ready', mockJob, 'https://roleradar-jobs.vercel.app');
    expect(document.getElementById('role-radar-job-posting-ld-json')).not.toBeNull();

    // Now unavailable
    const cleanupFn = updateJobStructuredData('unavailable', null, 'https://roleradar-jobs.vercel.app');
    expect(document.getElementById('role-radar-job-posting-ld-json')).toBeNull();
    expect(document.getElementById('role-radar-canonical-link')).toBeNull();

    const noindex = document.getElementById('role-radar-job-noindex') as HTMLMetaElement;
    expect(noindex).not.toBeNull();
    expect(noindex.name).toBe('robots');
    expect(noindex.content).toBe('noindex, nofollow');

    cleanupFn();
    expect(document.getElementById('role-radar-job-noindex')).toBeNull();
  });

  it('reuses pre-existing server-rendered JSON-LD script and prevents duplicate JobPosting items in head', () => {
    // Simulate pre-existing server-rendered script tag from SSR
    const serverScript = document.createElement('script');
    serverScript.id = 'role-radar-job-posting-ld-json';
    serverScript.type = 'application/ld+json';
    serverScript.textContent = JSON.stringify({ '@type': 'JobPosting', title: 'Old SSR Title' });
    document.head.appendChild(serverScript);

    // Call updateJobStructuredData
    const cleanupFn = updateJobStructuredData('ready', mockJob, 'https://roleradar-jobs.vercel.app');
    
    // Verify there is strictly ONE script tag, not two
    const scripts = document.querySelectorAll('script[type="application/ld+json"]');
    expect(scripts.length).toBe(1);
    expect(scripts[0].id).toBe('role-radar-job-posting-ld-json');
    const parsed = JSON.parse(scripts[0].textContent || '{}');
    expect(parsed.title).toBe('Full Stack Engineer');

    cleanupFn();
    expect(document.querySelectorAll('script[type="application/ld+json"]').length).toBe(0);
  });

  it('omits structured data when job is remote without verified applicant requirements', () => {
    const remoteNoReqs: JobDetail = {
      ...mockJob,
      applicant_location_requirements: undefined
    };
    const cleanupFn = updateJobStructuredData('ready', remoteNoReqs, 'https://roleradar-jobs.vercel.app');
    expect(document.getElementById('role-radar-job-posting-ld-json')).toBeNull();
    // Canonical link is still provided for human visitors
    expect(document.getElementById('role-radar-canonical-link')).not.toBeNull();
    cleanupFn();
  });
});
