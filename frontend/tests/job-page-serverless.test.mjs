import { describe, it, expect } from 'vitest';
import {
  generateJobPostingLdJson,
  getHtmlShellTemplate,
  renderVisibleJobHtml,
  safeJsonLdString,
  fetchJob,
  sanitizeJobHtml,
  validateApplyUrl,
  buildSchemaPlace,
  buildBaseSalary,
  resolveMatchingSalaryInterval
} from '../api/job-page.mjs';

describe('Vercel Serverless Function job-page.mjs', () => {
  const sampleJob = {
    job_id: 'ashby:test-123',
    title: 'Staff Security Engineer',
    company: 'Cohere',
    company_website_url: 'https://cohere.com',
    company_logo_url: '/api/company-logos/138',
    location: 'Toronto, Ontario, Canada',
    country: 'Canada',
    workplace_type: 'hybrid',
    role_type: 'full_time',
    posted_at: '2026-10-31T12:00:00Z',
    description: '<p>Cohere is building enterprise AI.</p>',
    company_apply_url: 'https://jobs.ashbyhq.com/cohere/test-123/application',
    compensation: {
      min: 200000,
      max: 250000,
      currency: 'CAD',
      interval: 'year'
    }
  };

  it('generates valid JSON-LD schema matching Google requirements', () => {
    const ld = generateJobPostingLdJson(sampleJob, 'https://roleradar-jobs.vercel.app');
    expect(ld).not.toBeNull();
    expect(ld['@context']).toBe('https://schema.org');
    expect(ld['@type']).toBe('JobPosting');
    expect(ld.title).toBe('Staff Security Engineer');
    expect(ld.hiringOrganization.name).toBe('Cohere');
    expect(ld.hiringOrganization.sameAs).toBe('https://cohere.com');
    expect(ld.hiringOrganization.logo).toBe('https://roleradar-jobs.vercel.app/api/company-logos/138');
    // Does NOT emit TELECOMMUTE without applicantLocationRequirements, preventing Google critical errors
    expect(ld.jobLocationType).toBeUndefined();
    expect(ld.applicantLocationRequirements).toBeUndefined();
    expect(ld.employmentType).toBe('FULL_TIME');
    expect(ld.jobLocation).toEqual({
      '@type': 'Place',
      address: {
        '@type': 'PostalAddress',
        addressLocality: 'Toronto',
        addressRegion: 'Ontario',
        addressCountry: 'Canada'
      }
    });
    expect(ld.baseSalary).toEqual({
      '@type': 'MonetaryAmount',
      currency: 'CAD',
      value: {
        '@type': 'QuantitativeValue',
        minValue: 200000,
        maxValue: 250000,
        unitText: 'YEAR'
      }
    });
  });

  it('does not treat office or job-location countries as proof of remote applicant eligibility', () => {
    const jobWithOffices = {
      ...sampleJob,
      locations: [
        { location: 'Toronto Office', country: 'Canada' },
        { location: 'San Francisco Office', country: 'United States' }
      ]
    };
    const ld = generateJobPostingLdJson(jobWithOffices);
    // Offices must be mapped to jobLocation, NOT applicantLocationRequirements
    expect(ld.jobLocation).toBeDefined();
    expect(ld.applicantLocationRequirements).toBeUndefined();
  });

  it('omits JobPosting markup for remote-only jobs when source does not establish applicant locations', () => {
    // 1. Remote-only job without applicant requirements
    const remoteOnlyNoReqs = {
      ...sampleJob,
      workplace_type: 'remote',
      applicant_location_requirements: undefined
    };
    const ld = generateJobPostingLdJson(remoteOnlyNoReqs);
    expect(ld).toBeNull();

    // 2. Remote-only job with office locations from ATS but no applicant requirements:
    // Omitting TELECOMMUTE must NOT make a remote-only job look office-based.
    // Omit JobPosting entirely rather than misrepresenting the job or inventing details.
    const remoteWithOfficesNoReqs = {
      ...sampleJob,
      workplace_type: 'remote',
      locations: [{ location: 'Toronto Office', country: 'Canada' }],
      applicant_location_requirements: undefined
    };
    const ldOffices = generateJobPostingLdJson(remoteWithOfficesNoReqs);
    expect(ldOffices).toBeNull();
  });

  it('includes remote applicant eligibility and TELECOMMUTE only when the source explicitly supports it', () => {
    const jobWithSourceEligibility = {
      ...sampleJob,
      workplace_type: 'remote',
      applicant_location_requirements: ['Canada', 'United States']
    };
    const ld = generateJobPostingLdJson(jobWithSourceEligibility);
    expect(ld.jobLocationType).toBe('TELECOMMUTE');
    expect(ld.applicantLocationRequirements).toEqual([
      { '@type': 'Country', name: 'Canada' },
      { '@type': 'Country', name: 'United States' }
    ]);
    // For 100% remote jobs, jobLocation is omitted per Google guidelines so it does not appear office-based
    expect(ld.jobLocation).toBeUndefined();

    const singleCountryJob = {
      ...sampleJob,
      workplace_type: 'remote',
      applicant_location_requirements: ['Canada']
    };
    const ldSingle = generateJobPostingLdJson(singleCountryJob);
    expect(ldSingle.jobLocationType).toBe('TELECOMMUTE');
    expect(ldSingle.applicantLocationRequirements).toEqual({
      '@type': 'Country',
      name: 'Canada'
    });
    expect(ldSingle.jobLocation).toBeUndefined();
  });

  it('buildSchemaPlace extracts locality, region, and country from location strings', () => {
    const place = buildSchemaPlace('Toronto, Ontario, Canada', 'Canada');
    expect(place).toEqual({
      '@type': 'Place',
      address: {
        '@type': 'PostalAddress',
        addressLocality: 'Toronto',
        addressRegion: 'Ontario',
        addressCountry: 'Canada'
      }
    });

    const place2 = buildSchemaPlace('Toronto, Ontario', 'Canada');
    expect(place2).toEqual({
      '@type': 'Place',
      address: {
        '@type': 'PostalAddress',
        addressLocality: 'Toronto',
        addressRegion: 'Ontario',
        addressCountry: 'Canada'
      }
    });
  });

  it('buildBaseSalary supports interval from compensation evidence or ranges, but omits periodless pay', () => {
    const compWithEvidence = {
      min: 100000,
      max: 150000,
      currency: 'CAD',
      evidence: 'Base pay CAD $100,000 - $150,000 per year'
    };
    const s = buildBaseSalary(compWithEvidence);
    expect(s?.value.unitText).toBe('YEAR');

    const periodless = {
      min: 81600,
      max: 115200,
      currency: 'CAD',
      evidence: '$81,600 - $115,200 CAD'
    };
    expect(buildBaseSalary(periodless)).toBeUndefined();
  });

  it('ensures a pay period from an unrelated salary range is never applied to the job salary', () => {
    // 1. Multiple ranges where an unrelated range has an interval (e.g. intern hourly rate)
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
    expect(buildBaseSalary(compWithUnrelatedHourlyRange)).toBeUndefined();

    // 2. Unrelated range in evidence mentioning a different rate or role
    const compWithMultipleEvidenceRanges = {
      min: 100000,
      max: 150000,
      currency: 'USD',
      evidence: 'Contractors: $40 - $60 / hr. Full-time base salary: $100,000 - $150,000 USD.'
    };
    expect(resolveMatchingSalaryInterval(compWithMultipleEvidenceRanges)).toBeUndefined();
    expect(buildBaseSalary(compWithMultipleEvidenceRanges)).toBeUndefined();

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
    const salary = buildBaseSalary(compWithMatchedRange);
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
    expect(buildBaseSalary(compWithSingleMismatchedAmount)).toBeUndefined();

    const compWithSingleMismatchedCurrency = {
      min: 81600,
      max: 115200,
      currency: 'CAD',
      ranges: [
        { min: 81600, max: 115200, currency: 'USD', interval: 'year' } // currency differs
      ]
    };
    expect(resolveMatchingSalaryInterval(compWithSingleMismatchedCurrency)).toBeUndefined();
    expect(buildBaseSalary(compWithSingleMismatchedCurrency)).toBeUndefined();

    // 5. Evidence with multiple amounts where currency symbols are NOT repeated
    const compMultiAmountsNoRepeatSymbol = {
      min: 100000,
      max: 150000,
      currency: 'CAD',
      evidence: '$40 - 60 / hr, 100,000 - 150,000 CAD'
    };
    expect(resolveMatchingSalaryInterval(compMultiAmountsNoRepeatSymbol)).toBeUndefined();
    expect(buildBaseSalary(compMultiAmountsNoRepeatSymbol)).toBeUndefined();

    const compMultiAmountsInverted = {
      min: 100000,
      max: 150000,
      currency: 'USD',
      evidence: '$100,000 - 150,000 or 40 - 60 / hr'
    };
    expect(resolveMatchingSalaryInterval(compMultiAmountsInverted)).toBeUndefined();
    expect(buildBaseSalary(compMultiAmountsInverted)).toBeUndefined();

    const compMultiAmountsBonus = {
      min: 100000,
      max: 150000,
      currency: 'USD',
      evidence: 'Base salary $100,000 - 150,000, plus 10,000 bonus / year'
    };
    expect(resolveMatchingSalaryInterval(compMultiAmountsBonus)).toBeUndefined();
    expect(buildBaseSalary(compMultiAmountsBonus)).toBeUndefined();

    // 6. Evidence where period IS clearly tied to the matching amount
    const compTiedPeriod = {
      min: 100000,
      max: 150000,
      currency: 'CAD',
      evidence: '$100,000 - 150,000 CAD per year'
    };
    expect(resolveMatchingSalaryInterval(compTiedPeriod)).toBe('year');
    expect(buildBaseSalary(compTiedPeriod)?.value.unitText).toBe('YEAR');
  });

  it('escapes unsafe JSON-LD script breakout strings', () => {
    const dangerous = {
      description: '</script><script>alert(1)</script>'
    };
    const safeStr = safeJsonLdString(dangerous);
    expect(safeStr).not.toContain('</script>');
    expect(safeStr).toContain('\\u003c/script\\u003e');
  });

  it('renders visible HTML content containing job title, company, location, and description', () => {
    const html = renderVisibleJobHtml(sampleJob);
    expect(html).toContain('Staff Security Engineer');
    expect(html).toContain('Cohere');
    expect(html).toContain('Toronto, Ontario, Canada');
    expect(html).toContain('Cohere is building enterprise AI.');
    expect(html).toContain('Apply on company site');
    expect(html).toContain('https://jobs.ashbyhq.com/cohere/test-123/application');
  });

  it('sanitizes script injection, external scripts, style tags, and iframes using restrictive allow-list', () => {
    const maliciousDesc = `
      <h1>Security Team</h1>
      <script>alert("xss")</script>
      <script src="https://evil.com/xss.js"></script>
      <iframe src="https://evil.com/phishing"></iframe>
      <style>body { display: none !important; }</style>
      <object data="https://evil.com/exploit.swf"></object>
      <embed src="https://evil.com/exploit.swf" />
      <svg><script>alert(1)</script></svg>
      <p>Legitimate job duties and responsibilities.</p>
    `;

    const sanitized = sanitizeJobHtml(maliciousDesc);
    expect(sanitized).not.toContain('<script');
    expect(sanitized).not.toContain('evil.com');
    expect(sanitized).not.toContain('<iframe');
    expect(sanitized).not.toContain('<style');
    expect(sanitized).not.toContain('<object');
    expect(sanitized).not.toContain('<embed');
    expect(sanitized).not.toContain('<svg');
    expect(sanitized).toContain('<h1>Security Team</h1>');
    expect(sanitized).toContain('<p>Legitimate job duties and responsibilities.</p>');
  });

  it('strips all inline event handlers (onclick, onerror, onload, onmouseover, onfocus)', () => {
    const htmlWithHandlers = `
      <p onclick="alert('click')">Click paragraph</p>
      <div onmouseover="evil()" onmouseenter="evil()">Hover division</div>
      <b onload="alert('load')">Bold</b>
      <span onfocus="alert('focus')">Focusable text</span>
      <img src="x" onerror="alert('image fail')" />
    `;

    const sanitized = sanitizeJobHtml(htmlWithHandlers);
    expect(sanitized).not.toContain('onclick');
    expect(sanitized).not.toContain('onmouseover');
    expect(sanitized).not.toContain('onmouseenter');
    expect(sanitized).not.toContain('onload');
    expect(sanitized).not.toContain('onfocus');
    expect(sanitized).not.toContain('onerror');
    expect(sanitized).toContain('<p>Click paragraph</p>');
    expect(sanitized).toContain('<div>Hover division</div>');
    expect(sanitized).toContain('<b>Bold</b>');
  });

  it('safely handles malformed HTML including unclosed tags and nested injection attempts', () => {
    const malformed = `
      <div><p>Unclosed paragraph with <b>bold and <i>italic text
      <<SCRIPT>alert("nested")//<</SCRIPT>
      <a href="https://example.com"">Malformed quote link</a>
      <p>Final paragraph
    `;

    const sanitized = sanitizeJobHtml(malformed);
    expect(sanitized).not.toContain('<script');
    expect(sanitized).not.toContain('alert(');
    expect(sanitized).toContain('Unclosed paragraph with');
    expect(sanitized).toContain('Final paragraph');
    // Verifies tags are properly closed by the AST parser
    expect(sanitized).toContain('</a>');
    expect(sanitized).toContain('</p>');
  });

  it('neutralizes unsafe URLs in anchor hrefs and enforces secure link attributes', () => {
    const linkVectors = `
      <a href="javascript:alert(document.cookie)">JS Cookie</a>
      <a href="data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==">Data URL</a>
      <a href="vbscript:msgbox(1)">VBScript</a>
      <a href="//attacker.com/evil">Protocol Relative</a>
      <a href="https://legitimate.company.com/apply">Legitimate link</a>
    `;

    const sanitized = sanitizeJobHtml(linkVectors);
    expect(sanitized).not.toContain('javascript:');
    expect(sanitized).not.toContain('data:text');
    expect(sanitized).not.toContain('vbscript:');
    expect(sanitized).not.toContain('//attacker.com');
    // Valid link is preserved with security attributes
    expect(sanitized).toContain('href="https://legitimate.company.com/apply"');
    expect(sanitized).toContain('target="_blank"');
    expect(sanitized).toContain('rel="noopener noreferrer"');
  });

  it('strictly validates Apply URLs and rejects unsafe protocols and malformed URLs', () => {
    // Valid URLs
    expect(validateApplyUrl('https://jobs.ashbyhq.com/cohere/apply')).toBe('https://jobs.ashbyhq.com/cohere/apply');
    expect(validateApplyUrl('http://careers.google.com/jobs/123')).toBe('http://careers.google.com/jobs/123');

    // Unsafe protocols
    expect(validateApplyUrl('javascript:alert(document.cookie)')).toBeNull();
    expect(validateApplyUrl('data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==')).toBeNull();
    expect(validateApplyUrl('vbscript:alert(1)')).toBeNull();
    expect(validateApplyUrl('file:///etc/passwd')).toBeNull();

    // Malformed / injection URLs
    expect(validateApplyUrl('https://evil.com" onmouseover="alert(1)')).toBeNull();
    expect(validateApplyUrl('https://example.com/apply with spaces')).toBeNull();
    expect(validateApplyUrl('')).toBeNull();
    expect(validateApplyUrl(null)).toBeNull();
  });

  it('renders safe fallback when Apply URL or description is malicious', () => {
    const maliciousJob = {
      ...sampleJob,
      company_apply_url: 'javascript:alert(1)',
      source_url: 'data:text/html,<script>alert(2)</script>',
      description: '<script>alert(3)</script><p>Clean description text.</p>'
    };

    const rendered = renderVisibleJobHtml(maliciousJob);
    expect(rendered).not.toContain('javascript:alert(1)');
    expect(rendered).not.toContain('data:text/html');
    expect(rendered).not.toContain('<script>');
    expect(rendered).toContain('Clean description text.');
  });

  it('reads current build assets from dist/index.html when available', () => {
    const template = getHtmlShellTemplate();
    expect(template).toContain('<!doctype html>');
    expect(template).toContain('<head>');
    expect(template).toContain('<body>');
  });

  it('fetches and preserves 404 vs 200 status codes correctly', async () => {
    const notFound = await fetchJob('nonexistent-test-id-12345');
    expect(notFound.status).toBe(404);
    expect(notFound.job).toBeNull();
  });

  it('fetches workday job with slashes in ID successfully from production API', async () => {
    const result = await fetchJob('workday:td.wd3/TD_Bank_Careers/Software-Engineer-II_R_1516370');
    expect(result.status).toBe(200);
    expect(result.job).not.toBeNull();
    expect(result.job.job_id).toBe('workday:td.wd3/TD_Bank_Careers/Software-Engineer-II_R_1516370');
    expect(result.job.company).toBe('TD');
  });

  it('handler handles slash job IDs from rewritten jobId query parameter', async () => {
    const defaultExport = (await import('../api/job-page.mjs')).default;
    let statusCode = null;
    const headers = {};
    let body = '';

    const req = {
      url: '/api/job-page?jobId=workday:td.wd3/TD_Bank_Careers/Software-Engineer-II_R_1516370',
      headers: { host: 'roleradar-jobs.vercel.app' }
    };
    const res = {
      set statusCode(val) { statusCode = val; },
      get statusCode() { return statusCode; },
      setHeader(name, val) { headers[name.toLowerCase()] = val; },
      end(chunk) { if (chunk) body += chunk; }
    };

    await defaultExport(req, res);
    expect(statusCode).toBe(200);
    expect(headers['content-type']).toContain('text/html');
    expect(body).toContain('TD');
    expect(body).toContain('Software-Engineer-II_R_1516370');
    expect(body).toContain('application/ld+json');
  });

  it('handler returns 404 with noindex header for nonexistent jobs', async () => {
    const defaultExport = (await import('../api/job-page.mjs')).default;
    let statusCode = null;
    const headers = {};
    let body = '';

    const req = {
      url: '/api/job-page?jobId=nonexistent-job-xyz',
      headers: { host: 'roleradar-jobs.vercel.app' }
    };
    const res = {
      set statusCode(val) { statusCode = val; },
      get statusCode() { return statusCode; },
      setHeader(name, val) { headers[name.toLowerCase()] = val; },
      end(chunk) { if (chunk) body += chunk; }
    };

    await defaultExport(req, res);
    expect(statusCode).toBe(404);
    expect(headers['x-robots-tag']).toBe('noindex, nofollow');
    expect(body).toContain('Job No Longer Available');
  });

  it('handler returns 503 with Retry-After and without noindex on temporary upstream failure', async () => {
    const defaultExport = (await import('../api/job-page.mjs')).default;
    let statusCode = null;
    const headers = {};
    let body = '';

    // Mock global.fetch to simulate upstream 500
    const originalFetch = global.fetch;
    global.fetch = async () => ({
      status: 500,
      json: async () => ({ error: 'Internal Server Error' })
    });

    try {
      const req = {
        url: '/api/job-page?jobId=temp-error-job',
        headers: { host: 'roleradar-jobs.vercel.app' }
      };
      const res = {
        set statusCode(val) { statusCode = val; },
        get statusCode() { return statusCode; },
        setHeader(name, val) { headers[name.toLowerCase()] = val; },
        end(chunk) { if (chunk) body += chunk; }
      };

      await defaultExport(req, res);
      expect(statusCode).toBe(503);
      expect(headers['retry-after']).toBe('60');
      expect(headers['x-robots-tag']).toBeUndefined();
      expect(body).toContain('Service Temporarily Unavailable');
    } finally {
      global.fetch = originalFetch;
    }
  });
});
