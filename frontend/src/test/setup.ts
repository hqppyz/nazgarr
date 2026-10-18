import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

// Con `globals: false` (vite.config.ts) Testing Library non registra da sé il
// suo afterEach(cleanup): senza, il DOM di un test resta montato nel
// successivo e una query su `screen` può trovare (o non trovare) l'elemento
// sbagliato a seconda dell'ordine. Qui una volta per tutti i file di test.
afterEach(cleanup)
