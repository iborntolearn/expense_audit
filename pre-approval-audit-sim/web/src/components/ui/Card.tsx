import type { HTMLAttributes, ReactNode } from 'react'
import { cn } from '../../lib/utils'

export function Card({ className, children, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        'rounded-xl border border-border bg-bg-surface/80 backdrop-blur-sm shadow-[0_4px_24px_-4px_rgba(0,0,0,0.35),0_0_0_1px_rgba(255,255,255,0.03)]',
        className,
      )}
      {...props}
    >
      {children}
    </div>
  )
}

export function CardHeader({
  title,
  subtitle,
  action,
  className,
}: {
  title: ReactNode
  subtitle?: ReactNode
  action?: ReactNode
  className?: string
}) {
  return (
    <div className={cn('flex items-start justify-between gap-3 px-5 pt-4 pb-3', className)}>
      <div>
        <h3 className="text-sm font-semibold text-text-primary tracking-tight">{title}</h3>
        {subtitle && <p className="mt-0.5 text-xs text-text-muted">{subtitle}</p>}
      </div>
      {action}
    </div>
  )
}

export function CardBody({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={cn('px-5 pb-5', className)}>{children}</div>
}

export function SectionLabel({ children }: { children: ReactNode }) {
  return (
    <div className="mb-2 mt-1 text-[11px] font-semibold uppercase tracking-[0.08em] text-text-muted">
      {children}
    </div>
  )
}
