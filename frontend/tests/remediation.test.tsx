import { describe, it, expect, vi } from 'vitest';
import { render, screen, waitFor, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { parseUrlSearch, serializeUrlSearch } from '../src/utils/urlState';
import { parseAndSanitizeJobDescription } from '../src/utils/sanitizeDescription';
import { apiClient, type JobDetail } from '../src/api/client';
import { JobDetailModal } from '../src/components/JobDetailModal';
import { resolveApplyRoutes } from '../src/utils/applyUrls';
import { App } from '../src/App';

const job: JobDetail = {job_id:'ashby:abc',title:'Software Engineer',company:'Fixture',location:'Remote',country:'Canada',workplace_type:'remote',source_name:'ashby',skills:[],company_apply_url:'https://jobs.ashbyhq.com/fixture/abc/application',description:'About the role\nBuild reliable software\n\nRequirements\n- TypeScript\n- Testing',locations:[{location:'Remote',country:'Canada'},{location:'London',country:'United Kingdom'}],compensation:{compensationTierSummary:'Canada: CAD 130,000–180,000'}};

function mockApi() {
  vi.spyOn(apiClient,'getOverview').mockResolvedValue({total_postings:1,total_companies:1,total_locations:2,total_skills:0});
  vi.spyOn(apiClient,'getCountries').mockResolvedValue([]);
  vi.spyOn(apiClient,'getSkills').mockResolvedValue([]);
  vi.spyOn(apiClient,'getRoleStats').mockResolvedValue([]);
  vi.spyOn(apiClient,'getWorkplaceStats').mockResolvedValue([]);
  vi.spyOn(apiClient,'getCompanyStats').mockResolvedValue([]);
  vi.spyOn(apiClient,'getCompanies').mockResolvedValue([]);
  vi.spyOn(apiClient,'getJobFilters').mockResolvedValue({countries:['Canada'],companies:['Fixture'],skills:[],workplace_types:['remote']});
  vi.spyOn(apiClient,'getJobs').mockResolvedValue({total:1,limit:20,offset:0,jobs:[job]});
  vi.spyOn(apiClient,'getJob').mockResolvedValue(job);
}

describe('remediation behavior', () => {
  it.each(['/logos', '/companies'])('keeps %s unavailable in production', async (path) => {
    mockApi();
    vi.stubEnv('DEV',false);
    window.history.replaceState(null,'',path);
    render(<App/>);
    await screen.findByText(/Page not found/i);
    expect(apiClient.getCompanies).not.toHaveBeenCalled();
  });
  it('roundtrips shareable job IDs, filters and sort without losing characters', () => {
    const parsed = parseUrlSearch('?job=ashby%3Aa%2Fb%2Bc&q=backend&country=ca&sort=oldest&page=2');
    expect(parsed.jobId).toBe('ashby:a/b+c');
    expect(parseUrlSearch(serializeUrlSearch(parsed.filters,parsed.page,parsed.jobId))).toEqual(parsed);
    expect(parseUrlSearch('?page=2garbage').page).toBe(1);
    expect(parseUrlSearch('?sort=DROP').filters.sort).toBe('recommended');
  });
  it('preserves prose, headings, ordered lists and strips executable content', () => {
    const parsed = parseAndSanitizeJobDescription('About the role\nBuild reliable software\n\nRequirements\n- TypeScript\n- Testing\n\nInterview process\n1. Call\n2. Exercise');
    const doc = new DOMParser().parseFromString(parsed.html,'text/html');
    expect([...doc.querySelectorAll('h2')].map(h=>h.textContent)).toEqual(['About the role','Requirements','Interview process']);
    expect(doc.querySelector('p')?.textContent).toBe('Build reliable software');
    expect(doc.querySelectorAll('ul li')).toHaveLength(2);
    expect(doc.querySelectorAll('ol li')).toHaveLength(2);
    const unsafe = parseAndSanitizeJobDescription('<h3>Benefits</h3><p>Work with <strong>great people</strong></p><script>alert(1)</script><a href="javascript:alert(1)">evil</a><img src=x onerror=alert(1)>');
    expect(unsafe.html).not.toMatch(/script|javascript:|onerror|<img/i);
    expect(unsafe.html).toContain('<strong>great people</strong>');
  });
  it('upgrades known ATS HTTP links without losing the application path', () => {
    expect(resolveApplyRoutes({company_apply_url:'http://boards.greenhouse.io/acme/jobs/123?gh_src=abc#apply'}).primaryUrl).toBe('https://boards.greenhouse.io/acme/jobs/123?gh_src=abc#apply');
    expect(resolveApplyRoutes({company_apply_url:'http://careers.example.com/jobs/123'}).primaryUrl).toBe('http://careers.example.com/jobs/123');
  });
  it('renders official Apply links and all location/compensation evidence', async () => {
    vi.spyOn(apiClient,'getJob').mockResolvedValue(job);
    const close = vi.fn();
    render(<JobDetailModal jobId={job.job_id} onClose={close}/>);
    const links = await screen.findAllByRole('link',{name:/Apply for Software Engineer at Fixture/});
    for (const link of links) {
      expect(link).toHaveAttribute('href',job.company_apply_url);
      expect(link).toHaveAttribute('rel','noopener noreferrer');
    }
    expect(screen.getByText('Canada: CAD 130,000–180,000')).toBeInTheDocument();
    expect(screen.queryByText(/London/)).not.toBeInTheDocument();   // extra locations stay collapsed
    await userEvent.click(screen.getByRole('button',{name:'+1 location'}));
    expect(screen.getByText(/London/)).toBeInTheDocument();
    await userEvent.keyboard('{Escape}');
    expect(close).toHaveBeenCalled();
  });
  it('ignores stale modal requests when a share URL changes', async () => {
    let resolveOld!: (value: JobDetail) => void;
    vi.spyOn(apiClient,'getJob').mockImplementationOnce(()=>new Promise(resolve=>{resolveOld=resolve;})).mockResolvedValueOnce({...job,job_id:'new',title:'New Role'});
    const {rerender} = render(<JobDetailModal jobId="old" onClose={()=>{}}/>);
    rerender(<JobDetailModal jobId="new" onClose={()=>{}}/>);
    await screen.findByRole('heading',{name:'New Role'});
    await act(async()=>resolveOld({...job,title:'Old Role'}));
    expect(screen.queryByRole('heading',{name:'Old Role'})).not.toBeInTheDocument();
  });
  it('loads a shared URL, responds to Back/Forward, and sends sorting to the API', async () => {
    mockApi();
    window.history.replaceState(null,'','/jobs?job=ashby%3Aabc&sort=oldest');
    render(<App/>);
    await screen.findByRole('dialog');
    // the dialog mounts before its effect requests the job; wait for the request instead of assuming it
    await waitFor(()=>expect(apiClient.getJob).toHaveBeenCalledWith('ashby:abc',expect.any(AbortSignal)));
    await act(async()=>{
      window.history.replaceState(null,'','/jobs?sort=company');
      window.dispatchEvent(new PopStateEvent('popstate'));
    });
    await waitFor(()=>expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    await userEvent.selectOptions(screen.getByRole('combobox',{name:'Sort jobs'}), 'title');
    await waitFor(()=>expect(apiClient.getJobs).toHaveBeenLastCalledWith(expect.objectContaining({sort:'title',offset:0}),expect.any(AbortSignal)));
    expect(new URLSearchParams(window.location.search).get('sort')).toBe('title');
  });
});
