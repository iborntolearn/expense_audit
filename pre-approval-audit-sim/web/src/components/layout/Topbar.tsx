import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useLocation } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ChevronDown, Globe } from 'lucide-react'
import { adminConfigApi } from '../../lib/api'
import { useAuth } from '../../lib/auth'
import { cn } from '../../lib/utils'
import { NAV_GROUPS } from './nav'

function findNavItem(pathname: string) {
  for (const group of NAV_GROUPS) {
    for (const item of group.items) {
      if (item.path === pathname) return { item, group }
      if (item.path !== '/' && pathname.startsWith(item.path)) return { item, group }
    }
  }
  return null
}

// Custom dropdown, not a native <select> - a native select's open popup is
// OS-native chrome that browsers often render with the OS's default light
// theme regardless of the page's own dark styling/color-scheme hints, so a
// plain self-rendered option list is the only way to guarantee it matches
// the app's dark theme in every browser (see components/ui/Input.tsx's
// Select for the same fix applied to every other dropdown in the app). The
// panel is portal-rendered into document.body rather than absolutely
// positioned inline - this header's own `backdrop-blur-md` creates a CSS
// stacking context that traps a plain `absolute` + `z-*` popup behind later
// page content no matter how high the z-index is set; only a portal escapes
// that.
function OeScopeSwitcher({
  value, options, onChange,
}: {
  value: string | null
  options: string[]
  onChange: (v: string | null) => void
}) {
  const [open, setOpen] = useState(false)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const panelRef = useRef<HTMLDivElement>(null)
  const [pos, setPos] = useState<{ top: number; right: number } | null>(null)

  useLayoutEffect(() => {
    if (!open || !triggerRef.current) {
      setPos(null)
      return
    }
    function update() {
      const r = triggerRef.current!.getBoundingClientRect()
      setPos({ top: r.bottom + 6, right: window.innerWidth - r.right })
    }
    update()
    window.addEventListener('scroll', update, true)
    window.addEventListener('resize', update)
    return () => {
      window.removeEventListener('scroll', update, true)
      window.removeEventListener('resize', update)
    }
  }, [open])

  useEffect(() => {
    if (!open) return
    function onDocPointerDown(e: MouseEvent) {
      const target = e.target as Node
      if (triggerRef.current?.contains(target) || panelRef.current?.contains(target)) return
      setOpen(false)
    }
    document.addEventListener('mousedown', onDocPointerDown)
    return () => document.removeEventListener('mousedown', onDocPointerDown)
  }, [open])

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-2 rounded-lg border border-border bg-bg-elevated px-2.5 py-1.5 text-xs font-medium text-text-primary transition-colors focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/25"
      >
        <Globe className="size-3.5 text-text-muted" />
        {value ?? 'All OEs'}
        <ChevronDown className={cn('size-3 text-text-muted transition-transform', open && 'rotate-180')} />
      </button>
      {open && pos && createPortal(
        <div
          ref={panelRef}
          role="listbox"
          style={{ position: 'fixed', top: pos.top, right: pos.right, zIndex: 9999 }}
          className="w-32 overflow-auto rounded-lg border border-border bg-bg-elevated py-1 shadow-popover"
        >
          {[{ code: null, label: 'All OEs' }, ...options.map((code) => ({ code, label: code }))].map((o) => (
            <button
              key={o.label}
              type="button"
              role="option"
              aria-selected={o.code === value}
              onClick={() => {
                onChange(o.code)
                setOpen(false)
              }}
              className={cn(
                'flex w-full items-center px-3 py-1.5 text-left text-xs transition-colors',
                o.code === value ? 'bg-bg-hover text-accent-bright' : 'text-text-primary hover:bg-bg-hover',
              )}
            >
              {o.label}
            </button>
          ))}
        </div>,
        document.body,
      )}
    </>
  )
}

export function Topbar() {
  const location = useLocation()
  const match = findNavItem(location.pathname)
  const { hasRole, user, oeScope, setOeScope } = useAuth()

  // Only a global admin (oe_code=null) can switch which OE they're viewing -
  // a tenant-scoped user is always confined to their own OE server-side
  // regardless of this control, so it isn't shown to them at all.
  const isGlobalAdmin = hasRole('admin') && user?.oe_code == null
  const { data: genCfg } = useQuery({
    queryKey: ['admin-config', 'generator', 'topbar-oe-switcher'],
    queryFn: () => adminConfigApi.getGenerator() as Promise<{ oe_codes: string[] }>,
    enabled: isGlobalAdmin,
  })

  return (
    <header className="sticky top-0 z-30 flex h-16 items-center justify-between border-b border-border bg-bg-base/80 px-6 backdrop-blur-md">
      <div>
        {match && (
          <div className="mb-0.5 text-[11px] font-medium uppercase tracking-wider text-text-muted">
            {match.group.label}
          </div>
        )}
        <h1 className="text-lg font-bold tracking-tight text-text-primary">
          {match?.item.label ?? 'Veriflow'}
        </h1>
      </div>
      {isGlobalAdmin && genCfg && (
        <OeScopeSwitcher value={oeScope} options={genCfg.oe_codes} onChange={setOeScope} />
      )}
    </header>
  )
}
