import { describe, expect, it } from 'vitest';
import { prettyLocationLabel } from '../src/utils/locations';
import { postingHighlights } from '../src/utils/postingHighlights';

describe('adversarial UI regressions', () => {
  it.each([
    ['US, CA, Santa Clara', 'Santa Clara, CA, United States'],
    ['United States of America, Minnesota, Eagan', 'Eagan, Minnesota, United States'],
    ['US, CA', 'CA, United States'],
    ['San Francisco, SF9', 'San Francisco'],
  ])('formats %s with source country evidence', (input, expected) => {
    expect(prettyLocationLabel(input, 'United States')).toBe(expected);
  });
  it('uses the API experience classification consistently with filters', () => {
    expect(postingHighlights('Software Engineer', '', 'senior')[0].value).toBe('Senior');
    expect(postingHighlights('Software Engineer', '', 'unknown')).toEqual([]);
    expect(postingHighlights('Associate Director DevOps', '', 'senior')[0].value).toBe('Senior');
  });
});
