// Genera public/ring.png, l'immagine statica dell'anello del logo: lo stesso
// anello WebGL (src/components/ring/WebGLRing.tsx) fotografato una volta, con
// lo sfondo trasparente. È il ripiego per "riduci movimento" e per i browser
// senza WebGL, e il segnaposto mentre si carica Three.js.
//
// Uso: npm run render:ring  (da rilanciare quando cambia l'anello)
// Serve Google Chrome o Chromium installato; CHROME_PATH per indicarne il
// percorso se non è in uno di quelli soliti.

import { spawn } from 'node:child_process'
import { existsSync } from 'node:fs'
import { mkdtemp, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import path from 'node:path'

import { createServer } from 'vite'

const root = path.resolve(import.meta.dirname, '..')
const output = path.join(root, 'public', 'ring.png')

function findChrome() {
  const candidates = [
    process.env.CHROME_PATH,
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    '/Applications/Chromium.app/Contents/MacOS/Chromium',
    '/usr/bin/google-chrome',
    '/usr/bin/chromium',
    '/usr/bin/chromium-browser',
    'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  ].filter(Boolean)
  const found = candidates.find((candidate) => existsSync(candidate))
  if (!found) throw new Error('Chrome/Chromium not found: set CHROME_PATH')
  return found
}

const server = await createServer({ root, server: { port: 0, strictPort: false }, logLevel: 'error' })
await server.listen()
const profile = await mkdtemp(path.join(tmpdir(), 'nazgarr-ring-'))
try {
  const url = `${server.resolvedUrls.local[0]}ring-lab.html?export`
  const args = [
    '--headless=new',
    '--use-angle=swiftshader',
    '--enable-unsafe-swiftshader',
    '--hide-scrollbars',
    '--no-first-run',
    '--no-default-browser-check',
    '--disable-background-networking',
    '--disable-component-update',
    '--window-size=400,400',
    `--user-data-dir=${profile}`,
    // tempo virtuale: la pagina ha il tempo di caricare Three.js e disegnare
    // il fotogramma prima che il DOM venga letto
    '--virtual-time-budget=4000',
    '--dump-dom',
    url,
  ]
  // Chrome può restare aperto a lungo dopo aver stampato il DOM: si legge
  // l'output man mano e lo si chiude appena l'immagine è arrivata.
  const pattern = /id="ring-export"[^>]*src="data:image\/png;base64,([^"]+)"|src="data:image\/png;base64,([^"]+)"[^>]*id="ring-export"/
  const chrome = spawn(findChrome(), args, { stdio: ['ignore', 'pipe', 'ignore'] })
  const exited = new Promise((resolve) => chrome.on('exit', resolve))
  const match = await new Promise((resolve, reject) => {
    let stdout = ''
    const timer = setTimeout(() => {
      chrome.kill()
      reject(new Error('Timed out waiting for the ring to render'))
    }, 120_000)
    chrome.stdout.on('data', (chunk) => {
      stdout += chunk
      const found = stdout.match(pattern)
      if (found && stdout.includes('</html>')) {
        clearTimeout(timer)
        chrome.kill()
        resolve(found)
      }
    })
    chrome.on('exit', () => {
      clearTimeout(timer)
      resolve(stdout.match(pattern))
    })
    chrome.on('error', reject)
  })
  if (!match) throw new Error('The ring was not rendered (no #ring-export in the page)')
  await writeFile(output, Buffer.from(match[1] ?? match[2], 'base64'))
  console.log(`Wrote ${path.relative(root, output)}`)
  await exited
} finally {
  await server.close()
  // il profilo temporaneo di Chrome: se qualcosa lo tiene ancora, pazienza
  await rm(profile, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 }).catch(() => {})
}
