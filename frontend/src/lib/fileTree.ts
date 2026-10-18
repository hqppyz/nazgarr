// L'albero di cartelle e file delle viste a cartelle (Libreria › Cartelle,
// Torrent › Cartelle): i dati e le funzioni pure, fuori dal componente
// (src/components/FileTree.tsx) così che il fast refresh di Vite lo ricarichi
// da solo.

import { isVideoPath, type PackFile } from '@/lib/pack'

export interface TreeFileEntry {
  disk_id?: number
  relative_path: string
  state: string
  stopped?: boolean
  excluded: boolean
  linked_paths: string[]
  // Solo Torrent files: orfano, ma lo stesso file è in seed da questi percorsi.
  seeding_copies?: string[]
  size_bytes: number
  // Contenuto del file (scheda di dettaglio al clic), assente se il file
  // non ha un'identità: non risolto, nfo, immagini.
  content_type?: string | null
  tmdb_id?: number | null
}

export interface TreeNode {
  name: string
  path: string
  file: TreeFileEntry | null
  children: Map<string, TreeNode>
  // Aggregati ricorsivi: per una cartella la somma dei file sottostanti,
  // per un file i suoi soli valori.
  sizeBytes: number
  fileCount: number
}

function emptyNode(name: string, path: string): TreeNode {
  return { name, path, file: null, children: new Map(), sizeBytes: 0, fileCount: 0 }
}

export function buildTree(files: TreeFileEntry[]): TreeNode {
  const root = emptyNode('', '')
  for (const file of files) {
    const segments = file.relative_path.split('/')
    let node = root
    node.sizeBytes += file.size_bytes
    node.fileCount += 1
    segments.forEach((segment, i) => {
      const isLast = i === segments.length - 1
      const path = segments.slice(0, i + 1).join('/')
      let child = node.children.get(segment)
      if (!child) {
        child = emptyNode(segment, path)
        node.children.set(segment, child)
      }
      child.sizeBytes += file.size_bytes
      child.fileCount += 1
      if (isLast) child.file = file
      node = child
    })
  }
  return root
}

// Cartelle prima dei file, poi alfabetico.
export function sortedChildren(node: TreeNode): TreeNode[] {
  return [...node.children.values()].sort((a, b) => {
    if (!!a.file !== !!b.file) return a.file ? 1 : -1
    return a.name.localeCompare(b.name)
  })
}

// I file di una cartella dell'albero, a qualunque profondità.
export function filesUnder(node: TreeNode): TreeFileEntry[] {
  const out: TreeFileEntry[] = []
  const walk = (n: TreeNode) => {
    if (n.file) out.push(n.file)
    n.children.forEach(walk)
  }
  walk(node)
  return out
}

// Un video che può entrare in un pack (nazgarr/upload/pack.py): su un disco, non escluso.
export function packable(file: TreeFileEntry): boolean {
  return file.disk_id != null && !file.excluded && isVideoPath(file.relative_path)
}

export const packFile = (file: TreeFileEntry): PackFile => ({ diskId: file.disk_id as number, path: file.relative_path })
