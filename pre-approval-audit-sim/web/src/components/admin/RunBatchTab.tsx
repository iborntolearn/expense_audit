import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { PlayCircle } from 'lucide-react'
import { adminDevtoolsApi, type IngestResult } from '../../lib/api'
import { useToast } from '../../lib/toast'
import { Card, CardHeader, CardBody } from '../ui/Card'
import { Table, Thead, Tbody, Tr, Th, Td } from '../ui/Table'
import { Badge } from '../ui/Badge'
import { Input } from '../ui/Input'
import { Button } from '../ui/Button'

export function RunBatchTab() {
  const { push } = useToast()
  const [sampleSize, setSampleSize] = useState(20)
  const [results, setResults] = useState<IngestResult[]>([])
  const [progress, setProgress] = useState<{ done: number; total: number } | null>(null)
  const [seed, setSeed] = useState<number | null>(null)

  const run = useMutation({
    mutationFn: async () => {
      setResults([])
      setProgress(null)
      const { seed: runSeed, events } = await adminDevtoolsApi.generateSyntheticEvents(sampleSize)
      setSeed(runSeed)
      setProgress({ done: 0, total: events.length })
      const out: IngestResult[] = []
      for (const event of events) {
        const result = await adminDevtoolsApi.ingestEvent(event)
        out.push(result)
        setResults([...out])
        setProgress({ done: out.length, total: events.length })
      }
      return { runSeed, out }
    },
    onSuccess: ({ runSeed, out }) => {
      push('success', `Audited ${out.length} submission(s) (run seed ${runSeed}). Dashboards updated.`)
    },
    onError: (e: any) => push('error', e.message ?? 'Batch failed'),
  })

  return (
    <Card>
      <CardHeader
        title="Run audit batch"
        subtitle="Generates synthetic submissions and runs them directly through the pipeline in-process — bypasses HTTP. Keep the sample small for an interactive run."
      />
      <CardBody className="space-y-4 pt-0">
        <div className="flex flex-wrap items-end gap-3">
          <Input
            label="Sample size"
            type="number"
            min={5}
            max={100}
            step={5}
            value={sampleSize}
            onChange={(e) => setSampleSize(Number(e.target.value))}
            className="w-32"
          />
          <Button
            variant="primary"
            onClick={() => run.mutate()}
            loading={run.isPending}
            disabled={sampleSize < 1}
          >
            <PlayCircle className="size-4" /> Generate & audit
          </Button>
          {seed !== null && <span className="text-xs text-text-muted">last run seed: {seed}</span>}
        </div>

        {progress && (
          <div className="flex items-center gap-2 text-xs text-text-muted">
            <div className="h-1.5 w-48 overflow-hidden rounded-full bg-bg-elevated">
              <div
                className="h-full rounded-full bg-accent transition-all"
                style={{ width: `${(progress.done / Math.max(progress.total, 1)) * 100}%` }}
              />
            </div>
            {progress.done} / {progress.total} audited
          </div>
        )}

        {results.length > 0 && (
          <Table>
            <Thead>
              <tr>
                <Th>Submission</Th>
                <Th>Accepted</Th>
                <Th>Reason</Th>
                <Th>Routing</Th>
              </tr>
            </Thead>
            <Tbody>
              {results.map((r) => (
                <Tr key={r.submission_id}>
                  <Td className="text-text-primary">{r.submission_id}</Td>
                  <Td>
                    <Badge kind={r.accepted ? 'success' : 'error'}>{r.accepted ? 'yes' : 'no'}</Badge>
                  </Td>
                  <Td>{r.reason}</Td>
                  <Td>{r.routing_decision ?? '—'}</Td>
                </Tr>
              ))}
            </Tbody>
          </Table>
        )}
      </CardBody>
    </Card>
  )
}
