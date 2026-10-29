import type { ReactNode } from 'react'
import type { LucideIcon } from 'lucide-react'
import { cn } from '../../lib/utils'

export function KpiTile({
  label,
  value,
  icon: Icon,
  bad,
  hint,
}: {
  label: string
  value: ReactNode
  icon?: LucideIcon
  bad?: boolean
  hint?: string
}) {
  return (
    <div
      className={cn(
        'group relative overflow-hidden rounded-xl border bg-bg-surface/80 p-4 transition-all hover:-translate-y-0.5',
        bad ? 'border-error/40 hover:shadow-[0_8px_24px_-8px_var(--color-error)]' : 'border-border hover:border-border-focus hover:shadow-[0_8px_24px_-8px_rgba(59,123,232,0.25)]',
      )}
    >
      <div className="flex items-start justify-between">
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-wider text-text-muted">{label}</div>
          <div className={cn('mt-1.5 text-2xl font-bold tracking-tight', bad ? 'text-error-text' : 'text-text-primary')}>
            {value}
          </div>
          {hint && <div className="mt-1 text-xs text-text-muted">{hint}</div>}
        </div>
        {Icon && (
          <div
            className={cn(
              'flex size-8 shrink-0 items-center justify-center rounded-lg',
              bad ? 'bg-error/10 text-error' : 'bg-accent-glow text-accent-bright',
            )}
          >
            <Icon className="size-4" />
          </div>
        )}
      </div>
    </div>
  )
}

export function KpiRow({ children }: { children: ReactNode }) {
  return <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">{children}</div>
}
