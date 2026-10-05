import { CheckCircle2Icon, FlaskConicalIcon } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'

import { Card, CardContent } from '@/components/ui/card'
import { t } from '@/lib/i18n'
import { DEMO_UPLOAD_ID, startUploadDemo, stopUploadDemo, useUploadDemoStep } from '@/lib/uploadDemo'
import { UploadJobView } from '@/pages/upload/UploadJobPage'

// L'upload di esempio del tour (src/lib/uploadDemo.ts): le schermate vere,
// con dati finti che non lasciano mai il browser. ?step=decision parte dalla
// decisione.
const startingStep = () =>
  new URLSearchParams(window.location.search).get('step') === 'decision' ? 'decision' : 'match'

export function UploadDemoPage() {
  const queryClient = useQueryClient()
  // Attivo già al primo render: gli effetti dei figli (la lettura
  // dell'upload) partono prima di quelli di questa pagina, e la prima
  // richiesta non deve mai arrivare al server.
  useState(() => {
    queryClient.removeQueries({ queryKey: ['uploads', DEMO_UPLOAD_ID] })
    startUploadDemo(startingStep())
    return true
  })
  const step = useUploadDemoStep()
  // Il tour passa da ?step=match a ?step=decision sulla stessa pagina.
  const [params] = useSearchParams()
  const requested = params.get('step')
  useEffect(() => {
    if (requested) startUploadDemo(requested === 'decision' ? 'decision' : 'match')
  }, [requested])
  useEffect(() => {
    startUploadDemo(startingStep()) // di nuovo dopo il doppio montaggio di StrictMode
    return () => {
      stopUploadDemo()
      queryClient.removeQueries({ queryKey: ['uploads', DEMO_UPLOAD_ID] })
    }
  }, [queryClient])
  // Il passo cambia (conferma del match): la pagina rilegge l'esempio.
  useEffect(() => {
    void queryClient.invalidateQueries({ queryKey: ['uploads', DEMO_UPLOAD_ID] })
  }, [step, queryClient])

  return (
    <div className="grid min-w-0 gap-4">
      <div data-tour="demo.banner" className="flex gap-3 rounded-lg border border-sky-500/40 bg-sky-500/10 p-4 text-sm">
        <FlaskConicalIcon className="mt-0.5 size-4 shrink-0 text-sky-600 dark:text-sky-400" />
        <div className="grid gap-1">
          <p className="font-medium">{t('upload.demo.title')}</p>
          <p className="text-muted-foreground">{t('upload.demo.description')}</p>
        </div>
      </div>
      {step === 'approved' ? (
        <Card>
          <CardContent className="flex items-start gap-3 py-6 text-sm">
            <CheckCircle2Icon className="mt-0.5 size-5 shrink-0 text-emerald-600" />
            <span>{t('upload.demo.approved')}</span>
          </CardContent>
        </Card>
      ) : (
        step === 'match' ? (
          <div data-tour="demo.match">
            <UploadJobView id={DEMO_UPLOAD_ID} />
          </div>
        ) : (
          <div data-tour="demo.decision">
            <UploadJobView id={DEMO_UPLOAD_ID} />
          </div>
        )
      )}
    </div>
  )
}
