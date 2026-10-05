import { describe, it, expect } from 'vitest';
import { readCss } from './cssTokens';
import path from 'node:path';

const css = readCss(path.resolve(__dirname, '..', 'src', 'index.css'));
const darkVars = css.match(/\[data-theme="dark"\]\s*\{([^}]*)\}/)![1];
const v = (name: string) => darkVars.match(new RegExp(`--${name}:\\s*([^;]+);`))![1].trim();

const lum = (hex: string) => {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255).map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};
const contrast = (a: string, b: string) => {
  const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
};
const isNeutral = (hex: string) => {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
  return Math.max(r, g, b) - Math.min(r, g, b) <= 3;
};

describe('dark mode is neutral near-black', () => {
  it('page #090909, cards #151515, a distinct raised surface, neutral borders', () => {
    expect(v('bg-app')).toBe('#090909');
    expect(v('bg-card')).toBe('#151515');
    for (const name of ['bg-app', 'bg-card', 'bg-raised', 'border-color', 'border-subtle', 'control-border', 'control-border-hover', 'text-muted']) {
      expect(isNeutral(v(name)), name).toBe(true);
    }
    // surfaces step up: page < card < raised, and the border is visible against the card
    expect(lum(v('bg-app'))).toBeLessThan(lum(v('bg-card')));
    expect(lum(v('bg-card'))).toBeLessThan(lum(v('bg-raised')));
    expect(contrast(v('border-color'), v('bg-card'))).toBeGreaterThan(1.15);
  });

  it('keeps blue accents', () => {
    expect(v('primary')).toBe('#3b82f6');
  });

  it('no navy/slate colours remain in any dark-theme rule', () => {
    const navy = ['#0b1120', '#111827', '#172033', '#1e293b', '#263247', '#151e32', '#334155', '#475569', '#94a3b8', '#0f172a', '#030712'];
    const offenders = [...css.matchAll(/([^{}]*\[data-theme="dark"\][^{}]*)\{([^{}]*)\}/g)]
      .filter((m) => navy.some((n) => m[2].toLowerCase().includes(n)))
      .map((m) => m[1].trim().slice(0, 80));
    expect(offenders).toEqual([]);
  });

  it('text and controls stay readable: AA contrast on page, card and raised surfaces', () => {
    for (const surface of ['bg-app', 'bg-card', 'bg-raised']) {
      expect(contrast(v('text-main'), v(surface)), `text on ${surface}`).toBeGreaterThanOrEqual(7);
      expect(contrast(v('text-muted'), v(surface)), `muted on ${surface}`).toBeGreaterThanOrEqual(4.5);
    }
    // blue accent text (links, selected controls) on a card
    expect(contrast('#60a5fa', v('bg-card'))).toBeGreaterThanOrEqual(4.5);
    // selected language option: light blue text on the blue-tinted selection over a card
    const tint = [0, 1, 2].map((i) => Math.round(parseInt(v('bg-card').slice(1 + 2 * i, 3 + 2 * i), 16) * 0.85 + [59, 130, 246][i] * 0.15));
    const tinted = '#' + tint.map((c) => c.toString(16).padStart(2, '0')).join('');
    expect(css).toMatch(/\[data-theme="dark"\] \.job-language-option\[aria-pressed="true"\]\s*\{\s*color:\s*#93c5fd/);
    expect(contrast('#93c5fd', tinted)).toBeGreaterThanOrEqual(4.5);
    // white on the primary button blue
    expect(contrast('#ffffff', '#1d4ed8')).toBeGreaterThanOrEqual(4.5);
  });

  it('keyboard focus is visible: focus-visible rules exist and use a high-contrast colour', () => {
    expect(css).toMatch(/:focus-visible\s*\{[^}]*outline/);
    expect(contrast('#3b82f6', v('bg-card'))).toBeGreaterThanOrEqual(3); // WCAG 1.4.11 non-text contrast
    expect(contrast('#3b82f6', v('bg-app'))).toBeGreaterThanOrEqual(3);
  });
});
