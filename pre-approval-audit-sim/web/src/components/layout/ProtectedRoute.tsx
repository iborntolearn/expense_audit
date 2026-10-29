import { Navigate } from 'react-router-dom'
import type { ReactNode } from 'react'
import { Loader2, ShieldAlert } from 'lucide-react'
import { useAuth } from '../../lib/auth'
import type { Role } from '../../lib/api'

export function ProtectedRoute({ children, roles }: { children: ReactNode; roles?: Role[] }) {
  const { user, loading } = useAuth()

  if (loading) {
    return (
      <div className="flex h-screen items-center justify-center bg-bg-base">
        <Loader2 className="size-6 animate-spin text-accent" />
      </div>
    )
  }
  if (!user) return <Navigate to="/login" replace />
  if (roles && !roles.includes(user.role)) {
    return (
      <div className="flex h-[70vh] flex-col items-center justify-center gap-3 text-center">
        <ShieldAlert className="size-10 text-text-faint" />
        <div className="text-base font-semibold text-text-primary">Access restricted</div>
        <p className="max-w-sm text-sm text-text-muted">
          Your role ({user.role}) doesn't have permission to view this page.
        </p>
      </div>
    )
  }
  return <>{children}</>
}
