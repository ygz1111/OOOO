import { useMemo, useSyncExternalStore } from 'react'
import type { LoadInputQuality } from '../types'

interface ForecastSnapshot<T> {
  data: T | null
  loading: boolean
  error: string | null
}

/** One request and timer per resource, retained while users switch routes. */
export function createForecastResource<T>(
  fetch: (forceRefresh: boolean) => Promise<T>,
  qualityOf: (data: T) => Pick<LoadInputQuality, 'refresh_in_progress' | 'components'> | null | undefined,
  task: string,
  fallbackError: string,
) {
  const createStore = () => {
    let snapshot: ForecastSnapshot<T> = { data: null, loading: false, error: null }
    let lastAttempt: number | null = null
    let delay = 300000
    let pending: Promise<void> | null = null
    let timer: ReturnType<typeof setTimeout> | undefined
    const listeners = new Set<() => void>()
    const publish = (next: ForecastSnapshot<T>) => {
      snapshot = next
      listeners.forEach(listener => listener())
    }
    const schedule = () => {
      clearTimeout(timer)
      if (!listeners.size || document.hidden || pending) return
      const remaining = lastAttempt == null ? 0 : Math.max(0, lastAttempt + delay - Date.now())
      timer = setTimeout(() => { void load(false) }, remaining)
    }
    const load = (forceRefresh = true): Promise<void> => {
      if (pending) return pending
      clearTimeout(timer)
      publish({ ...snapshot, loading: true })
      // Assign pending before starting the request, including synchronous failures.
      pending = Promise.resolve().then(async () => {
        try {
          const data = await fetch(forceRefresh)
          const quality = qualityOf(data)
          const component = quality?.components?.[task]
          delay = quality?.refresh_in_progress ? 5000
            : component?.status === 'unavailable' || component?.status === 'cached' ? 35000 : 300000
          publish({ data, loading: true, error: null })
        } catch (error) {
          delay = 35000
          publish({ ...snapshot, error: error instanceof Error ? error.message : fallbackError })
        }
      }).finally(() => {
        lastAttempt = Date.now()
        pending = null
        publish({ ...snapshot, loading: false })
        schedule()
      })
      return pending
    }
    const onVisibility = () => {
      clearTimeout(timer)
      if (!document.hidden) {
        // Returning to a tab keeps the original deadline; it is not a refresh click.
        if (lastAttempt == null || Date.now() - lastAttempt >= delay) void load(false)
        else schedule()
      }
    }
    return {
      getSnapshot: () => snapshot,
      refresh: () => load(true),
      subscribe(listener: () => void) {
        listeners.add(listener)
        if (listeners.size === 1) {
          document.addEventListener('visibilitychange', onVisibility)
          schedule()
          if (lastAttempt == null && !document.hidden) void load(false)
        }
        return () => {
          listeners.delete(listener)
          if (!listeners.size) {
            clearTimeout(timer)
            document.removeEventListener('visibilitychange', onVisibility)
          }
        }
      },
    }
  }
  // A new login must never inherit another session's cached results.
  let current: { scope: string; store: ReturnType<typeof createStore> } | undefined
  return (scope: string) => {
    if (!current || current.scope !== scope) current = { scope, store: createStore() }
    return current.store
  }
}

export function useForecastResource<T>(resource: ReturnType<typeof createForecastResource<T>>, scope: string) {
  const store = useMemo(() => resource(scope), [resource, scope])
  const snapshot = useSyncExternalStore(store.subscribe, store.getSnapshot)
  return { ...snapshot, refresh: store.refresh }
}
