import { useQueryClient } from '@tanstack/react-query'
import { driver, type Driver } from 'driver.js'
import 'driver.js/dist/driver.css'
import { useEffect, useRef } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'

import type { Schemas } from '@/api/client'
import { t } from '@/lib/i18n'
import { DEFAULT_STATE, useOnboarding } from '@/onboarding/state'
import { isDone, visibleSteps } from '@/onboarding/steps'
import { tourStore, useActiveTour } from '@/onboarding/tourStore'
import { check, selector, stepsFor, tourFor } from '@/onboarding/tours'

type SetupStatus = Schemas['SetupStatusResponse']

const TICK_MS = 300
// Un'ancora sparita (dialog chiuso, lista che si ricarica) torna indietro
// solo dopo un attimo: il tempo di un'animazione o di un refetch.
const MISSING_GRACE_MS = 1500
// Un'ancora mai comparsa (pagina che carica): poi il fumetto al centro.
const NOT_FOUND_MS = 5000

// I livelli sopra la pagina (dialog, liste di una Select, menu): se non
// contengono l'ancora, il tour si ferma finché non si chiudono, se no
// l'overlay li coprirebbe (es. il selettore delle cartelle).
const LAYERS = '[data-slot="dialog-content"], [role="listbox"], [role="menu"], [role="alertdialog"]'

function foreignLayerOpen(anchor: Element | null): boolean {
  return Array.from(document.querySelectorAll(LAYERS)).some(
    (layer) => !layer.closest('.driver-popover') && !(anchor && layer.contains(anchor)),
  )
}

// Il tour guidato (src/onboarding/tours.ts) sopra driver.js: porta alla
// schermata, evidenzia un campo alla volta e aspetta quello che serve
// (un dialog aperto, un disco creato, una cartella scelta).
export function TourRunner() {
  const active = useActiveTour()
  const navigate = useNavigate()
  const location = useLocation()
  const here = useRef('')
  useEffect(() => {
    here.current = location.pathname + location.search
  }, [location])
  const queryClient = useQueryClient()
  const { state, save } = useOnboarding()
  const driverRef = useRef<Driver | null>(null)
  const internalDestroy = useRef(false)
  const answers = state?.answers ?? DEFAULT_STATE.answers
  // Lo stato più recente per chi finisce un tour (il timer lo legge dopo il render).
  const stateRef = useRef(state)
  useEffect(() => {
    stateRef.current = state
  }, [state])

  // Porta alla schermata del tour quando parte, non a ogni passo: se l'utente
  // va altrove, il fumetto aspetta che torni (o che chiuda il tour).
  useEffect(() => {
    if (!active) return
    const tour = tourFor(active.key)
    if (tour && active.index === 0) navigate(tour.route)
  }, [active?.key]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const destroy = () => {
      internalDestroy.current = true
      driverRef.current?.destroy()
      internalDestroy.current = false
    }
    if (!active) {
      destroy()
      return
    }
    const tour = tourFor(active.key)
    if (!tour) {
      tourStore.stop()
      return
    }
    const steps = stepsFor(tour, answers)
    const step = steps[active.index]
    const indexOf = (id: string | undefined) => {
      const found = steps.findIndex((s) => s.id === id)
      return found >= 0 ? found : active.index + 1
    }
    const status = () => queryClient.getQueryData<SetupStatus>(['setup-status'])
    const statusSteps = () => status()?.steps as Record<string, { done: boolean }> | undefined

    const afterThis = () => {
      const current = stateRef.current ?? DEFAULT_STATE
      const seen = current.seen.includes(tour.key) ? current.seen : [...current.seen, tour.key]
      const next = { ...current, seen }
      // Il tour che segue questo, o il prossimo passo della checklist con un
      // tour e non ancora fatto.
      const nextStep = tour.last
        ? undefined
        : tour.then
        ? { key: tour.then }
        : visibleSteps(next)
          .filter((s) => s.key !== tour.key && tourFor(s.key))
          .find((s) => !isDone(s, status(), next))
      return { next, nextStep }
    }
    const finish = () => {
      destroy()
      const { next, nextStep } = afterThis()
      save(next)
      if (nextStep) tourStore.start(nextStep.key)
      else {
        tourStore.stop()
        navigate('/dashboard')
      }
    }
    if (!step) {
      finish()
      return
    }

    if (!driverRef.current) {
      driverRef.current = driver({
        popoverClass: 'nazgarr-tour',
        stagePadding: 6,
        stageRadius: 8,
        allowClose: true,
        // Un click fuori dal campo non chiude niente: si chiude con la X o Esc.
        overlayClickBehavior: () => {},
        onDestroyed: () => {
          if (!internalDestroy.current) tourStore.stop()
        },
      })
    }
    const drv = driverRef.current
    const started = Date.now()
    let shown = false
    let paused = false
    let missingSince: number | null = null
    const last = active.index === steps.length - 1
    const nextTour = last ? afterThis().nextStep : undefined

    const show = (element: Element | null) => {
      const base = `onboarding.tour.${tour.key}.${step.id}`
      const buttons: ('next' | 'previous' | 'close')[] = ['close']
      if (active.index > 0) buttons.unshift('previous')
      if (step.next || last) buttons.push('next')
      drv.highlight({
        element: element ?? undefined,
        popover: {
          title: t(`${base}.title`),
          description: t(`${base}.body`),
          side: step.side,
          showButtons: buttons,
          prevBtnText: t('onboarding.tour.back'),
          nextBtnText: last
            ? nextTour ? t('onboarding.tour.continue', { next: t(`onboarding.step.${nextTour.key}.title`) }) : t('onboarding.tour.done')
            : t('onboarding.tour.next'),
          onNextClick: () => (last ? finish() : tourStore.goTo(active.index + 1)),
          onPrevClick: () => tourStore.goTo(Math.max(0, active.index - 1)),
          onCloseClick: () => {
            destroy()
            tourStore.stop()
          },
          onPopoverRender: (popover) => {
            popover.progress.textContent = `${t(`onboarding.step.${tour.key}.title`)} · ${active.index + 1}/${steps.length}`
            popover.progress.style.display = 'block'
            if (!step.next && !last && step.waitFor) {
              const hint = document.createElement('p')
              hint.className = 'nazgarr-tour-waiting'
              hint.textContent = t('onboarding.tour.waiting')
              popover.description.appendChild(hint)
            }
          },
        },
      })
      shown = true
    }

    const tick = () => {
      const statusNow = statusSteps()
      if (step.skipIf && check(step.skipIf, document, statusNow)) return tourStore.goTo(indexOf(step.skipTo))
      if (step.waitFor && check(step.waitFor, document, statusNow)) {
        return last ? finish() : tourStore.goTo(active.index + 1)
      }
      const element = step.anchor ? document.querySelector(selector(step.anchor)) : null
      if (step.anchor && !element) {
        if (shown && step.backTo) {
          missingSince ??= Date.now()
          if (Date.now() - missingSince > MISSING_GRACE_MS) return tourStore.goTo(indexOf(step.backTo))
          return
        }
        if (!shown && Date.now() - started > NOT_FOUND_MS) show(null)
        return
      }
      missingSince = null
      const foreign = foreignLayerOpen(element)
      if (foreign && !paused) {
        paused = true
        destroy()
        shown = false
        return
      }
      if (foreign) return
      if (!shown || paused) {
        paused = false
        show(element)
      } else drv.refresh()
    }

    // Il passo prima non resta evidenziato mentre si aspetta l'ancora nuova.
    destroy()
    // Un passo su un'altra schermata (tour delle viste) ci porta lì.
    if (step.route && here.current !== step.route) navigate(step.route)
    tick()
    const timer = window.setInterval(tick, TICK_MS)
    // Le condizioni sulla configurazione: setup-status più spesso mentre si aspetta.
    const refetch = step.waitFor && 'status' in step.waitFor
      ? window.setInterval(() => queryClient.invalidateQueries({ queryKey: ['setup-status'] }), 2000)
      : undefined
    return () => {
      window.clearInterval(timer)
      if (refetch) window.clearInterval(refetch)
    }
  }, [active, answers.upload, answers.arr]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => () => driverRef.current?.destroy(), [])
  return null
}
