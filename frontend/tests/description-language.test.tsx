import { describe, it, expect } from 'vitest';
import { renderDescription } from '../src/utils/descriptionPipeline';
import { analyzeLanguage, classifyText } from '../src/utils/descriptionLanguage';
import { parseAndSanitizeJobDescription } from '../src/utils/sanitizeDescription';
import { AMAZON_BILINGUAL, AUTODESK_BILINGUAL, FRENCH_ONLY, STRIPE } from './fixtures/descriptions';

const dom = (html: string) => new DOMParser().parseFromString(`<body>${html}</body>`, 'text/html').body;
const text = (html: string) => dom(html).textContent!.replace(/\s+/g, ' ').trim();
const shown = (r: ReturnType<typeof renderDescription>) => text(r.companyHtml + ' ' + r.teamHtml + ' ' + r.mainHtml + ' ' + r.policiesHtml);
const headings = (html: string) => [...dom(html).querySelectorAll('h4')].map((h) => h.textContent!.trim());
const words = (s: string) => s.toLowerCase().match(/[\p{L}\p{N}']+/gu) ?? [];

describe('language detection', () => {
  it('tells clear French from clear English and leaves short or mixed text unlabelled', () => {
    expect(classifyText("Nous recherchons un(e) stagiaire en génie logiciel pour rejoindre notre équipe.")).toBe('fr');
    expect(classifyText('We are seeking an intern to join our engineering team and build things.')).toBe('en');
    expect(classifyText('26WD101101')).toBeNull();
    expect(classifyText('Python, Go')).toBeNull();
  });
});

describe('bilingual Amazon posting (amazon:10565854): halves interleaved per section with "-----" rules', () => {
  const en = renderDescription(AMAZON_BILINGUAL, 'Amazon', 'Senior AI/ML Architect', 'en');
  const fr = renderDescription(AMAZON_BILINGUAL, 'Amazon', 'Senior AI/ML Architect', 'fr');
  const original = renderDescription(AMAZON_BILINGUAL, 'Amazon', 'Senior AI/ML Architect', 'original');

  it('offers English, French and the original, and defaults to English', () => {
    expect(en.views).toEqual(['en', 'fr', 'original']);
    expect(renderDescription(AMAZON_BILINGUAL, 'Amazon', 'x').view).toBe('en');
    expect(en.language).toBe('en');
    expect(fr.language).toBe('fr');
    expect(original.language).toBeNull();
  });

  it('the English view has the English half and the French view the French half', () => {
    expect(shown(en)).toContain('AWS Global Sales drives adoption of the AWS cloud worldwide');
    expect(shown(en)).not.toContain("AWS Global Sales favorise l'adoption du cloud");
    expect(shown(fr)).toContain("AWS Global Sales favorise l'adoption du cloud");
    expect(shown(fr)).not.toContain('AWS Global Sales drives adoption of the AWS cloud worldwide');
    expect(shown(en)).not.toMatch(/-{5,}/);
  });

  it('keeps the French fluency requirement explicit in the English view', () => {
    expect(shown(en)).toContain('Fluency in French and English is required');
    expect(shown(fr)).toContain("La maîtrise du français et de l'anglais est requise");
  });

  it('never drops shared or untranslated material: salary, links and unpaired French text stay in every view', () => {
    for (const r of [en, fr]) expect(shown(r)).toContain('CAN, QC, Montreal - 126,000.00 - 210,400.00 CAD annually');
    // the French salary paragraph has no English counterpart in the source, so the English view keeps it
    expect(shown(en)).toContain("L'échelle salariale de base pour ce poste est indiquée ci-dessous");
    // the shared English headings serve both halves
    for (const h of ['Basic Qualifications', 'Preferred Qualifications']) {
      expect(headings(en.mainHtml + en.teamHtml)).toContain(h);
      expect(headings(fr.mainHtml + fr.teamHtml)).toContain(h);
    }
    // "Key job responsibilities" is a plain line in the source (not a heading element): still in both views
    for (const r of [en, fr]) expect(shown(r)).toContain('Key job responsibilities');
  });

  it('every word of the original appears in at least one view (nothing is lost by separating)', () => {
    const union = new Set(words(shown(en) + ' ' + shown(fr)));
    const source = words(text(parseAndSanitizeJobDescription(AMAZON_BILINGUAL, 'Amazon').html).replace(/-{3,}/g, ' '));
    expect(source.filter((w) => !union.has(w))).toEqual([]);
  });

  it('the original view is the unsplit text with both languages', () => {
    expect(shown(original)).toContain('AWS Global Sales drives adoption');
    expect(shown(original)).toContain("AWS Global Sales favorise l'adoption");
  });
});

describe('bilingual Autodesk posting: whole French half, then the whole English half', () => {
  const en = renderDescription(AUTODESK_BILINGUAL, 'Autodesk', 'Intern, Software Developer', 'en');
  const fr = renderDescription(AUTODESK_BILINGUAL, 'Autodesk', 'Intern, Software Developer', 'fr');

  it('splits the halves, drops only the "English will follow" marker and the rule', () => {
    expect(en.views).toEqual(['en', 'fr', 'original']);
    expect(shown(en)).toContain('We are seeking a highly motivated Software Developer intern');
    expect(shown(en)).not.toContain('Nous recherchons un(e) stagiaire');
    expect(shown(fr)).toContain('Nous recherchons un(e) stagiaire');
    expect(shown(fr)).not.toContain('We are seeking a highly motivated');
    for (const r of [en, fr]) expect(shown(r)).not.toMatch(/English will follow|-{10,}/);
  });

  it('keeps shared material (requisition id) and the English-only trailing sections in both views', () => {
    for (const r of [en, fr]) {
      expect(shown(r)).toContain('26WD101101');
      expect(shown(r)).toContain('In-Person Onboarding and Identity Verification');
      expect(shown(r)).toContain('Salary transparency');
    }
  });

  it('structures French headings like English ones (shared pipeline)', () => {
    expect(headings(fr.mainHtml + fr.teamHtml)).toEqual(expect.arrayContaining(['Responsabilités']));
    expect(fr.mainHtml).toContain('<li>');
  });
});

describe('French-only posting', () => {
  const r = renderDescription(FRENCH_ONLY, 'Autodesk', 'Stagiaire en développement logiciel');

  it('is recognized as French, shown as published, with no language toggle and no fabricated translation', () => {
    expect(r.language).toBe('fr');
    expect(r.views).toEqual([]);
    expect(shown(r)).toContain('Nous recherchons un(e) stagiaire en génie logiciel');
    expect(shown(r)).not.toMatch(/We are seeking|Translated from French|Read in English/);
  });

  it('formats French headings, paragraphs and lists through the shared pipeline', () => {
    expect(headings(r.mainHtml)).toEqual(expect.arrayContaining(['Responsabilités', 'Exigences minimales', 'Compétences souhaitées']));
    expect(r.mainHtml).toContain('<li>');
    expect(shown(r)).toContain('Implémenter des prototypes et des composants de logiciel');
  });
});

describe('separation is conservative', () => {
  it('English-only descriptions are never split', () => {
    expect(renderDescription(STRIPE, 'Stripe', 'x').views).toEqual([]);
    expect(analyzeLanguage('<p>Hello there, this is plain English text for the role you will do.</p>').bilingual).toBe(false);
  });

  it('a French text with an English legal footer is not a bilingual pair', () => {
    const fr = FRENCH_ONLY;
    const footer = '<p>Autodesk is an equal opportunity employer and welcomes applicants from all backgrounds.</p><p>We will make reasonable accommodations for candidates with disabilities during the hiring process.</p>';
    expect(analyzeLanguage(parseAndSanitizeJobDescription(fr + footer, 'Autodesk').html).bilingual).toBe(false);
    expect(renderDescription(fr + footer, 'Autodesk', 'x').views).toEqual([]);
  });

  it('interleaved sentences without paired runs stay whole', () => {
    const raw = '<p>Nous construisons des logiciels pour nos clients partout dans le monde entier avec passion.</p><p>We build software for customers all around the world with passion and care.</p><p>Vous travaillerez avec une équipe dans un environnement dynamique et collaboratif.</p>';
    expect(renderDescription(raw, 'Acme', 'x').views).toEqual([]);
  });

  it('refuses to hide a French-only language requirement from the English view', () => {
    const fr = '<h2>Présentation du poste</h2><p>Nous recherchons une personne bilingue pour rejoindre notre équipe de développement logiciel, avec une expérience solide dans la création de services infonuagiques à grande échelle.</p><p>Vous collaborerez avec des collègues talentueux et vous contribuerez à des projets significatifs pour nos clients partout au pays.</p>';
    const en = '<p>---------------------</p><h2>Position Overview</h2><p>We are looking for a person to join our software development team, with solid experience building cloud services at a very large scale for customers.</p><p>You will collaborate with talented colleagues and contribute to meaningful projects for our customers across the country.</p>';
    expect(analyzeLanguage(parseAndSanitizeJobDescription(fr + en, 'Acme').html).bilingual).toBe(false);
    // the same posting where the English half repeats the requirement does split
    const enOk = en.replace('a person to join', 'a bilingual (French and English) person to join');
    expect(analyzeLanguage(parseAndSanitizeJobDescription(fr + enOk, 'Acme').html).bilingual).toBe(true);
  });
});
