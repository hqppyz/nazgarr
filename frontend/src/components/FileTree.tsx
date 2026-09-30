import { ChevronRightIcon, FileIcon, FileVideoIcon, FolderIcon, FolderOpenIcon } from "lucide-react";
import { useMemo, useState } from "react";

import { HardlinkInfo } from "@/components/HardlinkInfo";
import { RowContextMenu, type RowMenuItem } from "@/components/RowContextMenu";
import { StateBadge, StatusBadge, StoppedBadge } from "@/components/StateBadge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { t } from "@/lib/i18n";
import { fileKey, formatBytes } from "@/lib/library-filters";
import { cn } from "@/lib/utils";

export interface TreeFileEntry {
  disk_id?: number;
  relative_path: string;
  state: string;
  stopped?: boolean;
  excluded: boolean;
  linked_paths: string[];
  size_bytes: number;
  // Contenuto del file (scheda di dettaglio al clic), assente se il file
  // non ha un'identità: non risolto, nfo, immagini.
  content_type?: string | null;
  tmdb_id?: number | null;
}

export interface TreeNode {
  name: string;
  path: string;
  file: TreeFileEntry | null;
  children: Map<string, TreeNode>;
  // Aggregati ricorsivi: per una cartella la somma dei file sottostanti,
  // per un file i suoi soli valori.
  sizeBytes: number;
  fileCount: number;
}

function emptyNode(name: string, path: string): TreeNode {
  return { name, path, file: null, children: new Map(), sizeBytes: 0, fileCount: 0 };
}

export function buildTree(files: TreeFileEntry[]): TreeNode {
  const root = emptyNode("", "");
  for (const file of files) {
    const segments = file.relative_path.split("/");
    let node = root;
    node.sizeBytes += file.size_bytes;
    node.fileCount += 1;
    segments.forEach((segment, i) => {
      const isLast = i === segments.length - 1;
      const path = segments.slice(0, i + 1).join("/");
      let child = node.children.get(segment);
      if (!child) {
        child = emptyNode(segment, path);
        node.children.set(segment, child);
      }
      child.sizeBytes += file.size_bytes;
      child.fileCount += 1;
      if (isLast) child.file = file;
      node = child;
    });
  }
  return root;
}

// Stesse estensioni di app/file_types.py: solo l'icona, lo stato arriva dal backend.
const VIDEO_EXTENSIONS = [".mkv", ".mp4", ".avi", ".m2ts", ".ts", ".wmv", ".mov"];

function isVideo(path: string): boolean {
  const lower = path.toLowerCase();
  return VIDEO_EXTENSIONS.some((ext) => lower.endsWith(ext));
}

// Cartelle prima dei file, poi alfabetico.
function sortedChildren(node: TreeNode): TreeNode[] {
  return [...node.children.values()].sort((a, b) => {
    if (!!a.file !== !!b.file) return a.file ? 1 : -1;
    return a.name.localeCompare(b.name);
  });
}

interface FlatRow {
  node: TreeNode;
  depth: number;
  open: boolean;
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

// Voci facoltative del menu contestuale di una riga (tasto destro), es.
// "Upload / reseed" sui torrent orfani: nessuna voce, nessun menu.
export interface TreeRowActions {
  file?: (file: TreeFileEntry) => RowMenuItem[]
  folder?: (node: TreeNode) => RowMenuItem[]
}

export function FileTree({ files, expandAll = false, duplicateKeys, onOpenFile, actions }: { files: TreeFileEntry[]; expandAll?: boolean; duplicateKeys?: Set<string>; onOpenFile?: (file: TreeFileEntry) => void; actions?: TreeRowActions }) {
  // Cartelle il cui stato aperto/chiuso differisce dal default (aperte al
  // primo livello, chiuse sotto) — così il default resta quello anche
  // quando i dati cambiano, senza dover pre-popolare un Set di path.
  const [toggled, setToggled] = useState<Set<string>>(() => new Set());
  const tree = useMemo(() => buildTree(files), [files]);

  const rows = useMemo(() => {
    const out: FlatRow[] = [];
    const walk = (node: TreeNode, depth: number) => {
      for (const child of sortedChildren(node)) {
        const open = !child.file && (expandAll || depth < 1 !== toggled.has(child.path));
        out.push({ node: child, depth, open });
        if (open) walk(child, depth + 1);
      }
    };
    walk(tree, 0);
    return out;
  }, [tree, toggled, expandAll]);

  const toggle = (path: string) =>
    setToggled((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });

  if (files.length === 0) {
    return <p className="p-4 text-sm text-muted-foreground">{t("library.noFilesMatchFilters")}</p>;
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>{t("library.columnName")}</TableHead>
          <TableHead className="w-56">{t("library.columnState")}</TableHead>
          <TableHead className="w-28 text-right">{t("library.columnSize")}</TableHead>
        </TableRow>
      </TableHeader>
      {/* Mono per tutto il corpo: nomi di cartelle e file allineati, come in un terminale. */}
      <TableBody className="font-mono">
        {rows.map(({ node, depth, open }) => {
          const indent = { paddingLeft: `${depth * 1.25 + 0.5}rem` };
          if (!node.file) {
            return (
              <RowContextMenu key={node.path} title={node.path} items={actions?.folder?.(node) ?? []}>
              <TableRow
                // Cartelle aperte con uno sfondo tendente al primary: a colpo
                // d'occhio si vede cosa è esploso e cosa no.
                className={cn("cursor-pointer", open && "bg-primary/5 hover:bg-primary/10", "text-xs")}
                aria-expanded={open}
                onClick={() => toggle(node.path)}
              >
                <TableCell className="max-w-0" style={indent}>
                  <div className="flex items-center gap-1.5">
                    <ChevronRightIcon className={cn("size-3.5 shrink-0 transition-transform", open && "rotate-90")} />
                    {open ? <FolderOpenIcon className="size-3.5 shrink-0 text-primary" /> : <FolderIcon className="size-3.5 shrink-0 text-primary" />}
                    <span className="truncate font-medium">{node.name}</span>
                    <span className="ml-1.5 flex shrink-0 items-center gap-2 text-muted-foreground">
                      <span aria-hidden>·</span>
                      {t("library.filesCount", { count: node.fileCount })}
                    </span>
                  </div>
                </TableCell>
                <TableCell />
                <TableCell className="text-right text-xs text-muted-foreground tabular-nums">{formatBytes(node.sizeBytes)}</TableCell>
              </TableRow>
              </RowContextMenu>
            );
          }
          const file = node.file;
          const openable = onOpenFile != null && file.tmdb_id != null && file.content_type != null;
          return (
            <RowContextMenu key={node.path} title={file.relative_path} items={actions?.file?.(file) ?? []}>
            <TableRow className={cn(file.excluded && "opacity-60", openable && "cursor-pointer")} onClick={openable ? () => onOpenFile(file) : undefined}>
              <TableCell className="max-w-0" style={indent}>
                <div className="flex items-center gap-1.5 pl-5">
                  {isVideo(node.name) ? <FileVideoIcon className="size-3.5 shrink-0 text-muted-foreground" /> : <FileIcon className="size-3.5 shrink-0 text-muted-foreground" />}
                  <span className="truncate text-xs" title={file.relative_path}>
                    {node.name}
                  </span>
                  <HardlinkInfo linkedPaths={file.linked_paths} />
                </div>
              </TableCell>
              <TableCell>
                <div className="flex items-center gap-1.5">
                  {file.excluded ? (
                    // Escluso = fuori da ogni controllo: nessuno stato, nessun "duplicate".
                    <StatusBadge status="excluded" compact>
                      {t("library.excluded")}
                    </StatusBadge>
                  ) : (
                    <>
                      <StateBadge state={file.state} compact />
                      {file.stopped && <StoppedBadge compact />}
                      {file.state === "orphan_torrent" && file.linked_paths.length === 0 && (
                        // Né in seed né in libreria: nessuna identità, quindi mai cercato
                        // sui tracker; di solito spazio che si può recuperare.
                        <StatusBadge status="unmatched" compact>
                          {t("library.notInLibrary")}
                        </StatusBadge>
                      )}
                      {duplicateKeys?.has(fileKey(file)) && (
                        <StatusBadge status="duplicate" compact>
                          {t("library.duplicate")}
                        </StatusBadge>
                      )}
                    </>
                  )}
                </div>
              </TableCell>
              <TableCell className="text-right text-xs tabular-nums">{formatBytes(file.size_bytes)}</TableCell>
            </TableRow>
            </RowContextMenu>
          );
        })}
      </TableBody>
    </Table>
  );
}
