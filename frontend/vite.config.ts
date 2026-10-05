import react from '@vitejs/plugin-react'
import { defineConfig, type Connect, type Plugin } from 'vite'

const rejectMalformedUrlPath: Connect.NextHandleFunction = (req, res, next) => {
  try {
    decodeURIComponent((req.url ?? '').split(/[?#]/, 1)[0]);
  } catch {
    // Reject before Vite's HTML fallback decodes the path and broadcasts a
    // server error overlay to otherwise healthy browser sessions.
    res.statusCode = 400;
    res.setHeader('Content-Type', 'text/html; charset=utf-8');
    res.setHeader('Cache-Control', 'no-store');
    res.end(req.method === 'HEAD' ? undefined : '<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Invalid address — RoleRadar</title></head><body><main><h1>Invalid address</h1><p>This link contains an invalid URL.</p><a href="/jobs">Return to jobs</a></main></body></html>');
    return;
  }
  next();
};

const malformedUrlGuard: Plugin = {
  name: 'reject-malformed-url-path',
  configureServer(server) { server.middlewares.use(rejectMalformedUrlPath); },
  configurePreviewServer(server) { server.middlewares.use(rejectMalformedUrlPath); },
};

// https://vite.dev/config/
export default defineConfig({
  plugins: [malformedUrlGuard, react()],
})
