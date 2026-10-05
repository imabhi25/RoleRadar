import userEvent from '@testing-library/user-event';
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { stripDecorativeEmoji, stripEmojiText } from '../src/utils/stripEmoji';
import { parseAndSanitizeJobDescription } from '../src/utils/sanitizeDescription';
import { JobDetailContent } from '../src/components/JobDetailContent';
import { apiClient } from '../src/api/client';
import { vi } from 'vitest';

describe('stripEmojiText', () => {
  it.each([
    ['🌴 20 vacation days, 4 wellness days', '20 vacation days, 4 wellness days'],
    ['✈️ 90 days away...', '90 days away...'],
    ['👥 Employee resource groups...', 'Employee resource groups...'],
    ['🌸 Bloom 📈 Grow 🌎 Global', 'Bloom Grow Global'],
    ['Great perks 🌴 and more', 'Great perks and more'],
    ['Fun 🎉.', 'Fun.'],
    ['Perks🌴', 'Perks'],
    ['👨‍👩‍👧‍👦 Family friendly', 'Family friendly'],
    ['👍🏽 Nice', 'Nice'],
    ['🇨🇦 Canada', 'Canada'],
    ['1️⃣ First step', 'First step'],
    ['🌴🌴🌴', ''],
  ])('%s -> %s', (input, expected) => {
    expect(stripEmojiText(input)).toBe(expected);
  });

  it('keeps ordinary text, ASCII symbols, meaningful symbols and punctuation exactly', () => {
    for (const text of [
      'Plain text: C++ / C# & R (5+ years) - $100k–$120k, 50% remote!',
      '• Bullet one\n- Bullet two\n* Star',
      'Acme® Cloud™ © 2026',
      'Apply on company website ↗ and go → next',
      '✓ Python ✔ SQL',
      '▪ small square bullet ● big bullet',
      'Café résumé naïve — “quotes”',
      '',
    ]) {
      expect(stripEmojiText(text)).toBe(text);
    }
  });
});

describe('stripDecorativeEmoji (HTML)', () => {
  it('cleans text nodes and keeps the markup and words', () => {
    expect(stripDecorativeEmoji('<ul><li>🌴 20 vacation days, 4 wellness days</li><li>✈️ 90 days away...</li><li>👥 Employee resource groups...</li></ul>'))
      .toBe('<ul><li>20 vacation days, 4 wellness days</li><li>90 days away...</li><li>Employee resource groups...</li></ul>');
    expect(stripDecorativeEmoji('<h2>🌴 Benefits</h2><p>Health 🌎 care</p>')).toBe('<h2>Benefits</h2><p>Health care</p>');
  });

  it('removes nodes that only contained an emoji, including wrappers', () => {
    expect(stripDecorativeEmoji('<p>Intro</p><p>🌸</p><p><strong>📈</strong></p><ul><li>🌎</li><li>Real</li></ul>'))
      .toBe('<p>Intro</p><ul><li>Real</li></ul>');
    expect(stripDecorativeEmoji('<p><strong>🌴</strong> 20 vacation days</p>')).toBe('<p> 20 vacation days</p>'.replace('> ', '>'));
  });

  it('never removes images, lists or real content and returns untouched HTML unchanged', () => {
    const html = '<p>No emoji here &amp; C++</p><p><img src="x.png" alt="logo"></p><table><tr><td>Cell</td></tr></table>';
    expect(stripDecorativeEmoji(html)).toBe(html);
  });
});

describe('emoji stripping is part of every description rendering path', () => {
  it('parseAndSanitizeJobDescription output has no decorative emoji (HTML and plain text sources)', () => {
    const html = parseAndSanitizeJobDescription('<h3>🌴 Benefits</h3><ul><li>🌴 20 vacation days</li><li>✈️ 90 days away</li></ul><p>🌸</p>').html;
    expect(html).not.toMatch(/\p{Extended_Pictographic}/u);
    expect(html).toContain('20 vacation days');
    expect(html).toContain('Benefits');
    const plain = parseAndSanitizeJobDescription('About the role\n\n👥 Employee resource groups\n🌎 Global team').html;
    expect(plain).not.toMatch(/\p{Extended_Pictographic}/u);
    expect(plain).toContain('Employee resource groups');
  });

  it('the rendered detail (pane or overlay content) shows the text without the emoji', async () => {
    vi.spyOn(apiClient, 'getJob').mockResolvedValue({
      job_id: 'e1', title: 'Engineer', company: 'Fixture', location: 'Toronto, ON', country: 'Canada', workplace_type: 'remote', source_name: 'ashby',
      skills: [], company_apply_url: 'https://jobs.ashbyhq.com/f/e1/application',
      description: '<h2>Benefits</h2><ul><li>🌴 20 vacation days, 4 wellness days</li><li>✈️ 90 days away...</li><li>👥 Employee resource groups...</li></ul>',
    });
    render(<JobDetailContent jobId="e1" variant="modal" onClose={() => {}} />);
    await userEvent.click(await screen.findByRole('button', { name: 'Full Posting' }));
    expect(await screen.findByText('20 vacation days, 4 wellness days')).toBeInTheDocument();
    expect(screen.getByText('90 days away...')).toBeInTheDocument();
    expect(screen.getByText('Employee resource groups...')).toBeInTheDocument();
    expect(document.querySelector('.job-description-prose')!.textContent).not.toMatch(/\p{Extended_Pictographic}/u);
  });
});
