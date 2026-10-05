import { describe, it, expect, vi, afterEach } from 'vitest';
import { act, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { apiClient, ApiError, type JobDetail } from '../src/api/client';
import { JobDetailContent } from '../src/components/JobDetailContent';
import { AMAZON_BILINGUAL, BMO_SRE, STRIPE } from './fixtures/descriptions';

const make = (id: string, over: Partial<JobDetail> = {}): JobDetail => ({
  job_id: id, title: `Title ${id}`, company: `Company ${id}`, location: 'Toronto, ON', country: 'Canada', workplace_type: 'hybrid',
  role_type: 'full_time', source_name: 'ashby', skills: [], posted_at: '2026-09-28T00:00:00Z',
  company_apply_url: `https://jobs.example.test/${id}/apply`, description: `<p>Description of ${id}.</p>`, ...over,
});

interface Deferred { resolve: (j: JobDetail) => void; reject: (e: unknown) => void; signal?: AbortSignal }
function controlledApi() {
  const pending = new Map<string, Deferred>();
  const spy = vi.spyOn(apiClient, 'getJob').mockImplementation(
    (id: string, signal?: AbortSignal) => new Promise<JobDetail>((resolve, reject) => pending.set(id, { resolve, reject, signal }))
  );
  return { pending, spy };
}
const applyLinks = () => [...document.querySelectorAll('a[href]')].filter((a) => /apply/i.test(a.getAttribute('aria-label') ?? a.textContent ?? '')) as HTMLAnchorElement[];
const header = () => document.querySelector('.job-detail-header') as HTMLElement;
const title = () => screen.getByRole('heading', { level: 2 });

afterEach(() => vi.restoreAllMocks());

describe('switching jobs keeps the pane mounted and never mixes jobs', () => {
  it('keeps the header mounted without a desktop close control; shows the new job from its summary at once; Apply is disabled until the new destination loads', async () => {
    const { pending } = controlledApi();
    const a = make('a');
    const b = make('b');
    const { rerender } = render(<JobDetailContent jobId="a" variant="pane" onClose={() => {}} preview={a} />);
    await act(async () => pending.get('a')!.resolve(a));
    expect(applyLinks().map((l) => l.href)).toEqual(['https://jobs.example.test/a/apply']);
    const headerBefore = header();
    expect(screen.queryByRole('button', { name: 'Close job details' })).not.toBeInTheDocument();

    rerender(<JobDetailContent jobId="b" variant="pane" onClose={() => {}} preview={b} />);
    // same commit: the previous job's Apply URL is already unusable, the header is the same DOM node
    expect(applyLinks()).toEqual([]);
    expect(document.querySelector('[href*="/a/apply"]')).toBeNull();
    const pendingApply = screen.getByRole('link', { name: /Apply for Title b at Company b/ });
    expect(pendingApply).toHaveAttribute('aria-disabled', 'true');
    expect(pendingApply).not.toHaveAttribute('href');
    expect(header()).toBe(headerBefore);
    expect(screen.queryByRole('button', { name: 'Close job details' })).not.toBeInTheDocument();
    // summary data is used immediately; the old description and facts are gone
    expect(title()).toHaveTextContent('Title b');
    expect(header()).toHaveTextContent('Company b');
    expect(screen.queryByText('Description of a.')).not.toBeInTheDocument();
    expect(screen.queryByText('Title a')).not.toBeInTheDocument();

    await act(async () => pending.get('b')!.resolve(b));
    expect(applyLinks().map((l) => l.href)).toEqual(['https://jobs.example.test/b/apply']);
    expect(screen.getByText('Description of b.')).toBeInTheDocument();
    expect(header()).toBe(headerBefore);
  });

  it('ignores a late response from a previously selected job (reordered responses)', async () => {
    const { pending } = controlledApi();
    const { rerender } = render(<JobDetailContent jobId="a" variant="pane" onClose={() => {}} preview={make('a')} />);
    rerender(<JobDetailContent jobId="b" variant="pane" onClose={() => {}} preview={make('b')} />);
    rerender(<JobDetailContent jobId="c" variant="pane" onClose={() => {}} preview={make('c')} />);
    expect(pending.get('a')!.signal!.aborted).toBe(true);
    expect(pending.get('b')!.signal!.aborted).toBe(true);
    // c answers first, then b and a arrive late (the mock ignores the abort signal, like a slow proxy would)
    await act(async () => pending.get('c')!.resolve(make('c')));
    await act(async () => pending.get('b')!.resolve(make('b')));
    await act(async () => pending.get('a')!.resolve(make('a')));
    expect(title()).toHaveTextContent('Title c');
    expect(applyLinks().map((l) => l.href)).toEqual(['https://jobs.example.test/c/apply']);
    expect(screen.getByText('Description of c.')).toBeInTheDocument();
    expect(screen.queryByText('Description of a.')).not.toBeInTheDocument();
    expect(screen.queryByText('Description of b.')).not.toBeInTheDocument();
  });

  it("a late error from an earlier job does not replace the current job's content", async () => {
    const { pending } = controlledApi();
    const { rerender } = render(<JobDetailContent jobId="a" variant="pane" onClose={() => {}} preview={make('a')} />);
    rerender(<JobDetailContent jobId="b" variant="pane" onClose={() => {}} preview={make('b')} />);
    await act(async () => pending.get('b')!.resolve(make('b')));
    await act(async () => pending.get('a')!.reject(new ApiError(500, '/api/jobs/a')));
    expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument();
    expect(screen.getByText('Description of b.')).toBeInTheDocument();
  });

  it('an unavailable or failed new job never shows the previous job\'s Apply link or text', async () => {
    const { pending } = controlledApi();
    const { rerender } = render(<JobDetailContent jobId="a" variant="pane" onClose={() => {}} preview={make('a')} />);
    await act(async () => pending.get('a')!.resolve(make('a')));
    rerender(<JobDetailContent jobId="gone" variant="pane" onClose={() => {}} preview={null} />);
    await act(async () => pending.get('gone')!.reject(new ApiError(404, '/api/jobs/gone')));
    expect(screen.getByTestId('job-unavailable')).toBeInTheDocument();
    expect(applyLinks()).toEqual([]);
    expect(screen.queryByText('Description of a.')).not.toBeInTheDocument();
    rerender(<JobDetailContent jobId="flaky" variant="pane" onClose={() => {}} preview={make('flaky')} />);
    await act(async () => pending.get('flaky')!.reject(new ApiError(500, '/api/jobs/flaky')));
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
    expect(applyLinks()).toEqual([]);
  });

  it('resets the description scroll when another job is selected', async () => {
    const { pending } = controlledApi();
    const scrollTo = vi.fn();
    Element.prototype.scrollTo = scrollTo as unknown as typeof Element.prototype.scrollTo;
    const { rerender } = render(<JobDetailContent jobId="a" variant="pane" onClose={() => {}} preview={make('a')} />);
    await act(async () => pending.get('a')!.resolve(make('a')));
    scrollTo.mockClear();
    rerender(<JobDetailContent jobId="b" variant="pane" onClose={() => {}} preview={make('b')} />);
    expect(scrollTo).toHaveBeenCalledWith({ top: 0 });
  });

  it('only the selected job\'s own facts are shown: no old "Apply by" under the new job', async () => {
    const { pending } = controlledApi();
    const withDeadline = make('a', { description: '<p>Application Deadline:</p><p>10/30/2026</p><p>Body.</p>' });
    const { rerender } = render(<JobDetailContent jobId="a" variant="pane" onClose={() => {}} preview={withDeadline} />);
    await act(async () => pending.get('a')!.resolve(withDeadline));
    expect(screen.getByText('Apply by')).toBeInTheDocument();
    rerender(<JobDetailContent jobId="b" variant="pane" onClose={() => {}} preview={make('b')} />);
    expect(screen.queryByText('Apply by')).not.toBeInTheDocument();
    await act(async () => pending.get('b')!.resolve(make('b')));
    expect(screen.queryByText('Apply by')).not.toBeInTheDocument();
  });
});

describe('page order of the detail pane', () => {
  it("Stripe: job and team introduction first, company background last", async () => {
    const { pending } = controlledApi();
    const job = make('s', { company: 'Stripe', title: 'Software Engineer, Metronome Infrastructure', description: STRIPE });
    render(<JobDetailContent jobId="s" variant="pane" onClose={() => {}} preview={job} />);
    await act(async () => pending.get('s')!.resolve(job));
    const order = [...document.querySelectorAll('h3.job-part-heading, h4.job-section-heading')].map((h) => h.textContent);
    expect(order[0]).toBe('About the job');
    expect(order).toContain('Responsibilities');
    expect(order.at(-1)).toBe('About the company');
    expect(order.filter((t) => t === 'About the job')).toHaveLength(1);
    expect(order.filter((t) => t === 'About the team')).toHaveLength(0);
    await userEvent.click(screen.getByRole('button', { name: 'Full Posting' }));
    expect(screen.getByText("What you'll do")).toBeInTheDocument();
    expect(screen.getByText('About the team')).toBeInTheDocument();
  });
});

describe('per-job choices do not leak between jobs', () => {
  const amazon = (id: string) => make(id, { company: 'Amazon', title: `Senior AI/ML Architect ${id}`, description: AMAZON_BILINGUAL });

  it('the English/French choice resets for the next job and is not remembered for the previous one', async () => {
    const { pending } = controlledApi();
    const { rerender } = render(<JobDetailContent jobId="a" variant="pane" onClose={() => {}} preview={amazon('a')} />);
    await act(async () => pending.get('a')!.resolve(amazon('a')));
    const toggle = () => screen.getByRole('group', { name: 'Description language' });
    expect(within(toggle()).getByRole('button', { name: 'English' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByText(/AWS Global Sales drives adoption/)).toBeInTheDocument();

    await userEvent.click(within(toggle()).getByRole('button', { name: 'Français' }));
    expect(within(toggle()).getByRole('button', { name: 'Français' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByText(/AWS Global Sales favorise/)).toBeInTheDocument();
    expect(document.querySelector('.job-description-prose[lang="fr"]')).not.toBeNull();

    rerender(<JobDetailContent jobId="b" variant="pane" onClose={() => {}} preview={amazon('b')} />);
    await act(async () => pending.get('b')!.resolve(amazon('b')));
    expect(within(toggle()).getByRole('button', { name: 'English' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.queryByText(/AWS Global Sales favorise/)).not.toBeInTheDocument();

    rerender(<JobDetailContent jobId="a" variant="pane" onClose={() => {}} preview={amazon('a')} />);
    await act(async () => pending.get('a')!.resolve(amazon('a')));
    expect(within(toggle()).getByRole('button', { name: 'English' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('an ambiguous mixed-language job shows the complete original with no toggle, and nothing leaks across jobs', async () => {
    const { pending } = controlledApi();
    const ambiguous = 'Vous devez travailler au bureau de Montréal trois jours par semaine. La rémunération annuelle pour ce poste est de 120 000 dollars. Nous recherchons une personne avec cinq années d’expérience dans les systèmes distribués. Vous serez responsable de la sécurité des services et de la fiabilité des applications. Notre équipe vous accompagne dans votre développement professionnel.';
    const english = 'Our company builds reliable software for customers around the world. We are committed to supporting your career and helping you learn from experienced engineers. You will collaborate with our team to deliver useful products and improve the quality of our services. We offer a welcoming environment for everyone and opportunities to grow with the company. Your contributions will shape the future of our products.';
    const mixed = (id: string) => make(id, { company: 'Acme', description: `<p>${ambiguous}</p><p>${english}</p>` });
    const { rerender } = render(<JobDetailContent jobId="a" variant="pane" onClose={() => {}} preview={amazon('a')} />);
    await act(async () => pending.get('a')!.resolve(amazon('a')));
    await userEvent.click(screen.getByRole('button', { name: 'Français' })); // a French choice on a bilingual job...
    rerender(<JobDetailContent jobId="m" variant="pane" onClose={() => {}} preview={mixed('m')} />);
    await act(async () => pending.get('m')!.resolve(mixed('m')));
    // ...never reaches the ambiguous job: no toggle, both paragraphs complete
    expect(screen.queryByRole('group', { name: 'Description language' })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Full Posting' }));
    const prose = document.querySelector('.job-description-prose')!.textContent!;
    expect(prose).toContain('120 000 dollars');
    expect(prose).toContain('trois jours par semaine');
    expect(prose).toContain('Our company builds reliable software');
    rerender(<JobDetailContent jobId="b" variant="pane" onClose={() => {}} preview={amazon('b')} />);
    await act(async () => pending.get('b')!.resolve(amazon('b')));
    expect(within(screen.getByRole('group', { name: 'Description language' })).getByRole('button', { name: 'English' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.queryByText(/120 000 dollars/)).not.toBeInTheDocument();
  });

  it('an English-only job has no language toggle; the original stays one click away on bilingual jobs', async () => {
    const { pending } = controlledApi();
    const { rerender } = render(<JobDetailContent jobId="s" variant="pane" onClose={() => {}} preview={make('s')} />);
    await act(async () => pending.get('s')!.resolve(make('s', { company: 'Stripe', description: STRIPE })));
    expect(screen.queryByRole('group', { name: 'Description language' })).not.toBeInTheDocument();
    rerender(<JobDetailContent jobId="a" variant="pane" onClose={() => {}} preview={amazon('a')} />);
    await act(async () => pending.get('a')!.resolve(amazon('a')));
    await userEvent.click(screen.getByRole('button', { name: 'Original (both)' }));
    await userEvent.click(screen.getByRole('button', { name: 'Full Posting' }));
    expect(screen.getByText(/AWS Global Sales drives adoption/)).toBeInTheDocument();
    expect(screen.getByText(/AWS Global Sales favorise/)).toBeInTheDocument();
  });

  it('shows the employer address immediately, clears it on job switches, and keeps remote context', async () => {
    const { pending } = controlledApi();
    const bmo = make('bmo', { company: 'BMO', description: BMO_SRE, workplace_type: 'hybrid' });
    const { rerender } = render(<JobDetailContent jobId="bmo" variant="pane" onClose={() => {}} preview={bmo} />);
    await act(async () => pending.get('bmo')!.resolve(bmo));
    expect(header()).toHaveTextContent('Toronto, ON'); // city/province stay visible in the header
    const address = screen.getByRole('group', { name: 'Employer address' });
    const map = within(address).getByRole('link');
    expect(map).toHaveTextContent('4100 Gordon Baker Road');
    expect(map).toHaveAttribute('target', '_blank');
    expect(map).toHaveAttribute('rel', 'noopener noreferrer');
    expect(new URL(map.getAttribute('href')!).searchParams.get('query')).toContain('4100 Gordon Baker Road');
    expect(screen.getByLabelText('Job facts')).toHaveTextContent('Apply by Oct 30, 2026');
    // the address is no longer loose text at the top of the description
    expect(document.querySelector('.job-description-prose')!.textContent).not.toContain('Gordon Baker');
    rerender(<JobDetailContent jobId="x" variant="pane" onClose={() => {}} preview={make('x')} />);
    expect(screen.queryByRole('group', { name: 'Employer address' })).not.toBeInTheDocument();
    await act(async () => pending.get('x')!.resolve(make('x')));
    expect(screen.queryByRole('group', { name: 'Employer address' })).not.toBeInTheDocument();
    rerender(<JobDetailContent jobId="bmo" variant="pane" onClose={() => {}} preview={bmo} />);
    await act(async () => pending.get('bmo')!.resolve(bmo));
    expect(screen.getByRole('group', { name: 'Employer address' })).toHaveTextContent('4100 Gordon Baker Road');

    // a remote role: the address is shown with a note, never as a requirement to attend
    const remote = make('r', { company: 'BMO', description: BMO_SRE, workplace_type: 'remote' });
    rerender(<JobDetailContent jobId="r" variant="pane" onClose={() => {}} preview={remote} />);
    await act(async () => pending.get('r')!.resolve(remote));
    expect(screen.getByText('Employer-listed address; this role is remote.')).toBeInTheDocument();
  });

  it('multiple locations and their toggle still work next to location details', async () => {
    const { pending } = controlledApi();
    const job = make('m', { description: BMO_SRE, locations: [{ location: 'Toronto, ON', country: 'Canada' }, { location: 'Montreal, QC', country: 'Canada' }] });
    render(<JobDetailContent jobId="m" variant="pane" onClose={() => {}} preview={job} />);
    await act(async () => pending.get('m')!.resolve(job));
    await userEvent.click(screen.getByRole('button', { name: '+1 location' }));
    expect(screen.getByRole('list', { name: 'Additional locations' })).toHaveTextContent('Montreal');
    expect(screen.getByRole('group', { name: 'Employer address' })).toBeInTheDocument();
  });
});
