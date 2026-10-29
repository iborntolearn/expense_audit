import { useState, type ReactNode } from 'react'
import { cn } from '../../lib/utils'

export interface TabDef {
  key: string
  label: string
  icon?: ReactNode
  content: ReactNode
}

export function Tabs({ tabs, defaultKey }: { tabs: TabDef[]; defaultKey?: string }) {
  const [active, setActive] = useState(defaultKey ?? tabs[0]?.key)
  const activeTab = tabs.find((t) => t.key === active) ?? tabs[0]

  return (
    <div>
      <div className="flex gap-1 overflow-x-auto border-b border-border px-1">
        {tabs.map((t) => (
          <button
            key={t.key}
            onClick={() => setActive(t.key)}
            className={cn(
              'relative flex items-center gap-1.5 whitespace-nowrap px-3.5 py-2.5 text-sm font-medium transition-colors',
              active === t.key ? 'text-accent-bright' : 'text-text-muted hover:text-text-secondary',
            )}
          >
            {t.icon}
            {t.label}
            {active === t.key && (
              <span className="absolute inset-x-0 -bottom-px h-0.5 rounded-full bg-accent" />
            )}
          </button>
        ))}
      </div>
      <div className="pt-4 animate-in">{activeTab?.content}</div>
    </div>
  )
}
