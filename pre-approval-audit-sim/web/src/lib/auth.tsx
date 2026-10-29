import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { authApi, getToken, setToken, setUnauthorizedHandler, type CurrentUser, type Role } from './api'

interface AuthState {
  user: CurrentUser | null
  loading: boolean
  login: (username: string, password: string) => Promise<void>
  logout: () => void
  hasRole: (...roles: Role[]) => boolean
  // Effective OE to filter/scope by across the whole app. null = "all OEs" -
  // only ever possible for a global admin (user.oe_code === null); a
  // tenant-scoped user's own oe_code always wins, ignoring setOeScope.
  oeScope: string | null
  setOeScope: (oe: string | null) => void
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<CurrentUser | null>(null)
  const [loading, setLoading] = useState(true)
  const [oeOverride, setOeOverride] = useState<string | null>(null)
  const oeScope = user?.oe_code ?? oeOverride
  function setOeScope(oe: string | null) {
    if (user?.oe_code == null) setOeOverride(oe)
  }

  useEffect(() => {
    setUnauthorizedHandler(() => setUser(null))
    const token = getToken()
    if (!token) {
      setLoading(false)
      return
    }
    authApi
      .me()
      .then((me) => setUser(me))
      .catch(() => setToken(null))
      .finally(() => setLoading(false))
  }, [])

  async function login(username: string, password: string) {
    const res = await authApi.login(username, password)
    setToken(res.access_token)
    setUser({ username: res.username, display_name: res.display_name, role: res.role, oe_code: res.oe_code })
  }

  function logout() {
    setToken(null)
    setUser(null)
    setOeOverride(null)
    authApi.logout().catch(() => {})
  }

  function hasRole(...roles: Role[]) {
    return !!user && roles.includes(user.role)
  }

  return (
    <AuthContext.Provider value={{ user, loading, login, logout, hasRole, oeScope, setOeScope }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
