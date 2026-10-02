import { activity } from './activity'
import { application } from './application'
import { auth } from './auth'
import { changes } from './changes'
import { common } from './common'
import { config } from './config'
import { dashboard } from './dashboard'
import { disks } from './disks'
import { errors } from './errors'
import { exclusions } from './exclusions'
import { fullCheck } from './fullCheck'
import { integrations } from './integrations'
import { interfaceSettings } from './interface'
import { itemDetail } from './itemDetail'
import { layout } from './layout'
import { library } from './library'
import { logs } from './logs'
import { metadata } from './metadata'
import { misc } from './misc'
import { notImported } from './notImported'
import { onboarding } from './onboarding'
import { reseeding } from './reseeding'
import { runStatus } from './runStatus'
import { scans } from './scans'
import { security } from './security'
import { timeLanguage } from './timeLanguage'
import { torrent } from './torrent'
import { torrentClients } from './torrentClients'
import { trackers } from './trackers'
import { naming } from './naming'
import { plugins } from './plugins'
import { webhooks } from './webhooks'
import { trackerFilter } from './trackerFilter'
import { pack } from './pack'
import { upload } from './upload'
import { uploadSettings } from './uploadSettings'

// Ogni modulo di dominio esporta chiavi già namespaced (es. "errors.foo",
// "disks.title") — qui solo un merge piatto, mai nesting: t() resta un
// semplice lookup O(1) su un oggetto, senza dover camminare un albero.
export const en = {
  ...activity,
  ...application,
  ...auth,
  ...changes,
  ...common,
  ...config,
  ...dashboard,
  ...disks,
  ...errors,
  ...exclusions,
  ...fullCheck,
  ...integrations,
  ...interfaceSettings,
  ...itemDetail,
  ...layout,
  ...library,
  ...logs,
  ...metadata,
  ...misc,
  ...notImported,
  ...onboarding,
  ...reseeding,
  ...runStatus,
  ...scans,
  ...security,
  ...timeLanguage,
  ...torrent,
  ...torrentClients,
  ...trackers,
  ...naming,
  ...trackerFilter,
  ...pack,
  ...upload,
  ...uploadSettings,
  ...plugins,
  ...webhooks,
} as const

export type MessageKey = keyof typeof en
