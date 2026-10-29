import type { ReactNode } from 'react'
import { cn } from '../../lib/utils'

export type BadgeKind = 'success' | 'warning' | 'error' | 'info' | 'neutral' | 'accent'

const kindClasses: Record<BadgeKind, string> = {
  success: 'bg-success-bg border-success-border text-success-text',
  warning: 'bg-warning-bg border-warning-border text-warning-text',
  error: 'bg-error-bg border-error-border text-error-text',
  info: 'bg-info-bg border-info-border text-info-text',
  neutral: 'bg-bg-elevated border-border text-text-secondary',
  accent: 'bg-accent-glow border-accent/40 text-accent-bright',
}

export function Badge({
  children,
  kind = 'neutral',
  className,
  dot,
}: {
  children: ReactNode
  kind?: BadgeKind
  className?: string
  dot?: boolean
}) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[11px] font-semibold tracking-wide',
        kindClasses[kind],
        className,
      )}
    >
      {dot && <span className="size-1.5 rounded-full bg-current" />}
      {children}
    </span>
  )
}

const RISK_KIND: Record<string, BadgeKind> = { LOW: 'success', PENDING: 'warning', HIGH: 'error' }
const STATUS_KIND: Record<string, BadgeKind> = {
  APPROVED: 'success',
  REJECTED: 'error',
  SUBMITTED: 'info',
}

export function RiskBadge({ band }: { band: string }) {
  return <Badge kind={RISK_KIND[band] ?? 'neutral'}>{band}</Badge>
}

export function StatusBadge({ status }: { status: string }) {
  return <Badge kind={STATUS_KIND[status] ?? 'neutral'}>{status}</Badge>
}

export function RoleBadge({ role }: { role: string }) {
  const kind: BadgeKind = role === 'admin' ? 'accent' : role === 'auditor' ? 'warning' : 'neutral'
  return <Badge kind={kind}>{role}</Badge>
}
