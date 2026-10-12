# Career Coach frontend

React + Vite + TypeScript. It has no UI libraries, so the code stays readable. It talks to the local Career Coach API
(`backend/`, default `http://127.0.0.1:8000`). The request and response shapes are in `../docs/API.md`.

```
npm install        # once
npm run dev        # http://127.0.0.1:5173 (start the backend first)
npm test           # unit and component tests; no backend needed
npm run build      # type-check, then build static files into dist/ (what Amplify hosts)
```

To point the app at a different API, set `VITE_API_BASE_URL` (copy `.env.example` to `.env`) or use **Settings**
in the app. The address entered in Settings wins and is saved in the browser.

Where things live:

| Path | What |
|---|---|
| `src/App.tsx` | Which screen shows: Welcome, Setup wizard, Dashboard |
| `src/views/` | The screens: `SetupWizard`, `Dashboard`, `ProfilePanel`, `CoachPanel`, `InsightsPanel`, `Settings` |
| `src/api/` | `client.ts` (every API call), `sse.ts` (reads the streaming chat), `types.ts` (mirrors docs/API.md) |
| `src/lib/layoutGraph.ts` | Positions the skill knowledge graph. A pure function, so it is easy to test |

Needs Node.js 22 or newer for tests. `npm run dev` and `npm run build` work on Node 20.19+.
