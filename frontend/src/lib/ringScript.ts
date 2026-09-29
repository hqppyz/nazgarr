// Scrittura calligrafica inventata, in stile tengwar, per l'iscrizione
// dell'anello del logo. Consonanti come fusti e anse, vocali come segni sopra
// la consonante che SEGUE (su un "portatore" se non ne segue una), doppie con
// un segno sotto. Tracciati disegnati qui: nessun font esterno, nessuna
// trascrizione di testi esistenti. Puramente decorativa.
//
// Coordinate di un glifo (y verso il basso): corpo fra 0.42 e 1.0, fusti che
// scendono fino a ~1.46, segni delle vocali fra ~0.08 e ~0.32.

export interface ScriptGlyph {
  d: string
  width: number
}

type Vowel = 'a' | 'e' | 'i' | 'o' | 'u'

// Fusto che scende e si arriccia in fondo, con un piccolo attacco in alto.
const STEM = (x: number) =>
  `M${x - 0.08} 0.46 C${x - 0.02} 0.38 ${x} 0.4 ${x} 0.5 C${x + 0.02} 0.9 ${x - 0.02} 1.3 ${x + 0.02} 1.44 C${x + 0.06} 1.56 ${x + 0.22} 1.52 ${x + 0.26} 1.42`

// Consonanti di base (larghezza, tracciato). Le lettere che non servono alla
// frase non ci sono: si aggiungono qui.
const CONSONANTS: Record<string, ScriptGlyph> = {
  // fusto e un'ansa aperta a destra
  t: { width: 0.7, d: `${STEM(0.1)} M0.1 0.52 C0.6 0.24 0.72 0.9 0.24 1.02` },
  // fusto e un'ansa chiusa a destra
  p: { width: 0.74, d: `${STEM(0.1)} M0.1 0.52 C0.72 0.24 0.78 1.1 0.1 0.98` },
  // fusto e un'ansa aperta a sinistra
  c: { width: 0.7, d: `${STEM(0.6)} M0.6 0.52 C0.1 0.24 -0.02 0.9 0.46 1.02` },
  // fusto e due anse aperte a sinistra
  g: {
    width: 0.94,
    d: `${STEM(0.86)} M0.86 0.52 C0.46 0.28 0.38 0.9 0.74 1.02 M0.58 0.56 C0.16 0.3 0.02 0.94 0.44 1.02`,
  },
  // due gobbe aperte in basso
  n: { width: 0.9, d: 'M0.02 1.02 C0.04 0.96 0.08 0.98 0.08 0.9 C0.04 0.42 0.44 0.32 0.42 0.98 M0.42 0.62 C0.48 0.32 0.9 0.38 0.84 0.98 C0.84 1.06 0.9 1.06 0.94 1' },
  // a "y" con la coda che scende e si piega
  r: { width: 0.68, d: 'M0.02 0.5 C0.06 0.4 0.12 0.44 0.12 0.52 C0.14 0.88 0.4 0.96 0.5 0.58 M0.52 0.42 C0.56 0.96 0.42 1.34 0.14 1.4 C0 1.42 0 1.3 0.1 1.28' },
  // uncino alto che si avvolge
  l: { width: 0.62, d: 'M0.06 1 C0 0.6 0.1 0.1 0.34 -0.02 C0.5 -0.08 0.58 0.1 0.44 0.22 C0.3 0.34 0.12 0.32 0.16 0.2' },
  // ricciolo a esse
  s: { width: 0.66, d: 'M0.6 0.46 C0.5 0.36 0.02 0.34 0.22 0.64 C0.4 0.82 0.62 0.86 0.4 1.02 C0.24 1.1 0.02 1 0.06 0.92' },
  // ricciolo a esse con un tratto in basso
  z: { width: 0.68, d: 'M0.62 0.46 C0.52 0.36 0.04 0.34 0.24 0.64 C0.42 0.82 0.64 0.86 0.42 1.02 C0.3 1.1 0.14 1.08 0.1 1.2 C0.08 1.32 0.24 1.34 0.3 1.26' },
  // coppa aperta in alto con un ricciolo
  v: { width: 0.72, d: 'M0.02 0.5 C0.06 0.4 0.12 0.44 0.1 0.54 C0.06 1.08 0.66 1.08 0.66 0.56 C0.66 0.38 0.46 0.38 0.44 0.52' },
}
CONSONANTS.k = CONSONANTS.c

// Portatore breve per una vocale senza consonante che la segua.
const CARRIER: ScriptGlyph = { width: 0.32, d: 'M0.1 0.56 C0.12 0.8 0.08 0.92 0.1 1 M0.1 0.56 C0.16 0.46 0.24 0.46 0.28 0.52' }

const DOT = (x: number, y: number) => `M${x} ${y} l0.001 0`

function tehta(vowel: Vowel, c: number): string {
  switch (vowel) {
    case 'a':
      return `${DOT(c - 0.14, 0.27)} ${DOT(c, 0.16)} ${DOT(c + 0.14, 0.27)}`
    case 'e':
      return `M${c - 0.08} 0.32 L${c + 0.1} 0.12`
    case 'i':
      return DOT(c, 0.22)
    case 'o':
      return `M${c - 0.08} 0.32 C${c - 0.12} 0.1 ${c + 0.14} 0.08 ${c + 0.1} 0.27`
    case 'u':
      return `M${c + 0.08} 0.32 C${c + 0.12} 0.1 ${c - 0.14} 0.08 ${c - 0.1} 0.27`
  }
}

// Segno delle doppie, sotto la lettera.
const DOUBLE = (c: number) => `M${c - 0.18} 1.14 C${c - 0.06} 1.06 ${c + 0.06} 1.22 ${c + 0.18} 1.14`

export const SPACE_WIDTH = 0.5
export const GLYPH_GAP = 0.14

export interface Placed {
  d: string
  x: number // posizione del glifo lungo la riga, in unità
  width: number
}

const VOWELS = new Set('aeiou')

// Una riga di testo -> glifi posizionati. Vocale sulla consonante che segue,
// su un portatore se segue un'altra vocale, uno spazio o la fine.
export function transliterate(text: string): { glyphs: Placed[]; width: number } {
  const glyphs: Placed[] = []
  let x = 0
  const push = (glyph: ScriptGlyph, extra = '') => {
    glyphs.push({ d: `${glyph.d} ${extra}`.trim(), x, width: glyph.width })
    x += glyph.width + GLYPH_GAP
  }
  for (const word of text.toLowerCase().split(/\s+/).filter(Boolean)) {
    let pending: Vowel | null = null
    const letters = [...word.normalize('NFD').replace(/[\u0300-\u036f]/g, '')]
    for (let i = 0; i < letters.length; i++) {
      const ch = letters[i]
      if (VOWELS.has(ch)) {
        if (pending) push(CARRIER, tehta(pending, CARRIER.width / 2))
        pending = ch as Vowel
        continue
      }
      const glyph = CONSONANTS[ch]
      if (!glyph) {
        if (ch === ',' || ch === '.') push({ width: 0.2, d: DOT(0.1, 0.72) })
        continue
      }
      const double = letters[i + 1] === ch
      if (double) i++
      const c = glyph.width / 2
      push(glyph, [pending ? tehta(pending, c) : '', double ? DOUBLE(c) : ''].join(' '))
      pending = null
    }
    if (pending) push(CARRIER, tehta(pending, CARRIER.width / 2))
    x += SPACE_WIDTH
  }
  return { glyphs, width: x }
}

export const RING_INSCRIPTION = 'un Nazgarr per trovarli, un Nazgarr per riunirli e sul tracker caricarli'
