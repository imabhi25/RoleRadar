import { describe, it, expect, beforeEach, vi } from 'vitest';
import { checkJobLiveness, knownGoneJobIds, resetJobLivenessForTests } from '../src/utils/jobLiveness';

const reply = (status: number, body: unknown = {}) => ({ status, ok: status >= 200 && status < 300, json: async () => body });

beforeEach(() => resetJobLivenessForTests());

describe('job liveness against the employer board', () => {
  it('marks a Greenhouse posting gone only on a 404', async () => {
    const job = { job_id: 'greenhouse:8244082', source_name: 'greenhouse', source_url: 'https://job-boards.greenhouse.io/reddit/jobs/8244082' };
    const fetchMock = vi.fn(async () => reply(404));
    expect(await checkJobLiveness(job, fetchMock)).toBe('gone');
    expect(fetchMock).toHaveBeenCalledWith('https://boards-api.greenhouse.io/v1/boards/reddit/jobs/8244082', expect.anything());
    expect(knownGoneJobIds().has(job.job_id)).toBe(true);
  });

  it('keeps a job listed when the answer is anything but a definite 404', async () => {
    const job = { job_id: 'greenhouse:1', source_name: 'greenhouse', source_url: 'https://boards.greenhouse.io/acme/jobs/1' };
    expect(await checkJobLiveness(job, async () => reply(200))).toBe('live');
    resetJobLivenessForTests();
    expect(await checkJobLiveness(job, async () => reply(500))).toBe('unknown');
    expect(await checkJobLiveness(job, async () => { throw new Error('offline'); })).toBe('unknown');
    expect(knownGoneJobIds().size).toBe(0);
  });

  it('checks Lever by its posting id', async () => {
    const job = { job_id: 'lever:abc', source_name: 'lever', source_url: 'https://jobs.lever.co/acme/abc-123' };
    const fetchMock = vi.fn(async () => reply(404));
    expect(await checkJobLiveness(job, fetchMock)).toBe('gone');
    expect(fetchMock).toHaveBeenCalledWith('https://api.lever.co/v0/postings/acme/abc-123', expect.anything());
  });

  it('checks Ashby against the board listing, and ignores an empty board', async () => {
    const job = { job_id: 'ashby:x', source_name: 'ashby', source_url: 'https://jobs.ashbyhq.com/acme/id-1' };
    const other = { job_id: 'ashby:y', source_name: 'ashby', source_url: 'https://jobs.ashbyhq.com/acme/id-2' };
    const fetchMock = vi.fn(async () => reply(200, { jobs: [{ id: 'id-1' }] }));
    expect(await checkJobLiveness(job, fetchMock)).toBe('live');
    expect(await checkJobLiveness(other, fetchMock)).toBe('gone');
    expect(fetchMock).toHaveBeenCalledTimes(1); // one board request covers both
    resetJobLivenessForTests();
    expect(await checkJobLiveness(job, async () => reply(200, { jobs: [] }))).toBe('unknown');
  });

  it('does not check sources it cannot verify, and remembers answers', async () => {
    const workday = { job_id: 'workday:a', source_name: 'workday', source_url: 'https://clio.wd3.myworkdayjobs.com/x/job/y/z' };
    const fetchMock = vi.fn(async () => reply(404));
    expect(await checkJobLiveness(workday, fetchMock)).toBe('unknown');
    expect(await checkJobLiveness({ job_id: 'g', source_name: 'greenhouse' }, fetchMock)).toBe('unknown');
    expect(fetchMock).not.toHaveBeenCalled();
    const gh = { job_id: 'greenhouse:2', source_name: 'greenhouse', source_url: 'https://boards.greenhouse.io/acme/jobs/2' };
    await checkJobLiveness(gh, fetchMock);
    await checkJobLiveness(gh, fetchMock);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
