import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { RotateCcw, Save, AlertCircle } from 'lucide-react'
import { Button } from '../ui/Button'
import { Skeleton } from '../ui/Skeleton'
import { useToast } from '../../lib/toast'

interface Props {
  queryKey: string[]
  fetcher: () => Promise<Record<string, any>>
  saver: (data: Record<string, any>) => Promise<unknown>
  title: string
  subtitle?: string
}

/** Generic "advanced JSON" config editor - every write is validated server-side
 * against the matching pydantic model before it's persisted (config_admin.py's
 * own guarantee), so a syntactically-valid-but-semantically-wrong edit is
 * rejected with a clear error rather than silently corrupting the live config. */
export function JsonConfigEditor({ queryKey, fetcher, saver, title, subtitle }: Props) {
  const qc = useQueryClient()
  const { push } = useToast()
  const { data, isLoading } = useQuery({ queryKey, queryFn: fetcher })
  const [text, setText] = useState('')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (data) setText(JSON.stringify(data, null, 2))
  }, [data])

  const save = useMutation({
    mutationFn: () => {
      let parsed: Record<string, any>
      try {
        parsed = JSON.parse(text)
      } catch {
        throw new Error('Invalid JSON - fix syntax before saving')
      }
      return saver(parsed)
    },
    onSuccess: () => {
      setError(null)
      push('success', `${title} saved.`)
      qc.invalidateQueries({ queryKey })
    },
    onError: (e: any) => {
      setError(e.message ?? 'Save failed')
      push('error', e.message ?? 'Save failed')
    },
  })

  if (isLoading) return <Skeleton className="h-96 rounded-lg" />

  const dirty = data && text !== JSON.stringify(data, null, 2)

  return (
    <div className="space-y-3">
      {subtitle && <p className="text-xs text-text-muted">{subtitle}</p>}
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        spellCheck={false}
        rows={22}
        className="w-full rounded-lg border border-border bg-bg-elevated px-3 py-2 font-mono text-xs text-text-primary focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/25"
      />
      {error && (
        <div className="flex items-start gap-2 rounded-lg border border-error-border bg-error-bg px-3 py-2 text-xs text-error-text">
          <AlertCircle className="mt-0.5 size-3.5 shrink-0" />
          <pre className="whitespace-pre-wrap font-mono">{error}</pre>
        </div>
      )}
      <div className="flex gap-2">
        <Button variant="primary" size="sm" onClick={() => save.mutate()} loading={save.isPending} disabled={!dirty}>
          <Save className="size-3.5" /> Save
        </Button>
        <Button
          variant="secondary"
          size="sm"
          onClick={() => data && setText(JSON.stringify(data, null, 2))}
          disabled={!dirty}
        >
          <RotateCcw className="size-3.5" /> Reset
        </Button>
      </div>
    </div>
  )
}
