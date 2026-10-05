import { ChevronRightIcon, FileIcon, FileVideoIcon, FolderIcon, FolderOpenIcon } from "lucide-react";
import { useMemo, useState } from "react";

import { useIncrementalCount } from "@/hooks/use-incremental";

import { HardlinkInfo } from "@/components/HardlinkInfo";
import { InfoPopover } from "@/components/InfoPopover";
import { RowContextMenu, RowMenuButton, type RowMenuItem } from "@/components/RowContextMenu";
import { StateBadge, StatusBadge, StoppedBadge } from "@/components/StateBadge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { t } from "@/lib/i18n";
import { fileKey, formatBytes } from "@/lib/library-filters";
import { isVideoPath, type PackSelection } from "@/lib/pack";
import { cn } from "@/lib/utils";

export interface TreeFileEntry {
  disk_id?: number;
  relative_path: string;
  state: string;
  stopped?: boolean;
  excluded: boolean;
  linked_paths: string[];
  // Solo Torrent files: orfano, ma lo stesso file è in seed da questi percorsi.
  seeding_copies?: string[];
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

// Stesse estensioni di nazgarr/core/file_types.py: solo l'icona, lo stato arriva dal backend.
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

// Un video che può entrare in un pack (nazgarr/upload/pack.py): su un disco, non escluso.
export function packable(file: TreeFileEntry): boolean {
  return file.disk_id != null && !file.excluded && isVideoPath(file.relative_path);
}

export const packFile = (file: TreeFileEntry) => ({ diskId: file.disk_id as number, path: file.relative_path });

// onPick riceve SHIFT (dal clic, non dal change: lì non c'è). Più grande su
// touch: a 14 px una casella è difficile da centrare col dito.
function PackCheckbox({ checked, indeterminate = false, label, onPick }: { checked: boolean; indeterminate?: boolean; label: string; onPick: (shift: boolean) => void }) {
  return (
    <input
      type="checkbox"
      aria-label={label}
      className="size-3.5 shrink-0 accent-primary pointer-coarse:size-5"
      checked={checked}
      ref={(el) => {
        if (el) el.indeterminate = indeterminate;
      }}
      onClick={(e) => {
        e.stopPropagation();
        onPick(e.shiftKey);
      }}
      onChange={() => {}}
    />
  );
}

// Lo spazio di una casella assente, per allineare le righe.
const CHECKBOX_SPACER = <span className="size-3.5 shrink-0 pointer-coarse:size-5" />;

function FileBadges({ file, duplicateKeys }: { file: TreeFileEntry; duplicateKeys?: Set<string> }) {
  if (file.excluded) {
    // Escluso = fuori da ogni controllo: nessuno stato, nessun "duplicate".
    return (
      <StatusBadge status="excluded" compact>
        {t("library.excluded")}
      </StatusBadge>
    );
  }
  return (
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
      {(file.seeding_copies?.length ?? 0) > 0 && (
        // Da dove è in seed: al passaggio del mouse o al tocco, non solo in un title.
        <InfoPopover
          content={
            <div className="grid gap-1">
              <p>{t("library.seedingCopyTitle")}</p>
              {file.seeding_copies?.map((path) => (
                <p key={path} className="font-mono break-all">{path}</p>
              ))}
            </div>
          }
        >
          <StatusBadge status="seeding" compact>
            {t("library.seedingCopy")}
          </StatusBadge>
        </InfoPopover>
      )}
      {duplicateKeys?.has(fileKey(file)) && (
        <StatusBadge status="duplicate" compact>
          {t("library.duplicate")}
        </StatusBadge>
      )}
    </>
  );
}

const ROWS_PAGE = 300;

export function FileTree({ files, expandAll = false, duplicateKeys, onOpenFile, actions, selection }: { files: TreeFileEntry[]; expandAll?: boolean; duplicateKeys?: Set<string>; onOpenFile?: (file: TreeFileEntry) => void; actions?: TreeRowActions; selection?: PackSelection }) {
  const picking = selection?.active ?? false;
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

  // Solo un blocco di righe alla volta, altre scorrendo: con una ricerca
  // tutto l'albero si apre, e le righe potevano essere decine di migliaia.
  // Si riparte dal primo blocco quando cambiano i file (filtri, ricerca), non
  // quando si apre o chiude una cartella.
  const { visible, hasMore, sentinelRef } = useIncrementalCount<HTMLTableRowElement>(rows.length, ROWS_PAGE, files);

  // I video sceglibili nell'ordine mostrato, per SHIFT+clic.
  const orderedPackable = useMemo(
    () => rows.filter(({ node }) => node.file && packable(node.file)).map(({ node }) => packFile(node.file as TreeFileEntry)),
    [rows],
  );

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

  // Il pulsante ⋯ ha una colonna sua solo se c'è un menu (le viste con useTreeMenu).
  const withMenu = actions?.file != null || actions?.folder != null;

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>{t("library.columnName")}</TableHead>
          {/* Sotto sm stato e dimensione vanno sotto il nome: con le loro
              colonne al nome non restava spazio. */}
          <TableHead className="hidden w-56 sm:table-cell">{t("library.columnState")}</TableHead>
          <TableHead className="hidden w-28 text-right sm:table-cell">{t("library.columnSize")}</TableHead>
          {withMenu && <TableHead className="w-8 px-1" />}
        </TableRow>
      </TableHeader>
      {/* Mono per tutto il corpo: nomi di cartelle e file allineati, come in un terminale. */}
      <TableBody className="font-mono">
        {rows.slice(0, visible).map(({ node, depth, open }) => {
          // Rientro più stretto sul telefono: a 1.25rem per livello tre
          // cartelle si mangiavano metà riga.
          const indent = {
            "--indent": `${depth * 0.75 + 0.5}rem`,
            "--indent-sm": `${depth * 1.25 + 0.5}rem`,
          } as React.CSSProperties;
          const indentClass = "max-w-0 pl-(--indent) sm:pl-(--indent-sm)";
          if (!node.file) {
            const items = actions?.folder?.(node) ?? [];
            return (
              <RowContextMenu key={node.path} title={node.path} items={items}>
              <TableRow
                // Cartelle aperte con uno sfondo tendente al primary: a colpo
                // d'occhio si vede cosa è esploso e cosa no.
                className={cn("cursor-pointer", open && "bg-primary/5 hover:bg-primary/10", "text-xs")}
                aria-expanded={open}
                onClick={() => toggle(node.path)}
              >
                <TableCell className={indentClass} style={indent}>
                  <div className="flex items-center gap-1.5">
                    {picking && selection && (() => {
                      const videos = filesUnder(node).filter(packable);
                      if (videos.length === 0) return CHECKBOX_SPACER;
                      const picked = videos.filter((f) => selection.has(packFile(f))).length;
                      return (
                        <PackCheckbox
                          label={t("pack.selectFolder")}
                          checked={picked === videos.length}
                          indeterminate={picked > 0 && picked < videos.length}
                          onPick={() => selection.setMany(videos.map(packFile), picked < videos.length)}
                        />
                      );
                    })()}
                    <ChevronRightIcon className={cn("size-3.5 shrink-0 transition-transform", open && "rotate-90")} />
                    {open ? <FolderOpenIcon className="size-3.5 shrink-0 text-primary" /> : <FolderIcon className="size-3.5 shrink-0 text-primary" />}
                    <span className="truncate font-medium pointer-coarse:break-all pointer-coarse:whitespace-normal">{node.name}</span>
                    <span className="ml-1.5 flex shrink-0 items-center gap-2 text-muted-foreground">
                      <span aria-hidden>·</span>
                      {t("library.filesCount", { count: node.fileCount })}
                      <span className="tabular-nums sm:hidden">· {formatBytes(node.sizeBytes)}</span>
                    </span>
                  </div>
                </TableCell>
                <TableCell className="hidden sm:table-cell" />
                <TableCell className="hidden text-right text-xs text-muted-foreground tabular-nums sm:table-cell">{formatBytes(node.sizeBytes)}</TableCell>
                {withMenu && (
                  <TableCell className="px-1 text-right">
                    <RowMenuButton items={items} title={node.path} className="text-muted-foreground" />
                  </TableCell>
                )}
              </TableRow>
              </RowContextMenu>
            );
          }
          const file = node.file;
          const items = actions?.file?.(file) ?? [];
          const openable = onOpenFile != null && file.tmdb_id != null && file.content_type != null;
          return (
            <RowContextMenu key={node.path} title={file.relative_path} items={items}>
            <TableRow
              className={cn(file.excluded && "opacity-60", (openable || (picking && packable(file))) && "cursor-pointer", picking && "select-none")}
              onClick={picking && packable(file) ? (e) => selection?.pick(packFile(file), e.shiftKey, orderedPackable) : openable ? () => onOpenFile(file) : undefined}
            >
              <TableCell className={indentClass} style={indent}>
                <div className={cn("flex items-center gap-1.5", picking ? "pl-0" : "pl-5")}>
                  {picking && selection && (packable(file) ? (
                    <PackCheckbox label={file.relative_path} checked={selection.has(packFile(file))} onPick={(shift) => selection.pick(packFile(file), shift, orderedPackable)} />
                  ) : (
                    CHECKBOX_SPACER
                  ))}
                  {picking && <span className="w-1" />}
                  {isVideo(node.name) ? <FileVideoIcon className="size-3.5 shrink-0 text-muted-foreground" /> : <FileIcon className="size-3.5 shrink-0 text-muted-foreground" />}
                  {/* Su touch il nome intero va a capo: il title lì non si vede. */}
                  <span className="truncate text-xs pointer-coarse:break-all pointer-coarse:whitespace-normal" title={file.relative_path}>
                    {node.name}
                  </span>
                  <HardlinkInfo linkedPaths={file.linked_paths} />
                </div>
                <div className={cn("mt-1 flex flex-wrap items-center gap-1.5 sm:hidden", picking ? "pl-0" : "pl-5")}>
                  <FileBadges file={file} duplicateKeys={duplicateKeys} />
                  <span className="text-xs text-muted-foreground tabular-nums">{formatBytes(file.size_bytes)}</span>
                </div>
              </TableCell>
              <TableCell className="hidden sm:table-cell">
                <div className="flex items-center gap-1.5">
                  <FileBadges file={file} duplicateKeys={duplicateKeys} />
                </div>
              </TableCell>
              <TableCell className="hidden text-right text-xs tabular-nums sm:table-cell">{formatBytes(file.size_bytes)}</TableCell>
              {withMenu && (
                <TableCell className="px-1 text-right">
                  <RowMenuButton items={items} title={file.relative_path} className="text-muted-foreground" />
                </TableCell>
              )}
            </TableRow>
            </RowContextMenu>
          );
        })}
        {hasMore && (
          <TableRow ref={sentinelRef} aria-hidden>
            <TableCell colSpan={withMenu ? 4 : 3} className="h-px p-0" />
          </TableRow>
        )}
      </TableBody>
    </Table>
  );
}
