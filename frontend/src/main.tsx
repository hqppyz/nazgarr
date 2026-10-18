import { MutationCache, QueryClient } from '@tanstack/react-query'
import { polyfillCountryFlagEmojis } from 'country-flag-emoji-polyfill'
import flagsFont from 'country-flag-emoji-polyfill/dist/TwemojiCountryFlags.woff2?url'
import { PersistQueryClientProvider } from '@tanstack/react-query-persist-client'
import { ThemeProvider } from 'next-themes'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'

import App from './App.tsx'
import { shouldRetryQuery } from '@/api/client'
import { AuthGate } from '@/components/auth/AuthGate'
import { CrashPanel } from '@/components/CrashPanel'
import { ErrorBoundary } from '@/components/ErrorBoundary'
import { Toaster } from '@/components/ui/sonner'
import { TooltipProvider } from '@/components/ui/tooltip'
import { installChunkReload } from '@/lib/chunkReload'
import { CACHE_BUSTER, CACHE_MAX_AGE_MS, queryPersister, shouldPersistQuery } from '@/lib/queryPersistence'
import './index.css'

// Windows non ha le bandiere fra le emoji (le lingue nell'anteprima MediaInfo):
// un font con le sole bandiere, servito da qui perché la CSP non carica font
// da altri siti. Non fa niente dove le bandiere ci sono già.
polyfillCountryFlagEmojis('Twemoji Country Flags', flagsFont)

// Un chunk della build di prima che non c'è più (container aggiornato con la
// pagina aperta): si ricarica una volta, invece della pagina bianca.
installChunkReload()

// Dopo ogni salvataggio, la checklist del tour (src/onboarding) si riallinea:
// un passo si chiude appena la configurazione c'è, ovunque sia stata fatta.
const queryClient: QueryClient = new QueryClient({
  defaultOptions: { queries: { retry: shouldRetryQuery } },
  mutationCache: new MutationCache({
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['setup-status'] }),
  }),
})
// gcTime almeno quanto la cache persistita, ma solo per le query persistite
// (le viste della libreria, src/lib/queryPersistence.ts): una query
// ripristinata da IndexedDB non deve essere scartata dopo i 5 minuti di
// default. Le altre (ricerche, anteprime dei nomi) restano ai 5 minuti,
// invece di restare in memoria per tutta la sessione.
queryClient.setQueryDefaults(['library'], { gcTime: CACHE_MAX_AGE_MS })

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ThemeProvider attribute="class" defaultTheme="system" enableSystem disableTransitionOnChange>
      <PersistQueryClientProvider
        client={queryClient}
        persistOptions={{
          persister: queryPersister,
          maxAge: CACHE_MAX_AGE_MS,
          buster: CACHE_BUSTER,
          dehydrateOptions: { shouldDehydrateQuery: shouldPersistQuery },
        }}
      >
        <TooltipProvider>
          {/* L'ultima rete: un errore che nessuna vista ha fermato (il layout,
              il login) mostra il messaggio e "Ricarica" invece della pagina bianca. */}
          <ErrorBoundary fallback={({ error, reset }) => <CrashPanel error={error} onRetry={reset} fullPage />}>
            <AuthGate>
              <BrowserRouter>
                <App />
              </BrowserRouter>
            </AuthGate>
          </ErrorBoundary>
          <Toaster />
        </TooltipProvider>
      </PersistQueryClientProvider>
    </ThemeProvider>
  </StrictMode>,
)
