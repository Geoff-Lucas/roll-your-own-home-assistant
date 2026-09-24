# Home Organizer — frontend

The kiosk's page: a Svelte 5 app built with Vite. In production it's built on
the dev machine (never on the kiosk) and served by the backend itself, from
`frontend/dist/` (see `../deploy/README.md`).

Node comes from the `home_organizer` conda environment on the dev machine.

```bash
npm install
npm run dev     # http://localhost:5173, proxying /api to a backend on 127.0.0.1:8000
npm test        # Vitest: the timers, voice and idle stores (src/lib/**/*.test.js)
npm run build   # into dist/, which deploy/deploy.sh also does
```

The stores are where the page's logic lives (live countdowns, when to open and
close the voice panel, when the photo carousel starts), so they're what the
tests cover; the tests mock `src/lib/api.js` and use fake timers.
