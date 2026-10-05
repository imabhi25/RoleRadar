import { describe, it, expect } from 'vitest';
import { renderDescription } from '../src/utils/descriptionPipeline';
import { removeEmptySections } from '../src/utils/descriptionSections';
import { decodeDoubleEscapedReferences, parseAndSanitizeJobDescription } from '../src/utils/sanitizeDescription';

const text = (html: string) => new DOMParser().parseFromString(`<body>${html}</body>`, 'text/html').body.textContent!.replace(/\s+/g, ' ').trim();
const all = (r: ReturnType<typeof renderDescription>) => text(r.companyHtml + r.mainHtml + r.policiesHtml);

describe('headings that carry information survive cleanup (Stripe start date)', () => {
  const stripe = `<h2><strong>This role is for applicants actively looking to start before December 1, 2026.</strong></h2>
    <h2><strong>Who we are</strong></h2><h3><strong>About Stripe</strong></h3>
    <p>Stripe is a technology company focused on improving the conditions for economic growth and prosperity. We build programmable financial infrastructure.</p>
    <h2><strong>What you'll do</strong></h2><h3><strong>Responsibilities</strong></h3><ul><li>Ship product</li></ul>
    <h3><strong>Minimum requirements</strong></h3><ul><li>Able to start before December 1, 2026</li></ul>`;

  it('keeps a full-sentence heading even when the next node is another heading', () => {
    expect(removeEmptySections('<h2>Deadline: apply before the end of the month please.</h2><h2>Next</h2><p>x</p>')).toContain('Deadline: apply before the end of the month');
    const rendered = renderDescription(stripe, 'Stripe', 'Software Engineer, Early Career — Immediate Start');
    expect(text(rendered.mainHtml)).toContain('This role is for applicants actively looking to start before December 1, 2026.');
    expect(rendered.mainHtml.indexOf('actively looking')).toBeLessThan(rendered.mainHtml.indexOf('Responsibilities')); // source order
  });

  it('still removes a genuinely empty short label', () => {
    expect(removeEmptySections('<h3>Salary Range:</h3><h3>Benefits</h3><p>Dental</p>')).not.toContain('Salary Range');
  });

  it('the company introduction after the notice is still separated from the job', () => {
    const rendered = renderDescription(stripe, 'Stripe', 'Software Engineer, Early Career — Immediate Start');
    expect(text(rendered.companyHtml)).toContain('Stripe is a technology company');
    expect(text(rendered.mainHtml)).toContain('Responsibilities');
    expect(text(rendered.mainHtml)).not.toContain('programmable financial infrastructure');
  });
});

describe('"<Company> is looking for…" opens the job, it is not company background', () => {
  it('Thomson Reuters: role content, responsibilities and requirements stay under the job', () => {
    const raw = `<p>Thomson Reuters is looking for a<span>&nbsp;</span><b>Staff Software Engineer, AI Product Engineering</b><span>&nbsp;</span>to help shape the next generation of AI-powered software.</p>
      <h2>About the Role</h2><p>You will design services.</p><h2>About You</h2><ul><li>8 years of experience</li></ul>`;
    const rendered = renderDescription(raw, 'Thomson Reuters', 'Staff Software Engineer, AI Product Engineering');
    expect(rendered.companyHtml).toBe('');
    expect(text(rendered.mainHtml)).toContain('Thomson Reuters is looking for a Staff Software Engineer, AI Product Engineering to help shape');
    expect(text(rendered.mainHtml)).toContain('8 years of experience');
  });

  it('NVIDIA: only the genuine introduction is company text; the hiring sentence and everything after stay with the job', () => {
    const raw = `<p>NVIDIA has been transforming computer graphics, PC gaming, and accelerated computing for more than 25 years. It’s a unique legacy of innovation.</p>
      <p>NVIDIA is seeking a Software Engineer to join our DPU platform team.</p><h2>What you'll be doing</h2><ul><li>Write drivers</li></ul>
      <h2>What we need to see</h2><ul><li>BS in CS</li></ul>`;
    const rendered = renderDescription(raw, 'NVIDIA', 'Software Engineer - DPU Platform');
    expect(text(rendered.companyHtml)).toContain('NVIDIA has been transforming');
    expect(text(rendered.companyHtml)).not.toContain('is seeking');
    expect(text(rendered.mainHtml)).toContain('NVIDIA is seeking a Software Engineer');
    expect(text(rendered.mainHtml)).toContain('Write drivers');
    expect(text(rendered.mainHtml)).toContain('BS in CS');
  });

  it('a section that opens as company text is cut at its first job signal, not taken whole', () => {
    const raw = `<h2>A World-Changing Company</h2><p>Palantir builds the world’s leading software for data-driven decisions and operations.</p>
      <p>We are a software engineering team enabling ML models in production. You will own services end-to-end.</p><h2>Responsibilities</h2><ul><li>Rust</li></ul>`;
    const rendered = renderDescription(raw, 'Palantir', 'Software Engineer - Hosted Model Infrastructure');
    expect(text(rendered.companyHtml)).toContain('Palantir builds the world');
    expect(text(rendered.companyHtml)).not.toContain('You will own services');
    expect(text(rendered.mainHtml)).toContain('You will own services');
  });
});

describe('Greenhouse intro wrappers and hook lines', () => {
  it('Coinbase: the mission paragraph (with its one-line hook) is About the Company', () => {
    const raw = `<div class="content-intro"><p>Ready to do the most impactful work of your career? At <a href="https://www.coinbase.com/">Coinbase</a>, we are uncompromising on our mission to increase economic freedom. The bar is high.</p></div>
      <p>We're hiring a Senior Software Engineer to join the Retail DEX team.</p><h3>What you'll do</h3><ul><li>Build</li></ul>`;
    const rendered = renderDescription(raw, 'Coinbase', 'Senior Software Engineer, Retail DEX');
    expect(text(rendered.companyHtml)).toContain('we are uncompromising on our mission');
    expect(text(rendered.companyHtml)).not.toContain("We're hiring");
    expect(text(rendered.mainHtml)).toContain("We're hiring a Senior Software Engineer");
    expect(rendered.companyHtml + rendered.mainHtml).not.toContain('content-intro');
  });

  it('Anthropic: a heading inside the wrapper still counts, and role text stays with the job', () => {
    const raw = `<div class="content-intro"><h2>About Anthropic</h2><p>Anthropic’s mission is to create reliable, interpretable, and steerable AI systems.</p></div>
      <h2>About the role:</h2><p>As an Applied AI team member at Anthropic, you will work with enterprise teams.</p>`;
    const rendered = renderDescription(raw, 'Anthropic', 'Applied AI Engineer');
    expect(text(rendered.companyHtml)).toContain('Anthropic’s mission');
    expect(text(rendered.mainHtml)).toContain('you will work with enterprise teams');
  });

  it('an empty wrapper plus a team section is not invented into a company introduction', () => {
    const raw = `<div class="content-intro"><p> </p></div><h2>About the Team</h2><p>The Code Quality team owns test infrastructure.</p>`;
    const rendered = renderDescription(raw, 'DoorDash', 'Software Engineer');
    expect(rendered.companyHtml).toBe('');
    expect(text(rendered.mainHtml)).toContain('Code Quality team');
  });

  it('a company paragraph that goes on to describe this opening stays with the job', () => {
    const raw = `<p>Reddit is a community of communities.</p><p>Reddit is poised to grow. We are looking for a Senior Data Scientist to lead fraud detection. You will partner with Ads.</p>`;
    const rendered = renderDescription(raw, 'Reddit', 'Senior Data Scientist');
    expect(text(rendered.mainHtml)).toContain('We are looking for a Senior Data Scientist');
  });
});

describe('text artifacts are repaired without losing words', () => {
  it('whitespace-only inline spans stay a space (no glued words)', () => {
    const { html } = parseAndSanitizeJobDescription('<p>looking for a<span>&nbsp;</span><b>Staff Engineer</b><span> </span>to help with k8s<span>&nbsp;</span>and<span>&nbsp;</span>Argo</p>', 'X');
    expect(text(html)).toBe('looking for a Staff Engineer to help with k8s and Argo');
  });

  it('decodes doubly escaped character references', () => {
    expect(decodeDoubleEscapedReferences('varies.&amp;#xa;&amp;#xa;For Ontario')).toContain('<br><br>');
    const { html } = parseAndSanitizeJobDescription('<p>Salary varies across locations.&amp;#xa;&amp;#xa;For Ontario candidates &amp;#x2013; see below &amp;amp; beyond</p>', 'X');
    expect(text(html)).not.toMatch(/&#|&amp;/);
    expect(text(html)).toContain('For Ontario candidates – see below');
    expect(decodeDoubleEscapedReferences('keep &amp;#60;script&amp;#62; escaped')).toContain('&amp;#60;script');
  });

  it('removes ATS-only tags but keeps meaningful hashtags', () => {
    const { html } = parseAndSanitizeJobDescription('<p>Great team. #LI-remote, #LI-JS5</p><p>#LI-Hybrid</p><p>​#LI- SB1</p><p>Join the #BlackInTech community and work #Remote.</p>', 'X');
    expect(text(html)).not.toMatch(/#LI/i);
    expect(text(html)).toContain('Great team.');
    expect(text(html)).toContain('#BlackInTech');
    expect(text(html)).toContain('#Remote');
    expect(html.match(/<p/g)?.length).toBe(2); // the tag-only paragraphs are gone
  });

  it('renders **bold** inside HTML, including emphasis that spans a link or has loose markers', () => {
    const { html } = parseAndSanitizeJobDescription('<p>**Travel to Office expectations** apply.</p><p>**This is a hybrid role in our <a href="https://x.test/dublin">Dublin office</a> .**</p><p><strong>*** This is a hybrid role ***</strong></p><p><b>***Please note this position is Toronto.</b></p>', 'X');
    expect(html).not.toContain('*');
    expect(html).toContain('<strong>Travel to Office expectations</strong>');
    expect(html).toContain('href="https://x.test/dublin"');
    expect(text(html)).toContain('Dublin office');
  });

  it('bare top-level text with <br> line breaks keeps its line breaks and becomes real lists', () => {
    const raw = 'Want to build great things? Join a team.<br/><br/>- Own and ship features<br/>- Design systems<br/><br/>Key job responsibilities<br/>- Build services<br/>- Operate them';
    const { html } = parseAndSanitizeJobDescription(raw, 'Amazon');
    const doc = new DOMParser().parseFromString(`<body>${html}</body>`, 'text/html');
    expect(doc.querySelectorAll('li').length).toBe(4);
    expect(text(html)).not.toMatch(/team\.- Own|features- Design|responsibilities- Build/);
    const rendered = renderDescription(raw, 'Amazon', 'SDE');
    expect(all(rendered)).toContain('Key job responsibilities');
    expect(all(rendered)).toContain('Operate them');
  });
});

describe('labels keep their values (RBC-style nested wrappers and loose text)', () => {
  it('a bold label inside a chain of wrapper divs followed by loose text is kept with its value', () => {
    const deep = (label: string) => `${'<div>'.repeat(12)}<p><b>${label}</b></p>${'</div>'.repeat(12)}`;
    const raw = `<p><u><b>Additional Job Details</b></u></p>${deep('Address:')}777 BAY ST, TH 27:TORONTO${deep('Posted Date:')}2025-11-27${deep('Application Deadline:')}2026-10-05<p>Our Employment Opportunities</p>`;
    const rendered = renderDescription(raw, 'RBC', 'Senior Engineer');
    const out = all(rendered);
    // Confidently recognized label/value pairs move to the header (and are not shown twice); the rest keeps its
    // label, value and source order.
    expect(rendered.meta.address).toBe('777 BAY ST, TH 27:TORONTO');
    expect(rendered.meta.deadline).toBe('2026-10-05');
    expect(out).not.toMatch(/Address:|777 BAY ST|Application Deadline/);
    expect(out).toContain('Additional Job Details');
    expect(out).toMatch(/Posted Date:\s*2025-11-27/);
    expect(out.indexOf('Posted Date:')).toBeLessThan(out.indexOf('Our Employment Opportunities')); // source order
  });

  it('a label with nothing after it is still removed', () => {
    const out = all(renderDescription('<p>Real content here.</p><p><b>Job Category:</b></p>', 'RBC', 'Engineer'));
    expect(out).toContain('Real content here.');
    expect(out).not.toContain('Job Category');
  });
});

describe('a heading that titles a block of labelled fields is kept', () => {
  it('"Additional Job Details" followed by "Address:" keeps its title', () => {
    const out = removeEmptySections('<h2><b>Additional Job Details</b></h2><h2><b>Address:</b></h2><p>16 York St</p><h2><b>City:</b></h2><p>Toronto</p>');
    expect(text(out)).toContain('Additional Job Details');
    expect(text(out)).toContain('Address:');
  });
});


describe('mixed company and role paragraphs are preserved under the job', () => {
  it.each([
    ['NVIDIA', 'At NVIDIA, as a Principal Rack Scale Systems Infrastructure Engineer, you will build software systems.'],
    ['Toast', 'Toast is growing our engineering team. You will own high-impact services.'],
    ['Acme', 'Acme builds tools. As a software engineer, build our next platform.'],
  ])('%s: a company name must not override a job signal within the paragraph', (company, paragraph) => {
    const raw = `<p>${company} is a technology company building useful products.</p><p>${paragraph}</p><h2>Responsibilities</h2><ul><li>Ship reliable software.</li></ul>`;
    const result = renderDescription(raw, company, 'Software Engineer');
    expect(text(result.companyHtml)).not.toContain(paragraph);
    expect(text(result.mainHtml)).toContain(paragraph);
  });
});
