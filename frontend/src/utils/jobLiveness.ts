/**
 * Checks, from the browser, whether a posting is still on the employer's own job board.
 *
 * The database is refreshed every few hours, so a posting an employer took down can stay listed until the next
 * refresh. Greenhouse, Lever and Ashby publish public job-board APIs that allow browser requests, so those postings
 * can be confirmed on the spot. Only a definite "not there" counts as gone: a network error, a timeout or any
 * other answer leaves the job listed.
 */
export type Liveness = "live" | "gone" | "unknown";

export interface LivenessJob {
  job_id: string;
  source_name: string;
  source_url?: string | null;
}

const TTL_MS = 10 * 60 * 1000;
const TIMEOUT_MS = 6000;

const results = new Map<string, { state: Liveness; at: number }>();
const ashbyBoards = new Map<string, { at: number; ids: Promise<Set<string> | null> }>();

type FetchLike = (url: string, init?: { signal?: AbortSignal }) => Promise<{ status: number; ok: boolean; json: () => Promise<unknown> }>;

function timeoutSignal(): AbortSignal | undefined {
  return typeof AbortSignal !== "undefined" && typeof AbortSignal.timeout === "function" ? AbortSignal.timeout(TIMEOUT_MS) : undefined;
}

function pathParts(sourceUrl: string): { host: string; parts: string[] } | null {
  try {
    const url = new URL(sourceUrl);
    return { host: url.hostname.toLowerCase(), parts: url.pathname.split("/").filter(Boolean) };
  } catch {
    return null;
  }
}

async function ashbyIds(org: string, fetchImpl: FetchLike): Promise<Set<string> | null> {
  const cached = ashbyBoards.get(org);
  if (cached && Date.now() - cached.at < TTL_MS) return cached.ids;
  const ids = (async () => {
    try {
      const response = await fetchImpl(`https://api.ashbyhq.com/posting-api/job-board/${encodeURIComponent(org)}`, { signal: timeoutSignal() });
      if (!response.ok) return null;
      const body = (await response.json()) as { jobs?: { id?: string }[] };
      const list = Array.isArray(body.jobs) ? body.jobs : [];
      // An empty board is more likely an outage than every posting closing at once.
      return list.length > 0 ? new Set(list.map((job) => String(job.id))) : null;
    } catch {
      return null;
    }
  })();
  ashbyBoards.set(org, { at: Date.now(), ids });
  return ids;
}

async function probe(job: LivenessJob, fetchImpl: FetchLike): Promise<Liveness> {
  const where = job.source_url ? pathParts(job.source_url) : null;
  if (!where) return "unknown";
  try {
    if (job.source_name === "greenhouse" && where.host.endsWith("greenhouse.io")) {
      const id = /^greenhouse:(\d+)$/.exec(job.job_id)?.[1];
      const board = where.parts[0];
      if (!id || !board) return "unknown";
      const response = await fetchImpl(`https://boards-api.greenhouse.io/v1/boards/${encodeURIComponent(board)}/jobs/${id}`, { signal: timeoutSignal() });
      return response.status === 404 ? "gone" : response.ok ? "live" : "unknown";
    }
    if (job.source_name === "lever" && where.host === "jobs.lever.co") {
      const [org, id] = where.parts;
      if (!org || !id) return "unknown";
      const response = await fetchImpl(`https://api.lever.co/v0/postings/${encodeURIComponent(org)}/${encodeURIComponent(id)}`, { signal: timeoutSignal() });
      return response.status === 404 ? "gone" : response.ok ? "live" : "unknown";
    }
    if (job.source_name === "ashby" && where.host === "jobs.ashbyhq.com") {
      const [org, id] = where.parts;
      if (!org || !id) return "unknown";
      const ids = await ashbyIds(org, fetchImpl);
      if (!ids) return "unknown";
      return ids.has(id) ? "live" : "gone";
    }
  } catch {
    return "unknown";
  }
  return "unknown";
}

/** Remembers answers for ten minutes so paging, filtering and reopening do not ask the employer again. */
export async function checkJobLiveness(job: LivenessJob, fetchImpl?: FetchLike): Promise<Liveness> {
  const cached = results.get(job.job_id);
  if (cached && Date.now() - cached.at < TTL_MS) return cached.state;
  const impl = fetchImpl ?? (typeof fetch === "function" ? (fetch as unknown as FetchLike) : null);
  if (!impl) return "unknown";
  const state = await probe(job, impl);
  if (state !== "unknown") results.set(job.job_id, { state, at: Date.now() });
  return state;
}

/** Ids already confirmed gone in this session (and not yet expired from memory). */
export function knownGoneJobIds(): Set<string> {
  const now = Date.now();
  return new Set([...results].filter(([, entry]) => entry.state === "gone" && now - entry.at < TTL_MS).map(([id]) => id));
}

export function resetJobLivenessForTests(): void {
  results.clear();
  ashbyBoards.clear();
}
