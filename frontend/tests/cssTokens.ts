import fs from 'node:fs';

/**
 * Reads the stylesheet with the scale tokens (--text-*, --radius-*) replaced by their pixel values, so tests can assert
 * on the effective size/radius without caring whether a rule spells it as a token or a literal.
 */
export function readCss(file: string): string {
  const css = fs.readFileSync(file, 'utf-8');
  const tokens = new Map([...css.matchAll(/(--(?:text|radius)-[\w]+):\s*([\d.]+px)\s*;/g)].map((m) => [m[1], m[2]] as const));
  return css.replace(/var\((--(?:text|radius)-[\w]+)\)/g, (whole, name: string) => tokens.get(name) ?? whole);
}
