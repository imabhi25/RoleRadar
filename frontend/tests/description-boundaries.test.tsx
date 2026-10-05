import { describe, it, expect } from 'vitest';
import { renderDescription } from '../src/utils/descriptionPipeline';
import { classifySectionHeading, isBoilerplateHeading, removeRedundantJobHeading, separateTeamIntro, structureDescription } from '../src/utils/descriptionSections';
import { STRIPE } from './fixtures/descriptions';

const dom = (html: string) => new DOMParser().parseFromString(`<body>${html}</body>`, 'text/html').body;
const text = (html: string) => dom(html).textContent!.replace(/\s+/g, ' ').trim();
const headings = (html: string) => [...dom(html).querySelectorAll('h4')].map((h) => h.textContent!.trim());
const words = (s: string) => (s.toLowerCase().match(/[\p{L}\p{N}']+/gu) ?? []);

describe('team introduction sits between the company intro and "About the Job" (Stripe greenhouse:8231439)', () => {
  const r = renderDescription(STRIPE, 'Stripe', 'Software Engineer, Metronome Infrastructure');

  it('keeps "About the team" and its paragraphs together, in their own block', () => {
    expect(headings(r.teamHtml)).toEqual(['About the team']);
    expect(text(r.teamHtml)).toContain('The Revenue and Financial Automation (RFA) team at Stripe is building');
    expect(text(r.teamHtml)).toContain('Hundreds of thousands of businesses of all sizes and types use Stripe Billing');
  });

  it('starts "About the Job" at "What you\'ll do"', () => {
    expect(headings(r.mainHtml)[0]).toBe("What you'll do");
    expect(text(r.mainHtml)).not.toContain('RFA');
    expect(headings(r.mainHtml)).toEqual(expect.arrayContaining(['Responsibilities', 'Who you are', 'Minimum requirements', 'Preferred qualifications']));
  });

  it('does not treat team content as company background', () => {
    expect(text(r.companyHtml)).toContain('Stripe is a financial infrastructure platform');
    expect(text(r.companyHtml)).not.toContain('RFA');
    expect(headings(r.companyHtml)).toEqual([]);
  });

  it('preserves wording and order: every source word appears, company → team → job', () => {
    const rendered = text(r.companyHtml + r.teamHtml + r.mainHtml + r.policiesHtml);
    const source = text(STRIPE);
    const have = new Set(words(rendered));
    // "Who we are" and "About Stripe" are the generic wrapper headings absorbed into "About the Company"
    expect(words(source).filter((w) => !have.has(w))).toEqual([]);
    const flat = r.companyHtml + r.teamHtml + r.mainHtml;
    expect(flat.indexOf('Stripe is a financial')).toBeLessThan(flat.indexOf('About the team'));
    expect(flat.indexOf('About the team')).toBeLessThan(flat.indexOf("What you'll do"));
  });
});

describe('team separation is generic and conservative', () => {
  const company = 'Acme';
  const render = (html: string) => renderDescription(html, company, 'Engineer');

  it('works for other employers and for French headings', () => {
    const en = render('<h2>About the platform team</h2><p>We run the platform.</p><h2>Responsibilities</h2><ul><li>Ship</li></ul>');
    expect(headings(en.teamHtml)).toEqual(['About the platform team']);
    expect(headings(en.mainHtml)[0]).toBe('Responsibilities');
    const fr = render("<h2>À propos de l'équipe</h2><p>Nous construisons la plateforme.</p><h2>Vos responsabilités</h2><ul><li>Livrer</li></ul>");
    expect(headings(fr.teamHtml)).toEqual(["À propos de l'équipe"]);
    expect(headings(fr.mainHtml)[0]).toBe('Vos responsabilités');
  });

  it('recognizes equivalent responsibilities headings, including French ones', () => {
    for (const h of ["What you'll do", 'Key Responsibilities', 'Your impact', 'Responsabilités', 'Vos responsabilités', 'Ce que vous ferez', 'Votre rôle', 'Rôle et responsabilités', 'Au quotidien']) {
      expect(classifySectionHeading(h), h).toBe('responsibilities');
    }
    expect(classifySectionHeading('Exigences minimales')).toBe('requirements');
    expect(classifySectionHeading('Compétences souhaitées')).toBe('preferred');
    expect(classifySectionHeading("À propos de l'équipe")).toBe('team');
    expect(classifySectionHeading("À propos d'Acme", 'Acme')).toBe('company');
    expect(classifySectionHeading('Présentation du poste')).toBe('about-role');
    // longer sentences are never classified
    expect(classifySectionHeading('Vos responsabilités incluent la gestion de plusieurs équipes dans le monde entier')).toBeNull();
  });

  it('leaves the description alone when there is no clear boundary', () => {
    // loose intro paragraph before the team section
    const loose = '<p>We are hiring.</p><h2>About the team</h2><p>Team text.</p><h2>Responsibilities</h2><ul><li>x</li></ul>';
    expect(render(loose).teamHtml).toBe('');
    // an unfamiliar heading sits before the role starts
    const unknown = '<h2>About the team</h2><p>Team text.</p><h2>Our unusual heading</h2><p>Mystery.</p><h2>Responsibilities</h2><ul><li>x</li></ul>';
    expect(render(unknown).teamHtml).toBe('');
    expect(text(render(unknown).mainHtml)).toContain('Mystery.');
    // no role-start heading at all
    expect(render('<h2>About the team</h2><p>Team text.</p><h2>Benefits</h2><p>Dental</p>').teamHtml).toBe('');
    // unstructured text
    expect(separateTeamIntro('<p>Just prose.</p>')).toEqual({ teamHtml: '', jobHtml: '<p>Just prose.</p>' });
  });

  it('never produces a second "About the Job" heading', () => {
    expect(removeRedundantJobHeading('<h2>About the Job</h2><p>Text</p>')).toBe('<p>Text</p>');
    expect(removeRedundantJobHeading('<h2>À propos du poste</h2><p>Texte</p>')).toBe('<p>Texte</p>');
    expect(removeRedundantJobHeading('<h2>About the Job Market</h2><p>Text</p>')).toContain('About the Job Market');
    const r = render('<h2>About the Job</h2><p>We build.</p><h2>Responsibilities</h2><ul><li>x</li></ul>');
    expect(headings(r.mainHtml)).toEqual(['Responsibilities']);
    expect(text(r.mainHtml)).toContain('We build.');
  });

  it('keeps employer headings, links and lists untouched in the team block', () => {
    const r = render('<h2>The team</h2><p>See <a href="https://acme.test/team">our team</a>.</p><ul><li>Ten people</li></ul><h2>What you will do</h2><p>Work.</p>');
    expect(r.teamHtml).toContain('href="https://acme.test/team"');
    expect(r.teamHtml).toContain('<li>Ten people</li>');
  });

  it('French boilerplate headings collapse into policies; French role headings never do', () => {
    expect(isBoilerplateHeading("Égalité des chances en matière d'emploi")).toBe(true);
    expect(isBoilerplateHeading('Mesures d’adaptation')).toBe(true);
    expect(isBoilerplateHeading('Responsabilités')).toBe(false);
    expect(structureDescription('<h2>Responsabilités</h2><p>x</p>', 'Acme')).toContain('data-section="responsibilities"');
  });
});
