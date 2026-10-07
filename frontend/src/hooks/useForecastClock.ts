import { useEffect, useState } from 'react'

/** Expire forecast intervals even when a refresh fails or the tab stays open. */
export function useForecastClock() {
  const [now, setNow] = useState(Date.now)
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>
    const update = () => {
      clearTimeout(timer)
      setNow(Date.now())
      timer = setTimeout(update, 60_000 - Date.now() % 60_000 + 10)
    }
    update()
    window.addEventListener('focus', update)
    return () => { clearTimeout(timer); window.removeEventListener('focus', update) }
  }, [])
  return now
}
