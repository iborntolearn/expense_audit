import { useEffect, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { X } from 'lucide-react'
import { cn } from '../../lib/utils'

export function Sheet({
  open,
  onClose,
  title,
  subtitle,
  children,
  width = 'max-w-3xl',
}: {
  open: boolean
  onClose: () => void
  title: ReactNode
  subtitle?: ReactNode
  children: ReactNode
  width?: string
}) {
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    document.body.style.overflow = 'hidden'
    return () => {
      window.removeEventListener('keydown', onKey)
      document.body.style.overflow = ''
    }
  }, [open, onClose])

  if (!open) return null

  // Portalled to document.body: a `fixed` element takes its containing block
  // from the nearest ancestor with a `transform` (even a resting
  // translateY(0) from a page's `.animate-in` entrance animation), not just
  // the viewport. Rendered in-place, the sheet would size itself against
  // that ancestor's content height instead of the viewport - on a page with
  // enough rows to make the content taller than the viewport, `h-full`
  // resolves to that inflated height and the sheet stops fitting the
  // screen, orphaning content below the fold with no way to scroll to it.
  return createPortal(
    <div className="fixed inset-0 z-50 flex justify-end">
      <div
        className="absolute inset-0 bg-black/60 backdrop-blur-sm animate-in"
        onClick={onClose}
        style={{ animationDuration: '0.2s' }}
      />
      <div
        className={cn(
          'relative flex h-full w-full flex-col border-l border-border bg-bg-surface shadow-[0_12px_40px_-8px_rgba(0,0,0,0.5),0_0_0_1px_rgba(255,255,255,0.04)] animate-in',
          width,
        )}
        style={{ animationDuration: '0.25s' }}
      >
        <div className="flex items-start justify-between gap-3 border-b border-border px-6 py-4">
          <div>
            <h2 className="text-base font-semibold text-text-primary tracking-tight">{title}</h2>
            {subtitle && <p className="mt-0.5 text-xs text-text-muted">{subtitle}</p>}
          </div>
          <button
            onClick={onClose}
            className="rounded-lg p-1.5 text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-primary"
          >
            <X className="size-4" />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto px-6 py-5">{children}</div>
      </div>
    </div>,
    document.body,
  )
}
