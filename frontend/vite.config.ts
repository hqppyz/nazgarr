import path from 'node:path'

import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
// `vitest/config` ri-esporta defineConfig di Vite con la chiave `test`
// tipizzata — un solo file di config invece di uno separato per i test.
import { defineConfig } from 'vitest/config'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(import.meta.dirname, './src'),
    },
  },
  server: {
    // Backend avviato separatamente con `uvicorn nazgarr.main:app --reload --port 3019`
    // (vedi README) - nessun bisogno di CORS lato backend, nemmeno in dev.
    proxy: {
      '/api': 'http://localhost:3019',
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    globals: false,
  },
})
