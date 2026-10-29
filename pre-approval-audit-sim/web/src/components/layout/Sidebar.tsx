import { NavLink } from 'react-router-dom'
import { ChevronsLeft, ChevronsRight, LogOut, ShieldCheck } from 'lucide-react'
import { useState } from 'react'
import { NAV_GROUPS } from './nav'
import { useAuth } from '../../lib/auth'
import { RoleBadge } from '../ui/Badge'
import { cn, initials } from '../../lib/utils'

export function Sidebar() {
  const { user, logout } = useAuth()
  const [collapsed, setCollapsed] = useState(false)

  if (!user) return null

  return (
    <aside
      className={cn(
        'sticky top-0 flex h-screen shrink-0 flex-col border-r border-border bg-bg-surface/95 backdrop-blur transition-[width] duration-200',
        collapsed ? 'w-[68px]' : 'w-64',
      )}
    >
      {/* Brand */}
      <div className="flex h-16 items-center gap-2.5 border-b border-border px-4">
        <div className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-accent to-purple text-white shadow-[0_0_0_1px_rgba(255,255,255,0.08)]">
          <ShieldCheck className="size-4.5" />
        </div>
        {!collapsed && (
          <div className="min-w-0 animate-in">
            <div className="truncate text-[13px] font-bold leading-tight text-text-primary">
              Veriflow
            </div>
            <div className="truncate text-[10px] font-medium uppercase tracking-wider text-text-muted">
              Agentic Pre-Approval Audit
            </div>
          </div>
        )}
      </div>

      {/* Nav groups */}
      <nav className="flex-1 space-y-5 overflow-y-auto px-3 py-4">
        {NAV_GROUPS.map((group) => {
          const visible = group.items.filter((item) => item.roles.includes(user.role))
          if (!visible.length) return null
          return (
            <div key={group.label}>
              {!collapsed && (
                <div className="mb-1.5 px-2.5 text-[10px] font-semibold uppercase tracking-[0.1em] text-text-faint">
                  {group.label}
                </div>
              )}
              <div className="space-y-0.5">
                {visible.map((item) => (
                  <NavLink
                    key={item.key}
                    to={item.path}
                    end={item.path === '/'}
                    title={collapsed ? item.label : undefined}
                    className={({ isActive }) =>
                      cn(
                        'group relative flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm font-medium transition-colors',
                        isActive
                          ? 'bg-accent-glow text-accent-bright'
                          : 'text-text-secondary hover:bg-bg-elevated hover:text-text-primary',
                      )
                    }
                  >
                    {({ isActive }) => (
                      <>
                        {isActive && (
                          <span className="absolute left-0 top-1.5 bottom-1.5 w-0.5 rounded-full bg-accent" />
                        )}
                        <item.icon className="size-4 shrink-0" />
                        {!collapsed && <span className="truncate">{item.label}</span>}
                      </>
                    )}
                  </NavLink>
                ))}
              </div>
            </div>
          )
        })}
      </nav>

      {/* Collapse toggle */}
      <button
        onClick={() => setCollapsed((c) => !c)}
        className="mx-3 mb-2 flex items-center justify-center gap-2 rounded-lg border border-border py-1.5 text-xs text-text-muted transition-colors hover:bg-bg-elevated hover:text-text-secondary"
      >
        {collapsed ? <ChevronsRight className="size-3.5" /> : <ChevronsLeft className="size-3.5" />}
      </button>

      {/* Profile footer */}
      <div className="border-t border-border p-3">
        <div className={cn('flex items-center gap-2.5 rounded-lg p-1.5', !collapsed && 'hover:bg-bg-elevated')}>
          <div className="flex size-8 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-purple to-accent text-xs font-bold text-white">
            {initials(user.display_name || user.username)}
          </div>
          {!collapsed && (
            <div className="min-w-0 flex-1 animate-in">
              <div className="truncate text-[13px] font-semibold text-text-primary">{user.display_name}</div>
              <RoleBadge role={user.role} />
            </div>
          )}
          {!collapsed && (
            <button
              onClick={logout}
              title="Log out"
              className="shrink-0 rounded-lg p-1.5 text-text-muted transition-colors hover:bg-bg-overlay hover:text-error-text"
            >
              <LogOut className="size-4" />
            </button>
          )}
        </div>
        {collapsed && (
          <button
            onClick={logout}
            title="Log out"
            className="mt-1.5 flex w-full items-center justify-center rounded-lg p-1.5 text-text-muted transition-colors hover:bg-bg-overlay hover:text-error-text"
          >
            <LogOut className="size-4" />
          </button>
        )}
      </div>
    </aside>
  )
}
