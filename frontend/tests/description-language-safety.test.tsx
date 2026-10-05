import { describe, it, expect } from 'vitest';
import { analyzeLanguage } from '../src/utils/descriptionLanguage';
import { cognateOverlap, extractFacts, factsAgree, normalizeNumber } from '../src/utils/descriptionCorrespondence';
import { renderDescription } from '../src/utils/descriptionPipeline';
import { parseAndSanitizeJobDescription } from '../src/utils/sanitizeDescription';
import { AMAZON_BILINGUAL, AUTODESK_BILINGUAL } from './fixtures/descriptions';

const text = (html: string) => new DOMParser().parseFromString(`<body>${html}</body>`, 'text/html').body.textContent!.replace(/\s+/g, ' ').trim();
const p = (...paragraphs: string[]) => paragraphs.map((t) => `<p>${t}</p>`).join('');
const rule = '<hr>';

// A faithful French/English pair, written by hand: same structure, same facts, genuinely translated.
const FR_1 = 'Nous recherchons un développeur logiciel expérimenté pour rejoindre notre équipe de la plateforme infonuagique. Vous concevrez et développerez des services fiables pour nos clients partout dans le monde.';
const EN_1 = 'We are looking for an experienced software developer to join our cloud platform team. You will design and build reliable services for our customers around the world.';
const FR_2 = "Notre équipe offre un environnement collaboratif et des occasions d'apprentissage continu pour tous les employés de l'entreprise.";
const EN_2 = 'Our team offers a collaborative environment and continuous learning opportunities for all employees of the company.';
const FR_4 = 'Nous offrons un salaire concurrentiel, une assurance collective et un régime de retraite pour tous nos employés à temps plein.';
const EN_4 = 'We offer a competitive salary, group insurance and a retirement plan for all of our full-time employees.';
const FR_3 = "Le poste exige trois années d'expérience en développement logiciel et une bonne maîtrise des systèmes distribués.";
const EN_3 = 'The role requires three years of experience in software development and a strong command of distributed systems.';

// Real-shaped sentences that exist in only one language.
const FR_ONLY_REQUIREMENT = "Vous devez travailler au bureau de Montréal trois jours par semaine et vous déplacer chez nos clients à l'occasion.";
const EN_ONLY_REQUIREMENT = 'Candidates must hold a valid driver licence and be authorised to work in Canada without sponsorship.';
const EN_UNRELATED = 'Our company is committed to supporting your career and celebrates the achievements of every member of the group.';

const faithful = () => p(FR_1, FR_2, FR_3) + rule + p(EN_1, EN_2, EN_3);

describe('the exact reproduction: unrelated French and English paragraphs of similar size', () => {
  const fr =
    'Vous devez travailler au bureau de Montréal trois jours par semaine. La rémunération annuelle pour ce poste est de 120 000 dollars. Nous recherchons une personne avec cinq années d’expérience dans les systèmes distribués. Vous serez responsable de la sécurité des services et de la fiabilité des applications. Notre équipe vous accompagne dans votre développement professionnel. ';
  const en =
    'Our company builds reliable software for customers around the world. We are committed to supporting your career and helping you learn from experienced engineers. You will collaborate with our team to deliver useful products and improve the quality of our services. We offer a welcoming environment for everyone and opportunities to grow with the company. Your contributions will shape the future of our products.';
  const raw = `<p>${fr}</p><p>${en}</p>`;

  it('is not treated as a translation: the complete original is the only view', () => {
    const result = analyzeLanguage(raw);
    expect(result.bilingual).toBe(false);
    expect(result.views).toEqual([]);
    expect(result.fallbackReason).toMatch(/no passage/);
    expect(result.html.en).toBe(raw);
    expect(result.html.fr).toBe(raw);
  });

  it('shows salary, office attendance and the experience requirement through the whole pipeline', () => {
    const r = renderDescription(raw, 'Acme', 'Engineer');
    const shown = text(r.mainHtml + r.companyHtml + r.teamHtml);
    expect(r.views).toEqual([]);
    for (const needle of ['120 000 dollars', 'trois jours par semaine', 'cinq années', 'Our company builds reliable software']) expect(shown).toContain(needle);
  });

  it('even when separated by a rule or an "English will follow" marker', () => {
    for (const glue of [rule, '<p>English will follow</p>', '<p>------------</p>']) {
      const result = analyzeLanguage(`<p>${fr}</p>${glue}<p>${en}</p>`);
      expect(result.bilingual).toBe(false);
      expect(text(result.html.original)).toContain('120 000');
    }
  });

  it('also when the paragraphs are headed like a bilingual posting', () => {
    const result = analyzeLanguage(`<h2>Poste</h2><p>${fr}</p><h2>Position</h2><p>${en}</p>`);
    expect(result.bilingual).toBe(false);
  });
});

describe('unverified mixed-language passages next to a verified translation', () => {
  const reproFr = 'Vous devez travailler au bureau de Montréal trois jours par semaine. La rémunération annuelle pour ce poste est de 120 000 dollars. Nous recherchons une personne avec cinq années d’expérience dans les systèmes distribués. Vous serez responsable de la sécurité des services et de la fiabilité des applications. Notre équipe vous accompagne dans votre développement professionnel.';
  const reproEn = 'Our company builds reliable software for customers around the world. We are committed to supporting your career and helping you learn from experienced engineers. You will collaborate with our team to deliver useful products and improve the quality of our services. We offer a welcoming environment for everyone and opportunities to grow with the company. Your contributions will shape the future of our products.';

  it('a large unverified passage makes the whole posting ambiguous: the original is the only view', () => {
    const raw = p(FR_1, FR_2, FR_3) + rule + p(EN_1, EN_2, EN_3) + p(reproFr) + p(reproEn);
    const result = analyzeLanguage(raw);
    expect(result.bilingual).toBe(false);
    expect(result.fallbackReason).toMatch(/substantial part|matched/);
    expect(text(result.html.original)).toContain('120 000 dollars');
  });

  it('a small unverified boilerplate pair is tolerated and kept in both views', () => {
    const noticeFr = "Cet emploi peut exiger une vérification d'identité en personne.";
    const noticeEn = 'This role may require in-person identity verification.';
    const raw = p(FR_1, FR_2, FR_3, FR_4) + rule + p(EN_1, EN_2, EN_3, EN_4) + p(noticeFr) + p(noticeEn);
    const result = analyzeLanguage(raw);
    expect(result.bilingual).toBe(true);
    for (const view of [result.html.en, result.html.fr]) {
      expect(text(view)).toContain("vérification d'identité");
      expect(text(view)).toContain('in-person identity verification');
    }
  });
});

describe('a faithful translation is still separated', () => {
  const result = analyzeLanguage(faithful());
  it('offers English, French and the original, each complete for its language', () => {
    expect(result.bilingual).toBe(true);
    expect(result.views).toEqual(['en', 'fr', 'original']);
    expect(text(result.html.en)).toBe(text(p(EN_1, EN_2, EN_3)));
    expect(text(result.html.fr)).toBe(text(p(FR_1, FR_2, FR_3)));
  });
});

describe('French-only requirements embedded in an otherwise paired-looking passage', () => {
  it('an extra French requirement paragraph stays in the English view (and in the French one)', () => {
    const raw = p(FR_1, FR_ONLY_REQUIREMENT, FR_2, FR_3) + rule + p(EN_1, EN_2, EN_3);
    const result = analyzeLanguage(raw);
    expect(result.bilingual).toBe(true);
    expect(text(result.html.en)).toContain('trois jours par semaine');
    expect(text(result.html.en)).toContain('Montréal');
    expect(text(result.html.fr)).toContain('trois jours par semaine');
    // the translated paragraphs are still separated
    expect(text(result.html.en)).not.toContain('Nous recherchons un développeur');
  });

  it('with equal paragraph counts, an unrelated English paragraph in the same position does not hide it', () => {
    const raw = p(FR_1, FR_2, FR_ONLY_REQUIREMENT, FR_3, FR_4) + rule + p(EN_1, EN_2, EN_UNRELATED, EN_3, EN_4);
    const result = analyzeLanguage(raw);
    expect(result.bilingual).toBe(true);
    expect(text(result.html.en)).toContain('trois jours par semaine'); // unmatched French is kept, not dropped
    expect(text(result.html.en)).toContain('Montréal');
    expect(text(result.html.fr)).toContain('celebrates the achievements'); // and so is the unmatched English
  });

  it('when too little of the passage can be matched, nothing is separated at all', () => {
    const raw = p(FR_1, FR_ONLY_REQUIREMENT, FR_3) + rule + p(EN_1, EN_UNRELATED, EN_3);
    const result = analyzeLanguage(raw);
    expect(result.bilingual).toBe(false);
    expect(result.fallbackReason).toMatch(/matched/);
    expect(text(result.html.original)).toContain('trois jours par semaine');
  });

  it('a French requirement inside a list item is kept when its English list has no counterpart', () => {
    const fr = '<ul><li>Trois années d’expérience en développement logiciel et en systèmes distribués</li><li>Disponibilité pour travailler au bureau de Montréal selon un horaire hybride</li><li>Bonne maîtrise des outils de développement et de test</li></ul>';
    const en = '<ul><li>Three years of experience in software development and distributed systems</li><li>Strong command of development and testing tools</li></ul>';
    const result = analyzeLanguage(p(FR_1, FR_2) + fr + rule + p(EN_1, EN_2) + en);
    expect(result.bilingual).toBe(true);
    expect(text(result.html.en)).toContain('horaire hybride');
    expect(text(result.html.en)).not.toContain('Bonne maîtrise des outils'); // translated neighbour: separated
    expect(text(result.html.en)).toContain('Strong command of development and testing tools');
  });

  it('a French language requirement that the English half omits keeps the whole original', () => {
    const fr = p(FR_1, "Le candidat doit être bilingue et maîtriser le français à l'oral comme à l'écrit pour collaborer avec nos clients.", FR_3);
    const en = p(EN_1, 'The candidate must collaborate with our customers in writing and in conversation every day.', EN_3);
    const result = analyzeLanguage(fr + rule + en);
    expect(result.bilingual).toBe(false);
    expect(text(result.html.original)).toContain('bilingue');
  });
});

describe('English-only requirements absent from the French portion', () => {
  it('stay visible in the French view', () => {
    const result = analyzeLanguage(p(FR_1, FR_2, FR_3) + rule + p(EN_1, EN_ONLY_REQUIREMENT, EN_2, EN_3));
    expect(result.bilingual).toBe(true);
    expect(text(result.html.fr)).toContain('valid driver licence');
    expect(text(result.html.fr)).toContain('authorised to work in Canada');
    expect(text(result.html.en)).toContain('valid driver licence');
  });

  it('an English paragraph with a salary figure that the French lacks is never dropped', () => {
    const salary = 'The annual salary range for this position is 95,000 to 120,000 CAD, plus benefits and a performance bonus.';
    const result = analyzeLanguage(p(FR_1, FR_2, FR_3) + rule + p(EN_1, EN_2, EN_3, salary));
    expect(text(result.html.fr)).toContain('95,000 to 120,000 CAD');
    expect(text(result.html.en)).toContain('95,000 to 120,000 CAD');
  });
});

describe('matching numbers with different meanings', () => {
  it('equal digits are not enough: days of leave vs years of experience', () => {
    const fr = p("Vous bénéficiez de 5 jours de congé payé par année, d'un régime d'assurance collective et de plusieurs avantages sociaux pour vous et votre famille.");
    const en = p('Candidates need 5 years of experience building distributed software systems and mentoring other engineers on the team.');
    const result = analyzeLanguage(fr + rule + en);
    expect(result.bilingual).toBe(false);
    expect(text(result.html.original)).toContain('5 jours de congé');
  });

  it('inside an otherwise faithful pair, the mismatched units are kept in both views', () => {
    const fr = p(FR_1, 'Vous bénéficiez de 5 jours de congé payé par année et de plusieurs avantages sociaux pour votre famille.', FR_3);
    const en = p(EN_1, 'Candidates need 5 years of experience building distributed software systems and mentoring other engineers.', EN_3);
    const result = analyzeLanguage(fr + rule + en);
    expect(result.bilingual).toBe(true);
    expect(text(result.html.en)).toContain('5 jours de congé payé');
    expect(text(result.html.fr)).toContain('5 years of experience building');
  });

  it('written numbers, grouping and units are compared by meaning', () => {
    expect(normalizeNumber('120 000')).toBe('120000');
    expect(normalizeNumber('120,000.00')).toBe('120000');
    expect(normalizeNumber('120.000,00')).toBe('120000');
    expect(normalizeNumber('1,5')).toBe('1.5');
    expect(factsAgree(extractFacts('trois jours par semaine'), extractFacts('three days per week'))).toBe(true);
    expect(factsAgree(extractFacts('trois jours par semaine'), extractFacts('three years of experience'))).toBe(false);
    expect(factsAgree(extractFacts('le 30 octobre 2026'), extractFacts('on October 30, 2026'))).toBe(true);
    expect(factsAgree(extractFacts('le 30 octobre 2026'), extractFacts('on November 30, 2026'))).toBe(false);
    expect(factsAgree(extractFacts('120 000 $'), extractFacts('$120,000'))).toBe(true);
    expect(factsAgree(extractFacts('120 000 $'), extractFacts('$125,000'))).toBe(false);
  });
});

describe('unequal section counts and unmatched trailing disclosures', () => {
  const fr = '<h2>Description</h2>' + p(FR_1) + '<h2>Exigences</h2>' + p(FR_3);
  const en =
    '<h2>Description</h2>' + p(EN_1) + '<h2>Requirements</h2>' + p(EN_3) +
    '<h2>Salary transparency</h2>' + p('The base salary range for this position is 105,000 to 140,000 CAD per year, depending on experience and location.') +
    '<h2>Accommodations</h2>' + p('Accommodations are available on request during every stage of the hiring process for candidates with disabilities.');

  it('trailing English-only sections appear in the French view too', () => {
    const result = analyzeLanguage(fr + rule + en);
    expect(result.bilingual).toBe(true);
    expect(text(result.html.fr)).toContain('105,000 to 140,000 CAD');
    expect(text(result.html.fr)).toContain('Accommodations are available on request');
    expect(text(result.html.fr)).not.toContain('We are looking for an experienced software developer');
    expect(text(result.html.en)).toContain('105,000 to 140,000 CAD');
  });

  it('trailing French-only disclosures appear in the English view too', () => {
    const result = analyzeLanguage(fr + p("Des mesures d'adaptation sont offertes sur demande tout au long du processus d'embauche pour les personnes handicapées.") + rule + en.split('<h2>Salary')[0]);
    expect(text(result.html.en)).toContain("mesures d'adaptation");
  });

  it('a misaligned extra section in the middle does not shift matches onto unrelated text', () => {
    const middleExtra = '<h2>Description</h2>' + p(EN_1) + '<h2>Perks</h2>' + p('Free lunches every Friday, a generous learning budget of 2,000 dollars per year and a quiet room for focused work.') + '<h2>Requirements</h2>' + p(EN_3);
    const result = analyzeLanguage(fr + rule + middleExtra);
    if (result.bilingual) {
      for (const view of [result.html.en, result.html.fr]) expect(text(view)).toContain('2,000 dollars');
    } else {
      expect(text(result.html.original)).toContain('2,000 dollars');
    }
  });
});

describe('mismatched postings are never paired', () => {
  it('the French half of one real posting next to the English half of a different one stays whole', () => {
    const autodesk = analyzeLanguage(parseAndSanitizeJobDescription(AUTODESK_BILINGUAL, 'Autodesk').html);
    const amazon = analyzeLanguage(parseAndSanitizeJobDescription(AMAZON_BILINGUAL, 'Amazon').html);
    const frAutodesk = autodesk.html.fr.split('<h2>About the Canada')[0];
    const enAmazon = amazon.html.en;
    const mixed = analyzeLanguage(frAutodesk + rule + enAmazon);
    expect(mixed.bilingual).toBe(false);
  });
});

describe('real bilingual postings: units that exist in only one language are not hidden', () => {
  const amazon = analyzeLanguage(parseAndSanitizeJobDescription(AMAZON_BILINGUAL, 'Amazon').html);
  const autodesk = analyzeLanguage(parseAndSanitizeJobDescription(AUTODESK_BILINGUAL, 'Autodesk').html);

  it('Amazon: still split, and the French-only preferred qualification is also in the English view', () => {
    expect(amazon.bilingual).toBe(true);
    // The French "Preferred Qualifications" list has seven items, the English list six: the first (a master's degree
    // in engineering, computer science, ...) has no English counterpart in the source.
    expect(text(amazon.html.en)).toContain('Maîtrise en génie, informatique, apprentissage automatique');
    expect(text(amazon.html.fr)).toContain('Maîtrise en génie, informatique, apprentissage automatique');
    // its translated neighbours are separated as before
    expect(text(amazon.html.en)).toContain('Experience developing experimental and analytic plans');
    expect(text(amazon.html.en)).not.toContain("Expérience dans l'élaboration de plans expérimentaux");
    expect(text(amazon.html.fr)).toContain("Expérience dans l'élaboration de plans expérimentaux");
    expect(text(amazon.html.fr)).not.toContain('Experience developing experimental and analytic plans');
  });

  it('Autodesk: still split, and the French-only unit-testing requirement is also in the English view', () => {
    expect(autodesk.bilingual).toBe(true);
    expect(text(autodesk.html.en)).toContain('test unitaire et en développement basé sur les tests');
    expect(text(autodesk.html.fr)).toContain('test unitaire et en développement basé sur les tests');
    expect(text(autodesk.html.en)).toContain('Detail oriented and passionate about building great software');
    expect(text(autodesk.html.en)).not.toContain('Souci du détail et passion pour le développement de beaux logiciels');
    // English-only trailing sections are in the French view
    expect(text(autodesk.html.fr)).toContain('Salary transparency');
  });

  it('every list item and paragraph of the original is in at least one view, and every fact is in both', () => {
    for (const result of [amazon, autodesk]) {
      const doc = new DOMParser().parseFromString(`<body>${result.html.original}</body>`, 'text/html');
      const union = text(result.html.en) + ' ' + text(result.html.fr);
      const blocks = [...doc.body.querySelectorAll('li, p')].map((n) => (n.textContent || '').replace(/\s+/g, ' ').trim()).filter((t) => t.length > 25 && !/^[-\s]+$/.test(t));
      const missing = blocks.filter((b) => !b.split(/[\n]|(?<=\.)\s/).every((piece) => !piece.trim() || union.includes(piece.trim().slice(0, 40))));
      expect(missing).toEqual([]);
      const facts = new Set(extractFacts(text(result.html.original)).map((f) => f.value));
      for (const view of [result.html.en, result.html.fr]) {
        const have = new Set(extractFacts(text(view)).map((f) => f.value));
        expect([...facts].filter((f) => !have.has(f))).toEqual([]);
      }
    }
  });
});

describe('lexical evidence is real but not sufficient on its own', () => {
  it('translations share vocabulary; unrelated text does not', () => {
    const real = cognateOverlap(FR_1, EN_1);
    expect(Math.min(real.fr, real.en)).toBeGreaterThan(0.3);
    const unrelated = cognateOverlap(FR_ONLY_REQUIREMENT, EN_UNRELATED);
    expect(Math.min(unrelated.fr, unrelated.en)).toBeLessThan(0.15);
  });
});
