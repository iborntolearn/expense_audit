import type { HTMLAttributes, ReactNode, TdHTMLAttributes, ThHTMLAttributes } from 'react'
import { cn } from '../../lib/utils'

export function Table({ className, ...props }: HTMLAttributes<HTMLTableElement>) {
  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table className={cn('w-full border-collapse text-sm', className)} {...props} />
    </div>
  )
}

export function Thead({ className, ...props }: HTMLAttributes<HTMLTableSectionElement>) {
  return <thead className={cn('bg-bg-elevated', className)} {...props} />
}

export function Tbody({ className, ...props }: HTMLAttributes<HTMLTableSectionElement>) {
  return <tbody className={cn('divide-y divide-border-subtle', className)} {...props} />
}

export function Tr({
  className,
  clickable,
  selected,
  ...props
}: HTMLAttributes<HTMLTableRowElement> & { clickable?: boolean; selected?: boolean }) {
  return (
    <tr
      className={cn(
        'transition-colors',
        clickable && 'cursor-pointer hover:bg-bg-hover/60',
        selected && 'bg-accent-glow',
        className,
      )}
      {...props}
    />
  )
}

export function Th({ className, ...props }: ThHTMLAttributes<HTMLTableCellElement>) {
  return (
    <th
      className={cn(
        'px-3.5 py-2.5 text-left text-[11px] font-semibold uppercase tracking-wider text-text-muted whitespace-nowrap',
        className,
      )}
      {...props}
    />
  )
}

export function Td({ className, ...props }: TdHTMLAttributes<HTMLTableCellElement>) {
  return <td className={cn('px-3.5 py-2.5 text-text-secondary', className)} {...props} />
}

export function EmptyState({ icon, title, hint }: { icon?: ReactNode; title: string; hint?: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-16 text-center">
      {icon && <div className="text-text-faint">{icon}</div>}
      <div className="text-sm font-medium text-text-secondary">{title}</div>
      {hint && <div className="max-w-sm text-xs text-text-muted">{hint}</div>}
    </div>
  )
}
