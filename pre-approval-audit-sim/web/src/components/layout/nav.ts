import type { LucideIcon } from 'lucide-react'
import {
  LayoutDashboard,
  ReceiptText,
  Users,
  Sparkles,
  FileBarChart2,
  SlidersHorizontal,
  ShieldCheck,
} from 'lucide-react'
import type { Role } from '../../lib/api'

export interface NavItem {
  key: string
  label: string
  path: string
  icon: LucideIcon
  roles: Role[]
}

export interface NavGroup {
  label: string
  items: NavItem[]
}

export const NAV_GROUPS: NavGroup[] = [
  {
    label: 'Overview',
    items: [
      { key: 'dashboard', label: 'Dashboard', path: '/', icon: LayoutDashboard, roles: ['admin', 'user', 'auditor'] },
    ],
  },
  {
    label: 'Audit',
    items: [
      {
        key: 'expenses',
        label: 'Expense Reports',
        path: '/expenses',
        icon: ReceiptText,
        roles: ['admin', 'user', 'auditor'],
      },
    ],
  },
  {
    label: 'Insights',
    items: [
      { key: 'analytics', label: 'User Analytics', path: '/analytics', icon: Users, roles: ['admin', 'user'] },
      { key: 'assistant', label: 'Ask AI', path: '/assistant', icon: Sparkles, roles: ['admin', 'user'] },
      {
        key: 'reports',
        label: 'Reports & Exports',
        path: '/reports',
        icon: FileBarChart2,
        roles: ['admin', 'user', 'auditor'],
      },
    ],
  },
  {
    label: 'Configuration',
    items: [
      { key: 'settings', label: 'Settings', path: '/settings', icon: SlidersHorizontal, roles: ['admin'] },
      { key: 'system-admin', label: 'System Admin', path: '/system-admin', icon: ShieldCheck, roles: ['admin'] },
    ],
  },
]
