import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react'

export type WorkspaceTheme = 'business' | 'monitor'
export const THEME_STORAGE_KEY = 'smartgrid.workspace.theme'

interface ThemeContextValue {
  theme: WorkspaceTheme
  setTheme: (theme: WorkspaceTheme) => void
}

const ThemeContext = createContext<ThemeContextValue | null>(null)

const applyTheme = (theme: WorkspaceTheme) => {
  if (typeof document !== 'undefined') document.documentElement.dataset.theme = theme
}

// Run before React mounts so a saved monitor preference is applied to its first frame.
export const initializeWorkspaceTheme = (): WorkspaceTheme => {
  let theme: WorkspaceTheme = 'business'
  try {
    if (typeof window !== 'undefined' && window.localStorage.getItem(THEME_STORAGE_KEY) === 'monitor') {
      theme = 'monitor'
    }
  } catch {
    // Browsers can disable local storage; the current session must remain usable.
  }
  applyTheme(theme)
  return theme
}

export const ThemeProvider = ({ children }: { children: ReactNode }) => {
  const [theme, setCurrentTheme] = useState<WorkspaceTheme>(initializeWorkspaceTheme)
  const setTheme = useCallback((nextTheme: WorkspaceTheme) => {
    applyTheme(nextTheme)
    setCurrentTheme(nextTheme)
    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, nextTheme)
    } catch {
      // Keep the selection for this session when the browser cannot persist it.
    }
  }, [])
  const value = useMemo(() => ({ theme, setTheme }), [theme, setTheme])
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
}

export const useWorkspaceTheme = () => {
  const context = useContext(ThemeContext)
  if (!context) throw new Error('useWorkspaceTheme must be used within ThemeProvider')
  return context
}
