import { lookup } from 'node:dns/promises';
import { isIP } from 'node:net';
import { get } from 'node:https';

const cache = new Map();
const CACHE_MS = 86_400_000;

export function isPublicAddress(address) {
  if (isIP(address) === 4) {
    const [a, b] = address.split('.').map(Number);
    return !(a === 0 || a === 10 || a === 127 || a >= 224 || (a === 169 && b === 254)
      || (a === 172 && b >= 16 && b <= 31) || (a === 192 && (b === 0 || b === 168))
      || (a === 100 && b >= 64 && b <= 127) || (a === 198 && (b === 18 || b === 19)));
  }
  // Public IPv6 global-unicast addresses only; mapped IPv4, loopback, link-local and unique-local are excluded.
  return isIP(address) === 6 && /^[23][0-9a-f]{3}:/i.test(address);
}

export function officialUrl(website) {
  const url = new URL(website);
  if (url.protocol !== 'https:' || url.username || url.password || url.port || isIP(url.hostname)
    || !url.hostname.includes('.') || /(?:^|\.)(?:localhost|local|internal|test|invalid)$/.test(url.hostname)) {
    throw new Error('A public HTTPS company website is required');
  }
  url.pathname = '/';
  url.search = '';
  url.hash = '';
  return url;
}

const decode = (value) => value.replace(/&#(x[0-9a-f]+|\d+);/gi, (_, code) => {
  const point = code[0].toLowerCase() === 'x' ? parseInt(code.slice(1), 16) : Number(code);
  return point > 0 && point <= 0x10ffff ? String.fromCodePoint(point) : '';
}).replace(/&(amp|quot|apos|lt|gt|nbsp);/gi, (_, name) => ({ amp: '&', quot: '"', apos: "'", lt: '<', gt: '>', nbsp: ' ' })[name.toLowerCase()]);

export function extractSiteBackground(html) {
  const descriptions = {};
  for (const tag of html.match(/<meta\b[^>]*>/gi) || []) {
    const attrs = {};
    for (const m of tag.matchAll(/([a-z_:][-a-z\d_:]*)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'=<>`]+))/gi)) {
      attrs[m[1].toLowerCase()] = m[2] ?? m[3] ?? m[4];
    }
    const label = (attrs.name || attrs.property || '').toLowerCase();
    if (['description', 'og:description', 'twitter:description'].includes(label) && attrs.content) {
      descriptions[label] = decode(attrs.content).replace(/<[^>]*>/g, '').replace(/\s+/g, ' ').trim();
    }
  }
  const description = descriptions.description || descriptions['og:description'] || descriptions['twitter:description'];
  if (!description || description.length < 20 || description.length > 1200) return null;
  return description;
}

async function readPublicPage(url, originalHost = url.hostname.replace(/^www\./, ''), redirects = 0) {
  if (redirects > 3 || url.protocol !== 'https:' || url.username || url.password || url.port) throw new Error('Invalid redirect');
  const host = url.hostname.replace(/^www\./, '');
  if (host !== originalHost && !host.endsWith(`.${originalHost}`)) throw new Error('Cross-company redirect');
  const addresses = await Promise.race([
    lookup(url.hostname, { all: true }),
    new Promise((_, reject) => { const timer = setTimeout(() => reject(new Error('DNS timeout')), 3000); timer.unref(); }),
  ]);
  if (!addresses.length || addresses.some(({ address }) => !isPublicAddress(address))) throw new Error('Private address');
  const address = addresses.find((entry) => entry.family === 4) || addresses[0];
  // Pin the validated address for the actual connection, rather than resolving DNS again.
  const result = await new Promise((resolve, reject) => {
    const request = get(url, {
      lookup: (_host, options, callback) => options.all ? callback(null, [address]) : callback(null, address.address, address.family),
      headers: { Accept: 'text/html', 'Accept-Encoding': 'identity', 'User-Agent': 'RoleRadar-CompanyProfiles/1.0' },
    }, (response) => {
      if ([301, 302, 303, 307, 308].includes(response.statusCode) && response.headers.location) {
        response.resume(); resolve({ redirect: new URL(response.headers.location, url) }); return;
      }
      if (response.statusCode !== 200 || !response.headers['content-type']?.includes('text/html')) {
        response.resume(); reject(new Error('Company page unavailable')); return;
      }
      const chunks = []; let length = 0;
      response.on('data', (chunk) => {
        length += chunk.length;
        if (length > 524288) { request.destroy(new Error('Company page exceeds limit')); return; }
        chunks.push(chunk);
        const head = Buffer.concat(chunks).toString('utf8');
        const end = head.toLowerCase().indexOf('</head>');
        if (end !== -1) {
          resolve({ html: head.slice(0, end + 7), sourceUrl: url.href });
          response.destroy();
        }
      });
      response.on('end', () => resolve({ html: Buffer.concat(chunks).toString('utf8'), sourceUrl: url.href }));
      response.on('error', reject);
    });
    request.setTimeout(6000, () => request.destroy(new Error('Company page timeout')));
    request.on('error', reject);
  });
  return result.redirect ? readPublicPage(result.redirect, originalHost, redirects + 1) : result;
}

export async function lookupCompanyBackground(company, website, loadPage = readPublicPage) {
  if (typeof company !== 'string' || !company.trim() || company.length > 120 || typeof website !== 'string' || website.length > 2048) return null;
  const url = officialUrl(website);
  const { html, sourceUrl } = await loadPage(url);
  const description = extractSiteBackground(html);
  return description ? { description, sourceUrl } : null;
}

export default async function handler(request, response) {
  response.setHeader('Content-Type', 'application/json; charset=utf-8');
  response.setHeader('X-Content-Type-Options', 'nosniff');
  if (request.method !== 'GET') { response.statusCode = 405; response.end('{}'); return; }
  const params = new URL(request.url, 'https://roleradar.invalid').searchParams;
  const company = params.get('company'), website = params.get('website');
  try {
    const url = officialUrl(website);
    const key = `${company}\n${url.origin}`;
    const saved = cache.get(key);
    const result = saved && saved.expires > Date.now() ? saved.value : await lookupCompanyBackground(company, website);
    if (!result) { response.statusCode = 404; response.setHeader('Cache-Control', 'no-store'); response.end('{}'); return; }
    if (cache.size >= 256) cache.delete(cache.keys().next().value);
    cache.set(key, { value: result, expires: Date.now() + CACHE_MS });
    response.setHeader('Cache-Control', 'public, max-age=600, s-maxage=86400');
    response.end(JSON.stringify(result));
  } catch {
    response.statusCode = 404; response.setHeader('Cache-Control', 'no-store'); response.end('{}');
  }
}
