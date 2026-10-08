# RoleRadar frontend

The React and TypeScript client for RoleRadar: searchable job listings, a desktop split view, mobile job details, company profiles and a market dashboard.

**[Live demo](https://jobber-mauve.vercel.app/jobs)** · **[Project overview and backend setup](../README.md)**

## Development

Requires Node.js 22. Start the FastAPI backend using the root setup guide, then run from this directory:

```bash
npm ci
npm run dev
```

Vite normally serves the app at `http://localhost:5173`. API requests default to `http://127.0.0.1:8000` in development. To use another API, create `.env.local`:

```dotenv
VITE_API_BASE_URL=http://127.0.0.1:8000
```

Restart Vite after changing environment variables. Production defaults to same-origin API requests; configure an HTTPS `VITE_API_BASE_URL` for a cross-origin API and allow the frontend origin in the backend's `FRONTEND_ORIGIN`.

## Checks and build

```bash
npm test          # Vitest and React Testing Library
npm run lint      # ESLint
npm run build     # TypeScript check and Vite production build
npm run preview   # Preview the built application
```

The production output is `dist/`. Vercel routing and the production API proxy are configured in [`vercel.json`](vercel.json).

## Where to look

- [`src/components/`](src/components/): job search, detail views, filters and dashboard components.
- [`src/api/client.ts`](src/api/client.ts): typed API contracts and request helpers.
- [`src/utils/`](src/utils/): URL state, location and date presentation, description sanitization and source-based summaries.
- [`tests/`](tests/): interaction, accessibility, formatting and regression coverage.

The shared description pipeline serves both desktop and mobile. Summary preserves useful source blocks and prioritizes applicant conditions; Full Posting retains the complete sanitized description. Superseded search requests are cancelled, and state is reflected in the URL for shareable views.
