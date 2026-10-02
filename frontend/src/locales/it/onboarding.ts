// Il tour del primo accesso (src/onboarding). Tono neutro, con al massimo una
// strizzata d'occhio fantasy per passo: mai nomi né citazioni letterali.
export const onboarding = {
  'onboarding.welcome.title': 'Benvenuto in Nazgarr',
  'onboarding.welcome.description':
    'Un solo posto per trovare i tuoi media, le cartelle dei torrent e i client torrent, e per legarli insieme con gli hardlink. Pochi minuti di configurazione, il resto è guidato.',
  'onboarding.welcome.approval':
    'Nulla passa senza il tuo consenso: Nazgarr non crea mai un hardlink, non aggiunge un torrent e non carica nulla finché non lo approvi nella coda di revisione. L’esecuzione automatica esiste, ma è disattivata e resta così finché non la attivi tu.',
  'onboarding.welcome.needTitle': 'Meglio avere a portata di mano',
  'onboarding.welcome.needPaths': 'Dove sono montati i tuoi media e i download dei torrent dentro questo container (es. /data/media e /data/torrents).',
  'onboarding.welcome.needClient': 'Indirizzo e credenziali del tuo client torrent (per ora qBittorrent).',
  'onboarding.welcome.needTmdb': 'Una API key TMDB gratuita, per riconoscere film e serie.',
  'onboarding.welcome.needTracker': 'Per ogni tracker privato: il suo indirizzo e il tuo token API.',
  'onboarding.welcome.ask.upload': 'Caricherai nuovi torrent?',
  'onboarding.welcome.ask.uploadHelp': 'Aggiunge al percorso gli host di immagini e le impostazioni di upload.',
  'onboarding.welcome.ask.arr': 'Usi Radarr o Sonarr?',
  'onboarding.welcome.ask.arrHelp': 'Facoltativo: la loro cronologia di importazione spiega perché un torrent non è nella tua libreria.',
  'onboarding.welcome.later': 'Più tardi',
  'onboarding.welcome.start': 'Inizia la configurazione',

  'onboarding.checklist.title': 'Per iniziare',
  'onboarding.checklist.description': 'Ogni passo si completa da solo appena la configurazione c’è, ovunque tu l’abbia impostata.',
  'onboarding.checklist.readyTitle': 'È tutto a posto',
  'onboarding.checklist.readyDescription': 'Il cammino continua: i passi facoltativi restano qui quando li vorrai.',
  'onboarding.checklist.hide': 'Nascondi',
  'onboarding.checklist.finish': 'Fatto',
  'onboarding.checklist.optional': 'facoltativo',
  'onboarding.checklist.guide': 'Guidami',

  'onboarding.step.storage.title': 'Storage',
  'onboarding.step.storage.summary': 'I tuoi dischi: la cartella dei torrent su ognuno, e la libreria media se ne hai una.',
  'onboarding.step.clients.title': 'Client torrent',
  'onboarding.step.clients.summary': 'Collega il tuo client torrent, così Nazgarr sa cosa ha in seed.',
  'onboarding.step.metadata.title': 'Metadati',
  'onboarding.step.metadata.summary': 'Una API key TMDB, per riconoscere film e serie.',
  'onboarding.step.arr.title': 'Radarr / Sonarr',
  'onboarding.step.arr.summary': 'La loro cronologia di importazione: perché un torrent non è mai arrivato in libreria.',
  'onboarding.step.trackers.title': 'Tracker',
  'onboarding.step.trackers.summary': 'I tuoi tracker privati, per trovare cosa puoi rimettere in seed.',
  'onboarding.step.exclusions.title': 'Esclusioni',
  'onboarding.step.exclusions.summary': 'Sample, extra e cartelle da lasciare fuori da ogni conteggio.',
  'onboarding.step.reseeding.title': 'Reseed',
  'onboarding.step.reseeding.summary': 'Quanto deve essere sicuro un match prima di essere consigliato.',
  'onboarding.step.upload.title': 'Upload',
  'onboarding.step.upload.summary': 'Host di immagini per gli screenshot, e le impostazioni predefinite di upload.',
  'onboarding.step.first_scan.title': 'Prima scansione',
  'onboarding.step.views.title': 'Tour delle viste',
  'onboarding.step.first_scan.summary': 'Scansiona tutto una volta. Se è lunga, è il momento giusto per una seconda colazione.',

  'onboarding.restart.title': 'Tour iniziale',
  'onboarding.restart.description': 'La configurazione guidata del primo accesso, con la sua checklist nella dashboard.',
  'onboarding.restart.button': 'Riavvia il tour',
  'onboarding.tour.next': 'Avanti',
  'onboarding.tour.back': 'Indietro',
  'onboarding.tour.done': 'Fatto',
  'onboarding.tour.continue': 'Continua: {next}',
  'onboarding.tour.waiting': 'Vai pure, il tour prosegue da solo.',

  'onboarding.tour.storage.intro.title': 'I tuoi dischi',
  'onboarding.tour.storage.intro.body':
    'Un disco è un filesystem così come lo vede questo container. Gli hardlink funzionano solo dentro un singolo filesystem, quindi ogni disco contiene sia la sua libreria media sia la sua cartella dei torrent.\nCon un solo mount condiviso (es. /data con dentro media/ e torrents/) ti basta un disco.',
  'onboarding.tour.storage.add.title': 'Aggiungi un disco',
  'onboarding.tour.storage.add.body': 'Clicca "Aggiungi disco" per registrare il primo.',
  'onboarding.tour.storage.label.title': 'Un nome',
  'onboarding.tour.storage.label.body': 'Qualsiasi cosa ti dica di quale disco si tratta: "main", "disk1", "nvme".',
  'onboarding.tour.storage.root.title': 'Dove è montato',
  'onboarding.tour.storage.root.body':
    'Il percorso dentro questo container, non sul tuo host. Parte da disk_scan_root (es. /data): lascialo così con un solo mount, oppure scegli la sottocartella di un disco fisico (es. /data/disk1) se ne monti diversi.',
  'onboarding.tour.storage.create.title': 'Crealo',
  'onboarding.tour.storage.create.body': 'Nazgarr controlla che il percorso esista e ricorda su quale filesystem si trova.',
  'onboarding.tour.storage.media.title': 'La cartella media',
  'onboarding.tour.storage.media.body':
    'Cliccala e scegli la cartella con la tua libreria (film e serie), quella usata da Plex, Jellyfin o Radarr/Sonarr. Ogni file al suo interno viene abbinato a ciò che hai in seed. Facoltativa: senza, Nazgarr lavora solo sui tuoi torrent e sugli upload.',
  'onboarding.tour.storage.seeding.title': 'La cartella dei torrent',
  'onboarding.tour.storage.seeding.body':
    'Ora la cartella dove il tuo client torrent scarica e fa seed (es. torrents/). I file in seed qui senza un hardlink nella libreria compaiono come "non importati"; i file della libreria senza torrent come "orfani".',
  'onboarding.tour.storage.new.title': 'Nuovi hardlink (facoltativo)',
  'onboarding.tour.storage.new.body':
    'Dove un reseed crea i suoi hardlink, e dove si dice al client di metterli in seed. Vuoto significa la cartella dei torrent stessa, che va bene nella maggior parte dei casi.',
  'onboarding.tour.storage.upload.title': 'Upload (facoltativo)',
  'onboarding.tour.storage.upload.body': 'Lo stesso per i tuoi upload: dove i loro file vengono collegati e messi in seed. Vuoto significa la cartella dei torrent.',
  'onboarding.tour.storage.verify.title': 'Un controllo veloce',
  'onboarding.tour.storage.verify.body':
    'Controlla che il disco sia ancora lo stesso filesystem di quando l’hai aggiunto, così gli hardlink continuano a funzionare. Fai la guardia come una torre: rilancialo ogni volta che rimonti o sposti un disco.',

  'onboarding.tour.clients.add.title': 'Aggiungi il tuo client torrent',
  'onboarding.tour.clients.add.body': 'Clicca "Aggiungi client". Nazgarr si limita a leggerlo, finché non approvi un reseed o un upload.',
  'onboarding.tour.clients.type.title': 'Quale client',
  'onboarding.tour.clients.type.body': 'qBittorrent, oppure qui se gestisci con quello più istanze di qBittorrent. I plugin possono aggiungerne altri.',
  'onboarding.tour.clients.url.title': 'Il suo indirizzo',
  'onboarding.tour.clients.url.body':
    'Come lo raggiunge questo container: con Docker sulla stessa rete di solito è il nome del container (http://qbittorrent:8080), non localhost.',
  'onboarding.tour.clients.credentials.title': 'Credenziali',
  'onboarding.tour.clients.credentials.body': 'Nome utente e password della WebUI (per qui, la sua API key e il numero dell’istanza). Salvati cifrati.',
  'onboarding.tour.clients.create.title': 'Crealo',
  'onboarding.tour.clients.create.body': 'Poi proviamo la connessione.',
  'onboarding.tour.clients.test.title': 'Prova la connessione',
  'onboarding.tour.clients.test.body': 'Clicca "Prova connessione": ti dice quanti torrent ha il client. Se fallisce, controlla l’indirizzo e le credenziali della WebUI.',
  'onboarding.tour.clients.disks.title': 'Dischi e percorsi (facoltativo)',
  'onboarding.tour.clients.disks.body':
    'Se il client vede i tuoi file agli stessi percorsi di Nazgarr (entrambi usano /data), qui non c’è niente da fare. Usalo solo per limitare il client ad alcuni dischi, o quando monta un disco altrove (es. /downloads invece di /data/torrents).',
  'onboarding.tour.clients.labels.title': 'Categoria e tag per gli upload',
  'onboarding.tour.clients.labels.body': 'La categoria e i tag che i tuoi upload ricevono su questo client (es. tag "release"). Ogni upload può comunque cambiarli.',

  'onboarding.tour.metadata.tmdb.title': 'TMDB',
  'onboarding.tour.metadata.tmdb.body':
    'La chiave che permette a Nazgarr di riconoscere cos’è ogni file. È gratuita: crea un account su themoviedb.org, poi Settings › API, e incolla qui la API key (v3). Tienila nascosta e al sicuro: viene salvata cifrata.',
  'onboarding.tour.metadata.tvdb.title': 'TVDB (facoltativo)',
  'onboarding.tour.metadata.tvdb.body': 'Non ancora usato: puoi lasciarlo vuoto.',
  'onboarding.tour.metadata.radarr.title': 'Radarr',
  'onboarding.tour.metadata.radarr.body':
    'Il suo indirizzo e la API key (Radarr › Settings › General). La sua cronologia di importazione spiega perché un torrent non è mai arrivato in libreria, e riconosce i file più in fretta che dal nome.',
  'onboarding.tour.metadata.sonarr.title': 'Sonarr',
  'onboarding.tour.metadata.sonarr.body': 'Lo stesso per le serie: indirizzo e API key da Sonarr › Settings › General.',

  'onboarding.tour.trackers.add.title': 'Aggiungi un tracker',
  'onboarding.tour.trackers.add.body': 'Clicca "Aggiungi tracker" per ogni tracker privato che usi.',
  'onboarding.tour.trackers.preset.title': 'Un tracker conosciuto?',
  'onboarding.tour.trackers.preset.body': 'Sceglilo dall’elenco: nome, indirizzo e impostazioni di upload vengono compilati. Non è nell’elenco? Compila i campi a mano.',
  'onboarding.tour.trackers.url.title': 'Il suo indirizzo',
  'onboarding.tour.trackers.url.body': 'L’indirizzo del sito, es. https://mytracker.example. È lì che viene chiamata l’API.',
  'onboarding.tour.trackers.token.title': 'Il tuo token API',
  'onboarding.tour.trackers.token.body':
    'Sui tracker UNIT3D: il tuo profilo › Settings › API key. Permette a Nazgarr di cercare nel catalogo, niente di più. Tienilo nascosto e al sicuro: viene salvato cifrato.',
  'onboarding.tour.trackers.announce.title': 'Announce URL (solo upload)',
  'onboarding.tour.trackers.announce.body':
    'Serve solo per creare i torrent dei tuoi upload: contiene la tua passkey (dalla pagina di upload del tracker). Lascialo vuoto se fai solo reseed.',
  'onboarding.tour.trackers.create.title': 'Crealo',
  'onboarding.tour.trackers.create.body': 'Puoi aggiungere altri tracker più tardi allo stesso modo.',
  'onboarding.tour.trackers.client.title': 'Quale client lo mette in seed',
  'onboarding.tour.trackers.client.body': 'Dove vengono aggiunti i reseed di questo tracker, es. un client solo per i tracker privati. Predefinito: il primo attivo.',
  'onboarding.tour.trackers.language.title': 'La sua lingua',
  'onboarding.tour.trackers.language.body': 'Per i nomi degli upload: il titolo in questa lingua, il suo audio per primo, e come vengono scritti i sottotitoli.',
  'onboarding.tour.trackers.seed.title': 'Seed minimo',
  'onboarding.tour.trackers.seed.body':
    'La regola hit and run del tracker (seedtime e/o ratio). Così Non importati ti dice quali vecchi torrent puoi rimuovere in sicurezza. Facoltativo.',
  'onboarding.tour.trackers.profile.title': 'Profilo di upload',
  'onboarding.tour.trackers.profile.body': 'Come vengono nominati e categorizzati gli upload su questo tracker. Un tracker conosciuto ne ha già uno: cambialo solo se serve.',
  'onboarding.tour.exclusions.presets.title': 'Esclusioni pronte',
  'onboarding.tour.exclusions.presets.body':
    'Gruppi di file che non contano mai: i metadati dei media server (artwork, .nfo) sono attivi di default; si possono aggiungere sample e residui della scene. I file esclusi restano sul disco, vengono solo lasciati fuori da stati, conteggi e ricerche.',
  'onboarding.tour.exclusions.custom.title': 'I tuoi pattern',
  'onboarding.tour.exclusions.custom.body': 'Qualsiasi altra cosa da lasciare fuori, come pattern sul percorso (es. */Extras/*). Puoi anche escludere un file o una cartella con il tasto destro nella Libreria.',

  'onboarding.tour.reseeding.search.title': 'Cosa viene cercato',
  'onboarding.tour.reseeding.search.body':
    'Ogni scansione cerca i file della libreria che non sono in seed. Con il cross-seed attivo, un file in seed su un tracker viene cercato anche sugli altri.',
  'onboarding.tour.reseeding.thresholds.title': 'Quanto è sicuro sicuro',
  'onboarding.tour.reseeding.thresholds.body':
    'Sopra queste soglie di confidenza un match viene segnato come consigliato; sotto, aspetta in coda come proposta. In ogni caso nulla viene eseguito finché non lo approvi, a meno che tu non attivi l’esecuzione automatica qui sotto.',
  'onboarding.tour.reseeding.execution.title': 'Prima di fare qualsiasi cosa',
  'onboarding.tour.reseeding.execution.body':
    'Il controllo completo legge ogni pezzo prima che venga creato un hardlink o un torrent, così il recheck del client non può fallire. L’esecuzione automatica è disattivata, e resta così a meno che tu non scelga diversamente.',

  'onboarding.tour.upload.hosts.title': 'Host di immagini',
  'onboarding.tour.upload.hosts.body':
    'Dove finiscono gli screenshot dei tuoi upload, in quest’ordine: trascina per cambiarlo, rimuovi quelli che non vuoi. Imgbox e Pixhost non richiedono una chiave; per gli altri incolla la tua API key sulla destra.',
  'onboarding.tour.upload.screenshots.title': 'Screenshot',
  'onboarding.tour.upload.screenshots.body': 'Quanti per upload, e se applicare il tone mapping ai fotogrammi HDR perché non sembrino slavati.',
  'onboarding.tour.upload.description.title': 'Descrizione',
  'onboarding.tour.upload.description.body': 'Un’intestazione e una firma in BBCode attorno alla descrizione che Nazgarr scrive per ogni upload.',
  'onboarding.tour.upload.names.title': 'Nomi dei file',
  'onboarding.tour.upload.names.body':
    'Come vengono nominati i file dentro un nuovo torrent quando arrivano dalla tua libreria: il nome della release collegata con hardlink se c’è, altrimenti questo pattern.',

  'onboarding.tour.first_scan.run.title': 'La prima scansione',
  'onboarding.tour.first_scan.run.body':
    'Clicca "Scansiona ora": Nazgarr legge i tuoi dischi, riconosce ogni file, indicizza i tuoi client e cerca sui tuoi tracker. Si limita a leggere: nulla viene collegato, aggiunto o spostato.',
  'onboarding.tour.first_scan.progress.title': 'Ci vuole un po’',
  'onboarding.tour.first_scan.progress.body':
    'L’avanzamento è in basso a destra, e intanto puoi continuare a usare Nazgarr. La prima scansione di una libreria grande è il momento giusto per una seconda colazione. Nel frattempo, diamo un’occhiata in giro.',

  'onboarding.tour.views.intro.title': 'Uno sguardo dalla torre',
  'onboarding.tour.views.intro.body': 'Come una torre di guardia, la Dashboard vede tutto in un colpo solo. Un breve tour di dove si trovano le cose; i numeri si riempiono man mano che la scansione procede.',
  'onboarding.tour.views.health.title': 'Salute della libreria',
  'onboarding.tour.views.health.body': 'Quanta parte della tua libreria, per dimensione, è in seed tramite un hardlink. Accanto, come è cambiata nel tempo.',
  'onboarding.tour.views.metrics.title': 'Cosa merita un’occhiata',
  'onboarding.tour.views.metrics.body':
    'Media con hardlink, torrent orfani, torrent non importati nella libreria e duplicati, con l’andamento dall’ultima scansione. Ogni scheda apre l’elenco corrispondente.',
  'onboarding.tour.views.changes.title': 'Cosa è cambiato',
  'onboarding.tour.views.changes.body': 'File per file, cosa è cambiato dalla scansione precedente, e la cronologia delle scansioni.',
  'onboarding.tour.views.filter.title': 'Un tracker alla volta',
  'onboarding.tour.views.filter.body': 'Ogni vista può contare tutti i torrent, solo i tracker configurati, o uno solo. La scelta viene ricordata.',
  'onboarding.tour.views.library.title': 'La tua libreria',
  'onboarding.tour.views.library.body':
    'I file delle tue cartelle media, come albero di cartelle o come locandine. Clic destro su un file o una cartella: caricalo, fanne il reseed o escludilo.',
  'onboarding.tour.views.states.title': 'In seed o orfano',
  'onboarding.tour.views.states.body':
    'In seed: un hardlink è in seed in un client. Orfano: niente lo mette in seed, quindi è un candidato per un reseed. Clicca una scheda per filtrare.',
  'onboarding.tour.views.not_imported.title': 'Non importati',
  'onboarding.tour.views.not_imported.body':
    'Non tutti i file che vagano sono perduti: questi sono in seed senza un hardlink nella tua libreria, ognuno con il motivo (sostituito da un upgrade, una copia, mai importato). Con un requisito di seed sul tracker, ti dice anche quali puoi togliere.',
  'onboarding.tour.views.review.title': 'La coda di revisione',
  'onboarding.tour.views.review.body':
    'Ogni proposta aspetta qui, con la sua confidenza e cosa farebbe. Approva o rifiuta: nulla passa senza il tuo consenso. Il cammino continua: le prossime scansioni la terranno piena.',
  'onboarding.tour.storage.watch.title': 'Una cartella per le tue release (facoltativo)',
  'onboarding.tour.storage.watch.body':
    'Se pubblichi i tuoi encode: ciò che metti in questa cartella avvia un upload da solo, fino alla decisione, dove aspetta la tua approvazione. Quando è in seed, viene spostato nella cartella degli upload.',
  'onboarding.tour.upload.releases.title': 'Le tue release',
  'onboarding.tour.upload.releases.body':
    'Il tuo nome da releaser, usato come gruppo degli upload dalla cartella osservata, e quanto deve essere sicuro un match TMDB per essere confermato da solo, per ogni upload.',
} as const
