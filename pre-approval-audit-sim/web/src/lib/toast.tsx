import { createContext, useCallback, useContext, useState, type ReactNode } from 'react'
import { CheckCircle2, XCircle, Info, X } from 'lucide-react'
import { cn } from './utils'

type ToastKind = 'success' | 'error' | 'info'
interface Toast {
  id: number
  kind: ToastKind
  message: string
}

const ToastContext = createContext<{ push: (kind: ToastKind, message: string) => void } | null>(null)

let idCounter = 0

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])

  const push = useCallback((kind: ToastKind, message: string) => {
    const id = ++idCounter
    setToasts((prev) => [...prev, { id, kind, message }])
    setTimeout(() => setToasts((prev) => prev.filter((t) => t.id !== id)), 4500)
  }, [])

  const dismiss = (id: number) => setToasts((prev) => prev.filter((t) => t.id !== id))

  return (
    <ToastContext.Provider value={{ push }}>
      {children}
      <div className="fixed bottom-4 right-4 z-[100] flex flex-col gap-2">
        {toasts.map((t) => (
          <ToastItem key={t.id} toast={t} onDismiss={() => dismiss(t.id)} />
        ))}
      </div>
    </ToastContext.Provider>
  )
}

const ICONS: Record<ToastKind, typeof CheckCircle2> = { success: CheckCircle2, error: XCircle, info: Info }
const STYLES: Record<ToastKind, string> = {
  success: 'border-success-border bg-success-bg text-success-text',
  error: 'border-error-border bg-error-bg text-error-text',
  info: 'border-info-border bg-info-bg text-info-text',
}

function ToastItem({ toast, onDismiss }: { toast: Toast; onDismiss: () => void }) {
  const Icon = ICONS[toast.kind]
  return (
    <div
      className={cn(
        'animate-in flex w-80 items-start gap-2.5 rounded-lg border px-4 py-3 text-sm shadow-[0_12px_40px_-8px_rgba(0,0,0,0.5)]',
        STYLES[toast.kind],
      )}
    >
      <Icon className="mt-0.5 size-4 shrink-0" />
      <div className="flex-1">{toast.message}</div>
      <button onClick={onDismiss} className="text-current/70 hover:text-current">
        <X className="size-3.5" />
      </button>
    </div>
  )
}

export function useToast() {
  const ctx = useContext(ToastContext)
  if (!ctx) throw new Error('useToast must be used within ToastProvider')
  return ctx
}
