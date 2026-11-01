import { describe, it, expect, vi } from 'vitest';
import {
  escapeXml,
  isJobEligibleForMarkup,
  fetchEligibleJobs,
  generateSitemapXml,
  default as sitemapHandler
} from '../api/sitemap.mjs';

describe('Vercel Serverless Function sitemap.mjs', () => {
  describe('XML escaping', () => {
    it('escapes XML special characters correctly', () => {
      expect(escapeXml('https://example.com/jobs/A&B<C>"D\'E')).toBe(
        'https://example.com/jobs/A&amp;B&lt;C&gt;&quot;D&apos;E'
      );
      expect(escapeXml(null)).toBe('');
      expect(escapeXml(undefined)).toBe('');
    });
  });

  describe('Markup eligibility filtering against actual API fields (isJobEligibleForMarkup)', () => {
    it('approves active non-remote jobs with physical locations', () => {
      const job = {
        job_id: 'job-1',
        title: 'Platform Engineer',
        company: 'Scotiabank',
        posted_at: '2026-11-01T00:00:00Z',
        workplace_type: 'hybrid',
        location: 'Toronto, Ontario, Canada',
        locations: [{ country: 'Canada', location: 'Toronto, Ontario, Canada' }]
      };
      expect(isJobEligibleForMarkup(job)).toBe(true);
    });

    it('rejects remote-only jobs when applicant location requirements are absent (as in actual list API responses)', () => {
      // In the real list API responses, remote jobs lack applicant_location_requirements.
      // Google requires applicantLocationRequirements for TELECOMMUTE roles.
      // Omitting TELECOMMUTE must not make a remote-only job look office-based.
      // Therefore, they must be excluded from the sitemap.
      const realListApiRemoteJob = {
        job_id: 'ashby:cb981ecd-a161-482c-8d8e-5f19bb6e7fdd',
        title: 'Senior Security Engineer',
        company: 'Cohere',
        workplace_type: 'remote',
        location: 'Toronto, Ontario, Canada',
        country: 'Canada',
        posted_at: '2026-10-31T15:33:10.669000Z'
        // Notice: applicant_location_requirements is undefined in actual API responses
      };
      expect(isJobEligibleForMarkup(realListApiRemoteJob)).toBe(false);
    });

    it('approves remote-only jobs if verified applicant location requirements are present', () => {
      const remoteWithReqs = {
        job_id: 'remote-1',
        title: 'Senior Frontend Engineer',
        company: 'Automattic',
        posted_at: '2026-11-01T00:00:00Z',
        workplace_type: 'remote',
        applicant_location_requirements: ['Canada', 'United States']
      };
      expect(isJobEligibleForMarkup(remoteWithReqs)).toBe(true);
    });

    it('rejects non-remote jobs without any physical location', () => {
      const job = {
        job_id: 'office-noloc',
        title: 'Office Worker',
        company: 'No Location Inc',
        posted_at: '2026-11-01T00:00:00Z',
        workplace_type: 'on_site',
        location: null,
        locations: []
      };
      expect(isJobEligibleForMarkup(job)).toBe(false);
    });

    it('rejects closed or expired jobs', () => {
      const base = {
        job_id: 'test-job',
        title: 'Dev',
        company: 'Company',
        posted_at: '2026-11-01T00:00:00Z',
        location: 'Toronto, ON, Canada'
      };

      expect(isJobEligibleForMarkup({ ...base, is_active: false })).toBe(false);
      expect(isJobEligibleForMarkup({ ...base, status: 'closed' })).toBe(false);
      expect(isJobEligibleForMarkup({ ...base, expired: true })).toBe(false);
    });

    it('rejects jobs with missing title, company, or invalid posted_at', () => {
      expect(isJobEligibleForMarkup({ title: '', company: 'A', posted_at: '2026-11-01' })).toBe(false);
      expect(isJobEligibleForMarkup({ title: 'T', company: '', posted_at: '2026-11-01' })).toBe(false);
      expect(isJobEligibleForMarkup({ title: 'T', company: 'A', posted_at: null })).toBe(false);
      expect(isJobEligibleForMarkup({ title: 'T', company: 'A', posted_at: 'invalid-date' })).toBe(false);
      expect(isJobEligibleForMarkup(null)).toBe(false);
    });
  });

  describe('Multi-page API pagination and error handling (fetchEligibleJobs)', () => {
    it('paginates across all pages beyond 500 items and filters eligible jobs', async () => {
      // Mock API returning 250 items across 3 pages (limit=100)
      const mockJobs = Array.from({ length: 250 }, (_, i) => ({
        job_id: `job-${i}`,
        title: `Software Engineer ${i}`,
        company: 'Tech Corp',
        posted_at: '2026-10-30T00:00:00Z',
        workplace_type: i % 5 === 0 ? 'remote' : 'hybrid', // 1 in 5 is remote without applicant reqs
        location: 'Toronto, ON, Canada',
        locations: [{ country: 'Canada', location: 'Toronto, ON, Canada' }]
      }));

      const mockFetch = vi.fn(async (url) => {
        const u = new URL(url);
        const limit = parseInt(u.searchParams.get('limit') || '100', 10);
        const offset = parseInt(u.searchParams.get('offset') || '0', 10);
        const slice = mockJobs.slice(offset, offset + limit);
        return {
          ok: true,
          status: 200,
          json: async () => ({
            total: 250,
            limit,
            offset,
            jobs: slice
          })
        };
      });

      const eligible = await fetchEligibleJobs('https://test-api.example.com', mockFetch);

      expect(mockFetch).toHaveBeenCalledTimes(3);
      // 250 total minus 50 ineligible remote jobs = 200 eligible
      expect(eligible.length).toBe(200);
    });

    it('treats a failure on a later page (e.g. offset 100) as an error rather than returning an incomplete sitemap', async () => {
      const page1Jobs = [
        {
          job_id: 'job-1',
          title: 'Dev 1',
          company: 'Co',
          posted_at: '2026-11-01',
          location: 'Toronto, ON, Canada'
        }
      ];

      const mockFetch = vi.fn(async (url) => {
        if (url.includes('offset=0')) {
          return {
            ok: true,
            status: 200,
            json: async () => ({ total: 200, limit: 100, offset: 0, jobs: page1Jobs })
          };
        }
        // Offset 100 fails with HTTP 500
        return {
          ok: false,
          status: 500,
          json: async () => ({ error: 'Internal Error' })
        };
      });

      // Must throw an error instead of silently returning 1 job
      await expect(fetchEligibleJobs('https://test-api.example.com', mockFetch)).rejects.toThrow(
        /Sitemap pagination failed at offset 100: HTTP 500/
      );
    });

    it('treats a malformed response on a later page (missing jobs array) as an error', async () => {
      const page1Jobs = [
        {
          job_id: 'job-1',
          title: 'Dev 1',
          company: 'Co',
          posted_at: '2026-11-01',
          location: 'Toronto, ON, Canada'
        }
      ];

      const mockFetch = vi.fn(async (url) => {
        if (url.includes('offset=0')) {
          return {
            ok: true,
            status: 200,
            json: async () => ({ total: 200, limit: 100, offset: 0, jobs: page1Jobs })
          };
        }
        // Offset 100 returns malformed JSON
        return {
          ok: true,
          status: 200,
          json: async () => ({ unexpected: 'data' })
        };
      });

      await expect(fetchEligibleJobs('https://test-api.example.com', mockFetch)).rejects.toThrow(
        /Sitemap pagination received malformed response at offset 100/
      );
    });

    it('treats an initial page failure as an error', async () => {
      const mockFetch = vi.fn(async () => ({
        ok: false,
        status: 503,
        json: async () => ({})
      }));

      await expect(fetchEligibleJobs('https://test-api.example.com', mockFetch)).rejects.toThrow(
        /Failed to fetch initial page of jobs: HTTP 503/
      );
    });

    it('rejects first-page response with missing, invalid, or non-integer total', async () => {
      const validJobs = [
        {
          job_id: 'job-1',
          title: 'Dev',
          company: 'Co',
          posted_at: '2026-11-01',
          location: 'Toronto, ON, Canada'
        }
      ];

      // Missing total (undefined)
      const fetchMissing = vi.fn(async () => ({
        ok: true,
        status: 200,
        json: async () => ({ jobs: validJobs })
      }));
      await expect(fetchEligibleJobs('https://test-api.example.com', fetchMissing)).rejects.toThrow(
        /Invalid total in initial page response/
      );

      // Non-integer total
      const fetchFloat = vi.fn(async () => ({
        ok: true,
        status: 200,
        json: async () => ({ total: 12.5, jobs: validJobs })
      }));
      await expect(fetchEligibleJobs('https://test-api.example.com', fetchFloat)).rejects.toThrow(
        /Invalid total in initial page response: 12.5/
      );

      // Negative total
      const fetchNeg = vi.fn(async () => ({
        ok: true,
        status: 200,
        json: async () => ({ total: -1, jobs: validJobs })
      }));
      await expect(fetchEligibleJobs('https://test-api.example.com', fetchNeg)).rejects.toThrow(
        /Invalid total in initial page response: -1/
      );
    });

    it('rejects first-page response with inconsistent total that cannot produce a truthful sitemap', async () => {
      const tenJobs = Array.from({ length: 10 }, (_, i) => ({
        job_id: `job-${i}`,
        title: `Dev ${i}`,
        company: 'Co',
        posted_at: '2026-11-01',
        location: 'Toronto, ON, Canada'
      }));

      // Inconsistency: total is less than jobs returned on page 1
      const fetchLess = vi.fn(async () => ({
        ok: true,
        status: 200,
        json: async () => ({ total: 5, jobs: tenJobs })
      }));
      await expect(fetchEligibleJobs('https://test-api.example.com', fetchLess)).rejects.toThrow(
        /Inconsistent total in initial page response: total=5 but jobs.length=10/
      );

      // Inconsistency: jobs returned but total is 0
      const fetchZeroTotal = vi.fn(async () => ({
        ok: true,
        status: 200,
        json: async () => ({ total: 0, jobs: tenJobs })
      }));
      await expect(fetchEligibleJobs('https://test-api.example.com', fetchZeroTotal)).rejects.toThrow(
        /Inconsistent total in initial page response: total=0 but jobs.length=10/
      );

      // Inconsistency: total claimed > 0 but 0 jobs returned on page 1
      const fetchEmptyJobs = vi.fn(async () => ({
        ok: true,
        status: 200,
        json: async () => ({ total: 100, jobs: [] })
      }));
      await expect(fetchEligibleJobs('https://test-api.example.com', fetchEmptyJobs)).rejects.toThrow(
        /Inconsistent total in initial page response: total=100 but jobs.length=0/
      );
    });
  });

  describe('Sitemap XML generation (generateSitemapXml)', () => {
    it('omits <lastmod> from all URLs because no reliable modification timestamp exists', () => {
      const eligibleJobs = [
        {
          job_id: 'workday:td.wd3/TD_Bank_Careers/Software-Engineer-II_R_1516370',
          posted_at: '2026-11-01T12:00:00Z'
        },
        {
          job_id: 'ashby:simple-id',
          posted_at: '2026-10-31T08:00:00Z'
        }
      ];

      const xml = generateSitemapXml(eligibleJobs, 'https://roleradar.com');

      // Crucial: Must NOT use posted_at as a substitute for lastmod
      expect(xml).not.toContain('<lastmod>');
      expect(xml).not.toContain('</lastmod>');
    });

    it('generates compliant XML with the three existing general pages and job URLs', () => {
      const eligibleJobs = [
        {
          job_id: 'workday:td.wd3/TD_Bank_Careers/Software-Engineer-II_R_1516370',
          posted_at: '2026-11-01T12:00:00Z'
        }
      ];

      const xml = generateSitemapXml(eligibleJobs, 'https://roleradar.com');

      expect(xml).toContain('<?xml version="1.0" encoding="UTF-8"?>');
      expect(xml).toContain('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">');

      // Preserves the three existing general pages
      expect(xml).toContain('<loc>https://roleradar.com/jobs</loc>');
      expect(xml).toContain('<loc>https://roleradar.com/stats</loc>');
      expect(xml).toContain('<loc>https://roleradar.com/company</loc>');

      // Escapes slashes and special characters in job IDs
      expect(xml).toContain(
        '<loc>https://roleradar.com/jobs/workday%3Atd.wd3%2FTD_Bank_Careers%2FSoftware-Engineer-II_R_1516370</loc>'
      );
    });

    it('does not invent validThrough or expiry dates in the sitemap', () => {
      const xml = generateSitemapXml([{ job_id: 'j1', posted_at: '2026-11-01T00:00:00Z' }]);
      expect(xml).not.toContain('validThrough');
      expect(xml).not.toContain('expiry');
    });
  });

  describe('HTTP Handler integration', () => {
    it('sets correct headers and caching on success', async () => {
      const req = {
        headers: {
          host: 'roleradar-preview.vercel.app',
          'x-forwarded-proto': 'https'
        }
      };

      const headers = {};
      let responseBody = '';
      const res = {
        statusCode: 0,
        setHeader(name, val) {
          headers[name] = val;
        },
        end(chunk) {
          responseBody = chunk;
        }
      };

      await sitemapHandler(req, res);

      expect(res.statusCode).toBe(200);
      expect(headers['Content-Type']).toBe('application/xml; charset=utf-8');
      expect(headers['Cache-Control']).toContain('public');
      expect(headers['Cache-Control']).toContain('s-maxage=3600');
      expect(responseBody).toContain('<?xml version="1.0" encoding="UTF-8"?>');
      expect(responseBody).toContain('<loc>https://roleradar-preview.vercel.app/jobs</loc>');
      expect(responseBody).not.toContain('<lastmod>');
    });

    it('returns HTTP 503 with Retry-After when upstream pagination fails, never serving an incomplete sitemap', async () => {
      const originalFetch = global.fetch;
      global.fetch = vi.fn(async () => ({
        ok: false,
        status: 500,
        json: async () => ({})
      }));

      try {
        const req = {
          headers: { host: 'roleradar-preview.vercel.app', 'x-forwarded-proto': 'https' }
        };

        const headers = {};
        let responseBody = '';
        const res = {
          statusCode: 0,
          setHeader(name, val) {
            headers[name] = val;
          },
          end(chunk) {
            responseBody = chunk;
          }
        };

        await sitemapHandler(req, res);

        expect(res.statusCode).toBe(503);
        expect(headers['Retry-After']).toBe('60');
        expect(headers['Cache-Control']).toBe('no-cache, no-store, must-revalidate');
        expect(responseBody).toContain('Service Unavailable');
      } finally {
        global.fetch = originalFetch;
      }
    });

    it('returns HTTP 503 when first page total is invalid or inconsistent, never emitting a partial sitemap', async () => {
      const originalFetch = global.fetch;
      // Upstream returns 200 with 10 jobs, but inconsistent total: 2
      global.fetch = vi.fn(async () => ({
        ok: true,
        status: 200,
        json: async () => ({
          total: 2,
          limit: 100,
          offset: 0,
          jobs: Array.from({ length: 10 }, (_, i) => ({
            job_id: `inconsistent-${i}`,
            title: `Job ${i}`,
            company: 'Test Co',
            posted_at: '2026-11-01',
            location: 'Toronto, ON, Canada'
          }))
        })
      }));

      try {
        const req = {
          headers: { host: 'roleradar-preview.vercel.app', 'x-forwarded-proto': 'https' }
        };

        const headers = {};
        let responseBody = '';
        const res = {
          statusCode: 0,
          setHeader(name, val) {
            headers[name] = val;
          },
          end(chunk) {
            responseBody = chunk;
          }
        };

        await sitemapHandler(req, res);

        expect(res.statusCode).toBe(503);
        expect(headers['Retry-After']).toBe('60');
        expect(headers['Cache-Control']).toBe('no-cache, no-store, must-revalidate');
        expect(responseBody).toContain('Service Unavailable');
        // Crucial: Must NOT emit a partial sitemap containing the 10 inconsistent jobs
        expect(responseBody).not.toContain('<urlset');
        expect(responseBody).not.toContain('inconsistent-0');
      } finally {
        global.fetch = originalFetch;
      }
    });
  });
});
