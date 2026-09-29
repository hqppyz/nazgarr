// Anteprima autonoma del prototipo del logo (branch feature/ring-logo):
// `npm run dev` e poi /ring-lab.html. Niente login né backend, solo i due anelli.
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import './index.css'
import RingLabPage from '@/pages/lab/RingLabPage'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <RingLabPage />
  </StrictMode>,
)
