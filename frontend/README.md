# Frontend — Nazgarr

React + TypeScript + Vite + Tailwind CSS + shadcn/ui. Vedi `docs/SPEC.md` §10-11 per le decisioni di design e il [README principale](../README.md) per il quadro generale del progetto.

## Sviluppo

```bash
npm install
npm run dev
```

Il dev server (`http://localhost:5173`) fa da proxy per `/api/*` verso `http://localhost:8080` (vedi `vite.config.ts`) — avvia il backend separatamente (`uvicorn nazgarr.main:app --reload --port 8080` dalla root del repo, vedi il README principale).

Dopo ogni modifica agli endpoint del backend, rigenera i tipi TypeScript dallo schema OpenAPI (il backend deve essere in esecuzione):

```bash
npm run gen-types
```

## Logo (anello 3D)

L'anello della sidebar e del login è in WebGL (`src/components/ring/WebGLRing.tsx`, Three.js + GSAP), caricato a parte. Quando manca WebGL o è attivo "riduci movimento", si vede `public/ring.png`, che è lo stesso anello fotografato. Dopo ogni modifica all'anello va rigenerata:

```bash
npm run render:ring   # serve Chrome/Chromium installato (CHROME_PATH per indicarlo)
```

Anteprima: `npm run dev` e poi `/ring-lab.html` (con `?solo` per l'anello grande da solo, `?glow` per vederlo acceso).

## Test

```bash
npm run test   # vitest, component/unit test sulla logica non banale (vedi src/**/*.test.ts[x])
```

## Build

```bash
npm run build   # type-check (tsc) + build di produzione in dist/
```

In produzione `dist/` viene servito direttamente da FastAPI (`nazgarr/web/frontend.py`) — un solo container, nessun server Node separato (vedi il Dockerfile, stage `frontend-build`).

## Struttura

- `src/api/` — client tipizzato (`openapi-fetch`) sullo schema generato da `openapi-typescript` (`schema.ts`, non modificare a mano — rigenerato da `npm run gen-types`)
- `src/components/ui/` — componenti shadcn/ui (copiati nel repo dal CLI, non una dipendenza runtime)
- `src/components/layout/` — shell dell'app (sidebar, layout)
- `src/pages/` — una pagina per voce di navigazione (`src/lib/nav.ts`, struttura da `docs/SPEC.md` §10)

## Attenzione: `Select.Value` di Base UI

I componenti shadcn/ui qui sono costruiti su **Base UI**, non Radix — a differenza di Radix, `Select.Value` mostra il `value` grezzo selezionato invece dell'etichetta della `SelectItem` corrispondente, e passargli `children` disattiva anche il fallback automatico al `placeholder`. Va sempre gestito esplicitamente con l'helper condiviso `selectLabel()` (`src/lib/utils.ts`, testato in `utils.test.ts`) invece di ripetere la logica in ogni `Select`.
