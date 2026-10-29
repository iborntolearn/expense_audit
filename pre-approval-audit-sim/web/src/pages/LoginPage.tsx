import { useState, type FormEvent } from 'react'
import { Navigate } from 'react-router-dom'
import { ShieldCheck, AlertCircle, ScanEye, FileSearch, ShieldAlert } from 'lucide-react'
import { useAuth } from '../lib/auth'
import { ApiError } from '../lib/api'
import { Input } from '../components/ui/Input'
import { Button } from '../components/ui/Button'
import { AiAuditIllustration } from '../components/illustrations/AiAuditIllustration'

const AI_HIGHLIGHTS = [
  {
    icon: FileSearch,
    title: 'Reads every receipt',
    body: 'Vision AI extracts line items, amounts, and merchant detail straight from the receipt image.',
  },
  {
    icon: ScanEye,
    title: 'Screens for authenticity',
    body: 'Metadata and image-forensics analysis flags edited documents and fabricated receipts before they slip through.',
  },
  {
    icon: ShieldAlert,
    title: 'Applies policy automatically',
    body: 'A rules-and-risk agent pipeline checks every submission against policy and routes only real exceptions to a reviewer.',
  },
]

export function LoginPage() {
  const { user, login } = useAuth()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  if (user) return <Navigate to="/" replace />

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      await login(username, password)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Login failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex h-screen overflow-hidden">
      {/* AI-showcase panel */}
      <div className="relative hidden w-1/2 flex-col justify-center overflow-hidden border-r border-border bg-bg-surface/40 px-12 lg:flex">
        <div className="animate-in">
          <div className="flex items-center justify-center">
            <AiAuditIllustration />
          </div>
          <h2 className="mt-3 text-xl font-bold tracking-tight text-text-primary">
            AI that audits every expense, before it's approved
          </h2>
          <p className="mt-2 max-w-md text-sm leading-relaxed text-text-muted">
            Veriflow's agent pipeline reads, verifies, and risk-scores 100% of submissions in
            seconds — so your team reviews only what actually needs a human.
          </p>
          <div className="mt-5 space-y-3">
            {AI_HIGHLIGHTS.map(({ icon: Icon, title, body }) => (
              <div key={title} className="flex items-start gap-3">
                <div className="mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-accent to-purple shadow-[0_8px_24px_-4px_var(--color-accent-glow)]">
                  <Icon className="size-4.5 text-white" />
                </div>
                <div>
                  <div className="text-sm font-semibold text-text-primary">{title}</div>
                  <div className="mt-0.5 text-xs leading-relaxed text-text-muted">{body}</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Login form panel */}
      <div className="flex w-full items-center justify-center overflow-hidden px-4 lg:w-1/2">
        <div className="w-full max-w-sm animate-in">
          <div className="mb-8 flex flex-col items-center text-center">
            <div className="mb-4 flex size-12 items-center justify-center rounded-2xl bg-gradient-to-br from-accent to-purple shadow-[0_8px_24px_-4px_var(--color-accent-glow)]">
              <ShieldCheck className="size-6 text-white" />
            </div>
            <h1 className="text-xl font-bold tracking-tight text-text-primary">Veriflow</h1>
            <p className="mt-1 text-sm text-text-muted">Agentic pre-approval audit platform</p>
          </div>

          <form
            onSubmit={onSubmit}
            className="rounded-2xl border border-border bg-bg-surface/80 p-6 shadow-[0_12px_40px_-8px_rgba(0,0,0,0.5)] backdrop-blur-sm"
          >
            <div className="space-y-4">
              <Input
                label="Username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoFocus
                autoComplete="username"
                required
              />
              <Input
                label="Password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
                required
              />
            </div>

            {error && (
              <div className="mt-4 flex items-start gap-2 rounded-lg border border-error-border bg-error-bg px-3 py-2 text-xs text-error-text">
                <AlertCircle className="mt-0.5 size-3.5 shrink-0" />
                {error}
              </div>
            )}

            <Button type="submit" variant="primary" size="lg" className="mt-5 w-full" loading={loading}>
              {loading ? 'Signing in…' : 'Sign in'}
            </Button>
          </form>

          <p className="mt-5 text-center text-xs text-text-faint">
            Local operator accounts · SSO/RBAC is a baseline integration seam in this build
          </p>
        </div>
      </div>
    </div>
  )
}
