import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { CloudUpload, Repeat } from 'lucide-react'
import { ApiError, adminDevtoolsApi, webhooksApi, type IngestResult, type SubmissionEvent } from '../../lib/api'
import { useToast } from '../../lib/toast'
import { Card, CardHeader, CardBody } from '../ui/Card'
import { Table, Thead, Tbody, Tr, Th, Td } from '../ui/Table'
import { Badge } from '../ui/Badge'
import { Input, Select } from '../ui/Input'
import { Button } from '../ui/Button'

interface WebhookRow extends IngestResult {
  ok: boolean
  detail?: string
}

async function postBatch(events: SubmissionEvent[], onProgress: (rows: WebhookRow[]) => void): Promise<WebhookRow[]> {
  const rows: WebhookRow[] = []
  for (const event of events) {
    try {
      const result = await webhooksApi.submissionCreated(event)
      rows.push({ ...result, ok: true })
    } catch (e) {
      const err = e as ApiError
      rows.push({
        submission_id: event.submission_id,
        accepted: false,
        reason: 'error',
        routing_decision: null,
        ok: false,
        detail: err.message,
      })
    }
    onProgress([...rows])
  }
  return rows
}

export function ConcurWebhookTab() {
  const { push } = useToast()
  const [sampleSize, setSampleSize] = useState(5)
  const [events, setEvents] = useState<SubmissionEvent[]>([])
  const [rows, setRows] = useState<WebhookRow[]>([])
  const [inspect, setInspect] = useState<string>('')

  const go = useMutation({
    mutationFn: async () => {
      setRows([])
      const { events: generated } = await adminDevtoolsApi.generateSyntheticEvents(sampleSize)
      setEvents(generated)
      const results = await postBatch(generated, setRows)
      return results
    },
    onSuccess: (results) => {
      const okCount = results.filter((r) => r.ok).length
      if (okCount === results.length) push('success', `${okCount} submission(s) sent to the live webhook and audited.`)
      else push('error', `${results.length - okCount} of ${results.length} webhook call(s) failed.`)
    },
    onError: (e: any) => push('error', e.message ?? 'Batch failed'),
  })

  const resend = useMutation({
    mutationFn: () => postBatch(events, setRows),
    onSuccess: (results) => {
      const dup = results.filter((r) => r.ok && r.reason === 'already_processed').length
      push('info', `${dup} of ${results.length} re-delivered submission(s) were correctly no-op'd (already_processed) — idempotency holds.`)
    },
    onError: (e: any) => push('error', e.message ?? 'Resend failed'),
  })

  const inspected = events.find((e) => e.submission_id === (inspect || events[0]?.submission_id))

  return (
    <div className="space-y-5">
      <Card>
        <CardHeader
          title="Concur simulator — webhook"
          subtitle="Generates synthetic submissions and POSTs each one over HTTP to this service's own /webhooks/submission-created endpoint — the same route a live Concur connector would call (Tech Design §2.1)."
        />
        <CardBody className="space-y-4 pt-0">
          <div className="flex flex-wrap items-end gap-3">
            <Input
              label="Sample size"
              type="number"
              min={1}
              max={50}
              step={1}
              value={sampleSize}
              onChange={(e) => setSampleSize(Number(e.target.value))}
              className="w-32"
            />
            <Button variant="primary" onClick={() => go.mutate()} loading={go.isPending} disabled={sampleSize < 1}>
              <CloudUpload className="size-4" /> Generate & POST
            </Button>
            {events.length > 0 && (
              <Button variant="secondary" onClick={() => resend.mutate()} loading={resend.isPending}>
                <Repeat className="size-4" /> Resend last batch (idempotency check)
              </Button>
            )}
          </div>

          {rows.length > 0 && (
            <Table>
              <Thead>
                <tr>
                  <Th>Submission</Th>
                  <Th>Accepted</Th>
                  <Th>Reason</Th>
                  <Th>Routing</Th>
                  <Th>Detail</Th>
                </tr>
              </Thead>
              <Tbody>
                {rows.map((r) => (
                  <Tr key={r.submission_id}>
                    <Td className="text-text-primary">{r.submission_id}</Td>
                    <Td>
                      <Badge kind={r.accepted ? 'success' : r.ok ? 'neutral' : 'error'}>
                        {r.accepted ? 'yes' : 'no'}
                      </Badge>
                    </Td>
                    <Td>{r.reason}</Td>
                    <Td>{r.routing_decision ?? '—'}</Td>
                    <Td className="max-w-xs truncate text-text-muted">{r.detail ?? ''}</Td>
                  </Tr>
                ))}
              </Tbody>
            </Table>
          )}
        </CardBody>
      </Card>

      {events.length > 0 && (
        <Card>
          <CardHeader
            title="Inspect a webhook payload"
            subtitle="The exact JSON body POSTed to /webhooks/submission-created for the selected submission — the same payload a live Concur connector would send."
          />
          <CardBody className="space-y-3 pt-0">
            <Select value={inspect || events[0]?.submission_id} onChange={(e) => setInspect(e.target.value)} className="w-64">
              {events.map((e) => (
                <option key={e.submission_id} value={e.submission_id}>
                  {e.submission_id}
                </option>
              ))}
            </Select>
            {inspected && (
              <pre className="max-h-96 overflow-auto rounded-lg border border-border bg-bg-elevated p-3 text-xs text-text-secondary">
                {JSON.stringify(inspected, null, 2)}
              </pre>
            )}
          </CardBody>
        </Card>
      )}
    </div>
  )
}
