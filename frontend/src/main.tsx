import { MutationCache, QueryClient } from '@tanstack/react-query'
import { PersistQueryClientProvider } from '@tanstack/react-query-persist-client'
import { ThemeProvider } from 'next-themes'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'

import App from './App.tsx'
import { AuthGate } from '@/components/auth/AuthGate'
import { Toaster } from '@/components/ui/sonner'
import { TooltipProvider } from '@/components/ui/tooltip'
import { CACHE_BUSTER, CACHE_MAX_AGE_MS, queryPersister, shouldPersistQuery } from '@/lib/queryPersistence'
import './index.css'

// gcTime almeno quanto la cache persistita: una query ripristinata da
// IndexedDB non deve essere scartata dopo i 5 minuti di default.
// Dopo ogni salvataggio, la checklist del tour (src/onboarding) si riallinea:
// un passo si chiude appena la configurazione c'è, ovunque sia stata fatta.
const queryClient: QueryClient = new QueryClient({
  defaultOptions: { queries: { gcTime: CACHE_MAX_AGE_MS } },
  mutationCache: new MutationCache({
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['setup-status'] }),
  }),
})

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
          <AuthGate>
            <BrowserRouter>
              <App />
            </BrowserRouter>
          </AuthGate>
          <Toaster />
        </TooltipProvider>
      </PersistQueryClientProvider>
    </ThemeProvider>
  </StrictMode>,
)
