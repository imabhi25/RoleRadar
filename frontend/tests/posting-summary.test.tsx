import { afterEach, describe, expect, it, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { summarizePosting } from '../src/utils/postingSummary';
import { renderDescription } from '../src/utils/descriptionPipeline';
import { JobDetailContent } from '../src/components/JobDetailContent';
import { apiClient, type JobDetail } from '../src/api/client';

const raw = '<p>Build music discovery services. Collaborate with partners across several teams. This longer introduction is retained in the full posting.</p><h2>Requirements</h2><ul><li>A degree or equivalent experience; a degree is not required.</li><li>Experience with Java.</li><li>Experience operating distributed services.</li><li>Strong communication skills.</li><li>Additional requirement available in the full posting.</li></ul><h2>Responsibilities</h2><ul><li>Ship reliable software.</li><li>Measure service performance.</li></ul><h2>Benefits</h2><p>Health coverage and paid leave.</p><h2>Equal opportunity</h2><p>All qualified candidates are welcome.</p>';
const job: JobDetail = { job_id: 'lever:summary-a', title: 'Senior Software Engineer', company: 'Spotify', location: 'Toronto', country: 'Canada', workplace_type: 'remote', source_name: 'lever', skills: [], company_apply_url: 'https://jobs.lever.co/spotify/summary-a', description: raw };
afterEach(() => vi.restoreAllMocks());
const text = (html: string) => new DOMParser().parseFromString(html, 'text/html').body.textContent || '';

describe('source-based concise posting summaries', () => {
  it('keeps complete qualification alternatives and negation, with responsibilities, all short requirements and benefits', () => {
    const result = summarizePosting(renderDescription(raw, 'Spotify', job.title).mainHtml);
    expect(text(result)).toContain('A degree or equivalent experience; a degree is not required.');
    expect(text(result)).toContain('Build music discovery services.');
    expect(text(result)).toContain('Collaborate with partners across several teams.');
    expect(text(result)).toContain('Additional requirement');
    expect(text(result)).toContain('Health coverage');
    expect(text(result)).toContain('Ship reliable software.');
    expect(text(result).length).toBeLessThan(4001);
  });
  it('does not cut a long condition halfway through or render unsafe markup', () => {
    const long = 'Candidates may work remotely only if ' + 'a qualifying condition applies '.repeat(30);
    const result = summarizePosting(`<h4>Requirements</h4><ul><li>${long}</li><li>Python &amp; SQL experience.</li></ul><p>&lt;script&gt;attack&lt;/script&gt;</p>`);
    expect(text(result)).toContain(long.trim());
    expect(text(result)).toContain('Python & SQL');
    expect(result).not.toContain('<script>');
  });
  it('keeps all short unlabelled bullets rather than imposing a four-item limit', () => {
    const input = '<p>Build developer tools.</p><ul>' + ['Design APIs.', 'Ship services.', 'Maintain infrastructure.', 'Monitor reliability.', 'More detail in Full Posting.'].map((item) => `<li>${item}</li>`).join('') + '</ul>';
    const result = summarizePosting(renderDescription(input, 'Example', 'Engineer').mainHtml);
    const doc = new DOMParser().parseFromString(result, 'text/html');
    expect(doc.querySelectorAll('li')).toHaveLength(5);
    expect(text(result)).toContain('Monitor reliability.');
    expect(text(result)).toContain('More detail');
  });
  it('recognizes SuccessFactors question labels, drops recruitment fluff, and balances requirements and responsibilities', () => {
    const input = '<p>Requisition ID: 261791 Join a purpose driven winning team, committed to results, in an inclusive and high-performing culture.</p>'
      + '<p><b>Is this role right for you? In this role you will:</b></p><ul>'
      + ['Champion a customer focused culture to deepen client relationships.', 'Build cloud services using GCP.', 'Develop accessible interfaces using React.', 'Maintain containerized services.', 'Monitor production reliability.'].map((item) => `<li><p>${item}</p></li>`).join('') + '</ul>'
      + "<p><b>Do you have the skills that will enable you to succeed in this role? We'd love to work with you if you have:</b></p><ul>"
      + ['Experience with Java and cloud platforms.', 'Knowledge of Kubernetes.', 'Experience with HTML and CSS.', 'A degree or equivalent experience; a degree is not required.'].map((item) => `<li>${item}</li>`).join('') + '</ul>';
    const result = summarizePosting(renderDescription(input, 'Scotiabank', 'Associate Platform Engineer').mainHtml);
    const doc = new DOMParser().parseFromString(result, 'text/html');
    expect([...doc.querySelectorAll('h4')].map((h) => h.textContent)).toEqual(['Requirements', 'Responsibilities']);
    expect(doc.querySelectorAll('li')).toHaveLength(8);
    for (const snippet of ['Java', 'Kubernetes', 'HTML and CSS', 'degree is not required', 'GCP', 'React', 'containerized', 'reliability']) expect(text(result)).toContain(snippet);
    expect(text(result)).not.toMatch(/261791|winning team|Champion a customer/);
  });
  it('keeps complete qualification paragraphs, including their exceptions', () => {
    const result = summarizePosting('<h2>Requirements</h2><p>A degree is normally required. Equivalent experience is accepted instead.</p><h2>Responsibilities</h2><p>Operate distributed services.</p>');
    expect(text(result)).toContain('A degree is normally required. Equivalent experience is accepted instead.');
    expect(text(result)).toContain('Operate distributed services.');
  });
  it.each([
    "A bachelor's degree is required. Equivalent practical experience is also accepted.",
    'You must be based in Toronto. You are not required to relocate if you currently work remotely.',
  ])('preserves alternatives and exceptions in an unlabelled introduction: %s', (paragraph) => {
    const result = summarizePosting(`<p>${paragraph}</p><h2>Responsibilities</h2><ul><li>Build secure services.</li></ul>`);
    const doc = new DOMParser().parseFromString(result, 'text/html');
    expect(doc.querySelector('p')?.textContent).toBe(paragraph);
    expect(text(result)).toContain('Build secure services.');
    expect(text(result).length).toBeLessThanOrEqual(4000);
  });
  it('summarizes a long first sentence faithfully when its whole paragraph fits', () => {
    const paragraph = 'Secure accessible software engineering '.repeat(20) + 'is the work you will do.';
    expect(paragraph.length).toBeGreaterThan(400);
    const result = summarizePosting(`<p>${paragraph}</p>`);
    expect(text(result)).toBe(paragraph);
    expect(text(result).length).toBeLessThanOrEqual(4000);
  });
  it('uses the full text budget when no section headings are needed', () => {
    const paragraph = 'Build secure services. ' + 'x'.repeat(3977);
    expect(paragraph.length).toBe(4000);
    expect(text(summarizePosting(`<p>${paragraph}</p>`))).toBe(paragraph);
  });
  it('does not cut an oversized introductory condition to manufacture an excerpt', () => {
    const paragraph = 'Remote work is allowed only when ' + 'the following condition is satisfied '.repeat(150);
    expect(summarizePosting(`<p>${paragraph}</p>`)).toBe('');
  });
  it('reserves qualifications and responsibilities before a large introduction', () => {
    const paragraph = 'Build developer tooling for ' + 'secure accessible services '.repeat(150);
    const requirement = 'Equivalent experience is accepted. ' + 'Relevant Java experience. '.repeat(8);
    const responsibility = 'Ship reliable software. ' + 'Operate services securely. '.repeat(8);
    const result = summarizePosting(`<p>${paragraph}</p><h2>Requirements</h2><p>${requirement}</p><h2>Responsibilities</h2><p>${responsibility}</p>`);
    expect(text(result)).not.toContain('Build developer tooling');
    expect(text(result)).toContain(requirement.trim());
    expect(text(result)).toContain(responsibility.trim());
    expect(text(result).length).toBeLessThanOrEqual(4000);
  });
  it('does not exhaust the summary on a long responsibilities section before qualifications', () => {
    const input = '<h2>Responsibilities</h2><ul>' + Array.from({length: 24}, (_, i) => `<li>Build service ${i} with ${'reliable infrastructure '.repeat(9)}.</li>`).join('') + '</ul><h2>Qualifications</h2><ul><li>Experience with Python and SQL.</li><li>Remote work is allowed only within Canada.</li></ul>';
    const result = summarizePosting(input);
    expect(text(result)).toContain('Experience with Python and SQL.');
    expect(text(result)).toContain('Remote work is allowed only within Canada.');
    expect(text(result).length).toBeLessThanOrEqual(4000);
  });
  it('uses French section labels without changing the qualification text', () => {
    const result = summarizePosting('<h2>Exigences</h2><ul><li>Expérience avec Java ou Python.</li></ul><h2>Responsabilités</h2><ul><li>Développer des services fiables.</li></ul>', 'fr');
    const doc = new DOMParser().parseFromString(result, 'text/html');
    expect([...doc.querySelectorAll('h4')].map((h) => h.textContent)).toEqual(['Exigences', 'Responsabilités']);
    expect(text(result)).toContain('Java ou Python');
  });
  it('keeps fifth and later short requirements and duties, including eligibility and working conditions', () => {
    const requirements = ['Python experience.', 'SQL experience.', 'Linux experience.', 'Git experience.', 'Experience with distributed systems.', 'At least 5 years of software engineering experience.', 'A degree or equivalent practical experience.', 'Applicants must be authorized to work in Canada; sponsorship is not available.'];
    const responsibilities = ['Build APIs.', 'Deploy services.', 'Test changes.', 'Measure latency.', 'Respond to incidents.', 'Review pull requests.', 'Work in the office three days per week.'];
    const html = '<p>Build fraud detection services.</p><h2>Requirements</h2><ul>' + requirements.map((item) => `<li>${item}</li>`).join('') + '</ul><h2>Responsibilities</h2><ul>' + responsibilities.map((item) => `<li>${item}</li>`).join('') + '</ul><h2>Benefits</h2><p>Health insurance and paid parental leave.</p>';
    const result = text(summarizePosting(html));
    for (const item of [...requirements, ...responsibilities, 'Health insurance and paid parental leave.']) expect(result).toContain(item);
  });
  it('prioritizes late requirements and eligibility over repetitive duties while keeping both sections', () => {
    const duties = Array.from({ length: 20 }, (_, i) => `<li>Build service ${i}. ${'Support reliable systems. '.repeat(6)}</li>`).join('');
    const input = `<h2>Responsibilities</h2><ul>${duties}</ul><h2>Requirements</h2><ul><li>Experience with Rust and PostgreSQL.</li><li>At least 7 years of relevant engineering experience.</li><li>Remote work is allowed only within Canada.</li><li>A bachelor's degree is normally required.</li><li>Alternatively, equivalent professional experience is accepted.</li></ul>`;
    const result = text(summarizePosting(input));
    for (const item of ['Build service 0.', 'Rust and PostgreSQL', '7 years', 'only within Canada', "A bachelor's degree", 'Alternatively, equivalent professional experience is accepted.']) expect(result).toContain(item);
    expect(result.length).toBeLessThanOrEqual(4000);
  });
  it('retains full informative headings and the second and later unlabelled role paragraphs', () => {
    const paragraphs = ['Build streaming infrastructure.', 'The authorization team owns permissioning for creators.', 'You will collaborate with product engineers and operate the production services.', 'This role uses Java, Kafka and PostgreSQL.'];
    const result = text(summarizePosting('<h2>This role is for applicants actively looking to start before December 1, 2026.</h2>' + paragraphs.map((p) => `<p>${p}</p>`).join('')));
    for (const item of [...paragraphs, 'start before December 1, 2026.']) expect(result).toContain(item);
  });
  it('retains source text in table rows and recognizes NVIDIA and About You qualifications', () => {
    const result = text(summarizePosting('<p>Build GPU drivers.</p><h2>What we need to see</h2><table><tr><td>Experience:</td><td>5 years developing C++ software.</td></tr><tr><td>Systems:</td><td>Linux and networking.</td></tr></table><p><strong>About You</strong></p><p>Experience with Python.</p>'));
    for (const item of ['Experience: 5 years developing C++ software.', 'Linux and networking.', 'Experience with Python.']) expect(result).toContain(item);
  });
  it('does not reintroduce company history or general legal text into the richer role summary', () => {
    const result = text(summarizePosting('<p>Build secure services.</p><h2>About us</h2><p>Our company has 35 years of experience and was founded by PhD graduates.</p><h2>Privacy notice</h2><p>We process application data according to our privacy policy.</p><p>Applicants must be authorized to work in Canada.</p>'));
    expect(result).toContain('Build secure services.');
    expect(result).toContain('Applicants must be authorized to work in Canada.');
    expect(result).not.toMatch(/35 years|PhD graduates|privacy policy/);
  });
  it('falls back safely if important conditions cannot all fit, instead of dropping one', () => {
    const conditions = Array.from({ length: 7 }, (_, i) => `<li>Applicants must be authorized to work in country ${i}. ${'Additional source conditions apply. '.repeat(20)}</li>`).join('');
    expect(summarizePosting(`<h2>Requirements</h2><ul>${conditions}</ul>`)).toBe('');
  });
  it('keeps French applicant conditions that appear late in the posting', () => {
    const input = '<h2>Responsabilités</h2><ul><li>Développer des services fiables.</li></ul><h2>Exigences</h2><ul><li>Au moins 5 ans d’expérience en développement.</li><li>Un diplôme ou une expérience équivalente.</li><li>Un permis de travail valide est obligatoire.</li></ul>';
    const result = text(summarizePosting(input, 'fr'));
    for (const item of ['5 ans', 'expérience équivalente', 'permis de travail', 'Développer des services fiables.']) expect(result).toContain(item);
  });
  it.each(['pane', 'modal'] as const)('includes the role-specific team context in Summary (%s)', async (variant) => {
    const description = '<h2>About the team</h2><p>The authorization team manages creator permissions using Java and PostgreSQL.</p><h2>About the role</h2><p>Build secure permission services.</p><h2>Requirements</h2><ul><li>Experience with distributed systems.</li></ul><h2>Responsibilities</h2><ul><li>Own service reliability.</li></ul>';
    vi.spyOn(apiClient, 'getJob').mockResolvedValue({ ...job, description });
    render(<JobDetailContent jobId={job.job_id} variant={variant} onClose={() => {}} />);
    await screen.findByRole('button', { name: 'Summary', exact: true });
    const section = screen.getByRole('heading', { name: 'About the job', exact: true }).closest('section')!;
    for (const item of ['authorization team', 'Java and PostgreSQL', 'Build secure permission services.', 'Own service reliability.']) expect(section).toHaveTextContent(item);
  });
  it.each(['pane', 'modal'] as const)('defaults to Summary and preserves every source section in Full Posting (%s)', async (variant) => {
    vi.spyOn(apiClient, 'getJob').mockResolvedValue(job);
    render(<JobDetailContent jobId={job.job_id} variant={variant} onClose={() => {}} />);
    const summary = await screen.findByRole('button', { name: 'Summary', exact: true });
    expect(summary).toHaveAttribute('aria-pressed', 'true');
    const section = screen.getByRole('heading', { name: 'About the job', exact: true }).closest('section')!;
    expect(section).toHaveTextContent('Additional requirement');
    await userEvent.click(screen.getByRole('button', { name: 'Full Posting', exact: true }));
    expect(within(section).getByText('Additional requirement available in the full posting.')).toBeInTheDocument();
    expect(section).toHaveTextContent('Health coverage and paid leave.');
    expect(section).toHaveTextContent('All qualified candidates are welcome.');
    expect(screen.getByRole('link', { name: /^Apply for/ })).toHaveAttribute('href', job.company_apply_url);
    await userEvent.click(summary);
    expect(section).toHaveTextContent('Additional requirement');
    expect(screen.getByRole('heading', { name: 'About the company', exact: true })).toBeInTheDocument();
  });
  it.each(['pane', 'modal'] as const)('shows Full Posting when no complete source block fits a concise Summary (%s)', async (variant) => {
    const paragraph = 'Remote work is allowed only when ' + 'the following condition is satisfied '.repeat(150) + 'and the employer approves.';
    vi.spyOn(apiClient, 'getJob').mockResolvedValue({ ...job, description: `<p>${paragraph}</p>` });
    render(<JobDetailContent jobId={job.job_id} variant={variant} onClose={() => {}} />);
    const full = await screen.findByRole('button', { name: 'Full Posting', exact: true });
    expect(full).toHaveAttribute('aria-pressed', 'true');
    const summary = screen.getByRole('button', { name: 'Summary', exact: true });
    expect(summary).toBeDisabled();
    expect(summary).toHaveAttribute('aria-pressed', 'false');
    const section = screen.getByRole('heading', { name: 'About the job', exact: true }).closest('section')!;
    expect(section).toHaveTextContent(paragraph);
    expect(section).not.toHaveTextContent('Select Full Posting to read');
  });
  it('resets the view when switching jobs and ignores the previous job content while loading', async () => {
    vi.spyOn(apiClient, 'getJob').mockResolvedValueOnce(job).mockResolvedValueOnce({ ...job, job_id: 'lever:summary-b', description: '<p>Build scheduling products.</p>' });
    const { rerender } = render(<JobDetailContent jobId={job.job_id} variant="pane" onClose={() => {}} />);
    await userEvent.click(await screen.findByRole('button', { name: 'Full Posting' }));
    rerender(<JobDetailContent jobId="lever:summary-b" variant="pane" onClose={() => {}} />);
    expect(screen.queryByText('Additional requirement available in the full posting.')).not.toBeInTheDocument();
    expect(await screen.findByRole('button', { name: 'Summary' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByText('Build scheduling products.')).toBeInTheDocument();
  });
});

it('preserves late office cadence and relocation conditions behind long responsibilities', () => {
  const cadence = 'We use a hybrid work model of 3 days in the office per week and offer relocation assistance.';
  const html = '<h2>Responsibilities</h2><ul>' + Array.from({ length: 24 }, (_, i) => `<li>Build reliable service ${i} and collaborate with engineers to improve systems and customer experiences.</li>`).join('') + '</ul><h2>Workplace</h2><p>' + cadence + '</p>';
  const result = summarizePosting(renderDescription(html, 'OpenAI', 'Software Engineer').mainHtml);
  expect(text(result)).toContain(cadence);
});
