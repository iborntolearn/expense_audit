import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Send, Sparkles } from 'lucide-react'
import {
  adminConfigApi,
  adminDevtoolsApi,
  webhooksApi,
  type IngestResult,
  type ItemizedEntry,
  type SubmissionEvent,
} from '../../lib/api'
import { useToast } from '../../lib/toast'
import { Card, CardHeader, CardBody } from '../ui/Card'
import { Table, Thead, Tbody, Tr, Th, Td } from '../ui/Table'
import { Input, Select } from '../ui/Input'
import { Button } from '../ui/Button'
import { Badge } from '../ui/Badge'
import { Skeleton } from '../ui/Skeleton'

const SOURCE_SYSTEMS = [
  { value: 'concur', label: 'Concur' },
  { value: 'simulation_harness', label: 'Internal harness' },
]

function freshSubmissionId(prefix: string) {
  return `SUB-${prefix}-${Math.random().toString(16).slice(2, 10).toUpperCase()}`
}

interface GeneratorConfig {
  oe_codes: string[]
  currency_mix: string[]
  categories: string[]
}

export function CustomSubmissionTab() {
  const { data: genCfg, isLoading } = useQuery({
    queryKey: ['admin-config', 'generator', 'custom-submission'],
    queryFn: () => adminConfigApi.getGenerator() as Promise<GeneratorConfig>,
  })
  const [mode, setMode] = useState<'auto' | 'manual'>('auto')

  if (isLoading || !genCfg) return <Skeleton className="h-64 rounded-xl" />

  return (
    <div className="space-y-5">
      <Card>
        <CardHeader
          title="Concur simulator — custom submission"
          subtitle="Hand-build ONE submission-created payload and send it to the same webhook — useful to see exactly what data triggers an audit and to try it with your own receipt."
        />
        <CardBody className="space-y-4 pt-0">
          <div className="flex gap-2">
            <Button variant={mode === 'auto' ? 'primary' : 'secondary'} size="sm" onClick={() => setMode('auto')}>
              Auto-detect — AI itemizes the invoice
            </Button>
            <Button variant={mode === 'manual' ? 'primary' : 'secondary'} size="sm" onClick={() => setMode('manual')}>
              Manual — I specify category & amount
            </Button>
          </div>
        </CardBody>
      </Card>

      {mode === 'manual' ? <ManualSubmission genCfg={genCfg} /> : <AutoDetectSubmission genCfg={genCfg} />}
    </div>
  )
}

function ResultBanner({ result, sid }: { result: IngestResult; sid: string }) {
  return (
    <div
      className={
        result.accepted
          ? 'rounded-lg border border-success-border bg-success-bg px-3 py-2 text-sm text-success-text'
          : 'rounded-lg border border-warning-border bg-warning-bg px-3 py-2 text-sm text-warning-text'
      }
    >
      Sent. accepted=<Badge kind={result.accepted ? 'success' : 'warning'}>{String(result.accepted)}</Badge>{' '}
      reason={result.reason} · routing={result.routing_decision ?? '—'}. Look it up in <b>Expense reports</b> as{' '}
      <code>{sid}</code> (check "Pending review only" if it routed to human_review).
    </div>
  )
}

function ManualSubmission({ genCfg }: { genCfg: GeneratorConfig }) {
  const { push } = useToast()
  const [sid, setSid] = useState(() => freshSubmissionId('CUSTOM'))
  const [oe, setOe] = useState(genCfg.oe_codes[0] ?? '')
  const [currency, setCurrency] = useState(genCfg.currency_mix[0] ?? '')
  const [employee, setEmployee] = useState('EMP-DEMO')
  const [costCenter, setCostCenter] = useState('')
  const [source, setSource] = useState('concur')
  const [category, setCategory] = useState(genCfg.categories[0] ?? 'misc')
  const [amount, setAmount] = useState(25)
  const [file, setFile] = useState<File | null>(null)
  const [simAuthenticity, setSimAuthenticity] = useState(false)
  const [result, setResult] = useState<IngestResult | null>(null)

  const send = useMutation({
    mutationFn: async () => {
      if (!file) throw new Error('Attach a receipt file before sending.')
      const { key, receipt_url } = await adminDevtoolsApi.uploadReceipt(file, sid, 'manual')
      if (simAuthenticity) await adminDevtoolsApi.simulateAuthenticity(key)
      const event: SubmissionEvent = {
        event_type: 'submission.created',
        submission_id: sid,
        source_system: source,
        source_system_ref: `MANUAL-${sid}`,
        oe_code: oe,
        employee_id: employee,
        cost_center: costCenter || null,
        currency,
        submitted_at: new Date().toISOString(),
        report_lines: [{ line_id: 'LN-1', category, entered_amount: amount, receipt_url }],
      }
      const ingestResult = await webhooksApi.submissionCreated(event)
      return { ingestResult }
    },
    onSuccess: ({ ingestResult }) => {
      setResult(ingestResult)
      if (ingestResult.accepted) setSid(freshSubmissionId('CUSTOM'))
      push(ingestResult.accepted ? 'success' : 'info', `HTTP 200 · accepted=${ingestResult.accepted} · reason=${ingestResult.reason} · routing=${ingestResult.routing_decision ?? '—'}`)
    },
    onError: (e: any) => push('error', e.message ?? 'Send failed'),
  })

  return (
    <Card>
      <CardBody className="space-y-4">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <Input label="Submission ID" value={sid} onChange={(e) => setSid(e.target.value)} />
          <Select label="OE code" value={oe} onChange={(e) => setOe(e.target.value)}>
            {genCfg.oe_codes.map((c) => (
              <option key={c} value={c}>{c}</option>
            ))}
          </Select>
          <Select label="Currency" value={currency} onChange={(e) => setCurrency(e.target.value)}>
            {genCfg.currency_mix.map((c) => (
              <option key={c} value={c}>{c}</option>
            ))}
          </Select>
        </div>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <Input label="Employee ID" value={employee} onChange={(e) => setEmployee(e.target.value)} />
          <Input label="Cost center" value={costCenter} onChange={(e) => setCostCenter(e.target.value)} />
          <Select
            label="Source system"
            value={source}
            onChange={(e) => setSource(e.target.value)}
            hint="'concur' labels this as if a real Concur webhook sent it."
          >
            {SOURCE_SYSTEMS.map((s) => (
              <option key={s.value} value={s.value}>{s.label}</option>
            ))}
          </Select>
        </div>

        <div className="border-t border-border pt-3">
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-text-secondary">
            Line item <span className="font-normal normal-case text-text-muted">(this quick-build form supports one line — see Auto-detect mode for a multi-charge invoice)</span>
          </p>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <Select label="Category" value={category} onChange={(e) => setCategory(e.target.value)}>
              {genCfg.categories.map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </Select>
            <Input
              label="Entered amount"
              type="number"
              min={0}
              step={1}
              value={amount}
              onChange={(e) => setAmount(Number(e.target.value))}
            />
          </div>
          <Input
            label="Receipt (image or PDF)"
            type="file"
            accept=".png,.jpg,.jpeg,.pdf"
            className="mt-3"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
        </div>

        <div className="border-t border-border pt-3">
          <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-text-secondary">Testing helpers (optional)</p>
          <p className="mb-2 text-xs text-text-muted">
            The authenticity check reads a hidden metadata sidecar the synthetic generator writes — a plain uploaded
            file has none, so it can never trip that check on its own. Check this to attach one for testing.
          </p>
          <label className="flex items-center gap-2 text-sm text-text-secondary">
            <input
              type="checkbox"
              checked={simAuthenticity}
              onChange={(e) => setSimAuthenticity(e.target.checked)}
              className="size-4 rounded border-border accent-accent"
            />
            Simulate AI-generated / tampered receipt (forces an authenticity flag)
          </label>
        </div>

        <details className="rounded-lg border border-border">
          <summary className="cursor-pointer px-3 py-2 text-xs font-medium text-text-muted">
            Preview payload
          </summary>
          <pre className="max-h-64 overflow-auto border-t border-border p-3 text-xs text-text-secondary">
            {JSON.stringify(
              {
                event_type: 'submission.created',
                submission_id: sid,
                source_system: source,
                source_system_ref: `MANUAL-${sid}`,
                oe_code: oe,
                employee_id: employee,
                cost_center: costCenter || null,
                currency,
                submitted_at: '<assigned on send>',
                report_lines: [{ line_id: 'LN-1', category, entered_amount: amount, receipt_url: file?.name ?? '<upload a receipt>' }],
              },
              null,
              2,
            )}
          </pre>
        </details>

        <Button variant="primary" onClick={() => send.mutate()} loading={send.isPending} disabled={!file}>
          <Send className="size-4" /> Send to webhook
        </Button>

        {result && <ResultBanner result={result} sid={sid} />}
      </CardBody>
    </Card>
  )
}

function AutoDetectSubmission({ genCfg }: { genCfg: GeneratorConfig }) {
  const { push } = useToast()
  const [sid, setSid] = useState(() => freshSubmissionId('AUTO'))
  const [oe, setOe] = useState(genCfg.oe_codes[0] ?? '')
  const [currency, setCurrency] = useState(genCfg.currency_mix[0] ?? '')
  const [employee, setEmployee] = useState('EMP-DEMO')
  const [costCenter, setCostCenter] = useState('')
  const [source, setSource] = useState('concur')
  const [file, setFile] = useState<File | null>(null)
  const [simAuthenticity, setSimAuthenticity] = useState(false)
  const [detected, setDetected] = useState<ItemizedEntry[] | null>(null)
  const [receiptKey, setReceiptKey] = useState<string | null>(null)
  const [receiptUrl, setReceiptUrl] = useState<string | null>(null)
  const [result, setResult] = useState<IngestResult | null>(null)

  const detect = useMutation({
    mutationFn: async () => {
      if (!file) throw new Error('Attach an invoice before detecting.')
      const { key, receipt_url } = await adminDevtoolsApi.uploadReceipt(file, sid, 'auto')
      const { items } = await adminDevtoolsApi.autoDetect(key, currency)
      return { key, receipt_url, items }
    },
    onSuccess: ({ key, receipt_url, items }) => {
      setReceiptKey(key)
      setReceiptUrl(receipt_url)
      setDetected(items)
      push('success', `Detected ${items.length} line item(s) — review/correct below before sending.`)
    },
    onError: (e: any) => {
      setDetected(null)
      push('error', e.message ?? 'Could not read line items from this file.')
    },
  })

  const updateItem = (idx: number, patch: Partial<ItemizedEntry>) => {
    setDetected((prev) => (prev ? prev.map((it, i) => (i === idx ? { ...it, ...patch } : it)) : prev))
  }

  const send = useMutation({
    mutationFn: async () => {
      if (!detected || !receiptKey || !receiptUrl) throw new Error('Detect line items first.')
      const valid = detected.filter((it) => it.amount !== null && it.amount !== undefined)
      if (simAuthenticity) await adminDevtoolsApi.simulateAuthenticity(receiptKey)
      await adminDevtoolsApi.saveItemization(receiptKey, valid)
      const reportLines = valid.map((it, i) => ({
        line_id: `LN-${i + 1}`,
        category: it.category,
        entered_amount: Number(it.amount),
        receipt_url: receiptUrl,
      }))
      const event: SubmissionEvent = {
        event_type: 'submission.created',
        submission_id: sid,
        source_system: source,
        source_system_ref: `MANUAL-${sid}`,
        oe_code: oe,
        employee_id: employee,
        cost_center: costCenter || null,
        currency,
        submitted_at: new Date().toISOString(),
        report_lines: reportLines,
      }
      const ingestResult = await webhooksApi.submissionCreated(event)
      return { ingestResult, lineCount: reportLines.length }
    },
    onSuccess: ({ ingestResult, lineCount }) => {
      setResult(ingestResult)
      if (ingestResult.accepted) {
        setSid(freshSubmissionId('AUTO'))
        setDetected(null)
        setReceiptKey(null)
        setReceiptUrl(null)
        setFile(null)
      }
      push(
        ingestResult.accepted ? 'success' : 'info',
        `HTTP 200 · accepted=${ingestResult.accepted} · reason=${ingestResult.reason} · routing=${ingestResult.routing_decision ?? '—'} · ${lineCount} line(s) detected.`,
      )
    },
    onError: (e: any) => push('error', e.message ?? 'Send failed'),
  })

  return (
    <Card>
      <CardBody className="space-y-4">
        <p className="text-xs text-text-muted">
          Upload one real invoice — even if it lists several charges (airfare, hotel, meals, ...) on a single page —
          and the vision model will split it into separate categorized line items, then run each one through policy,
          verification, and risk scoring exactly like a manually-built submission.
        </p>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <Input label="Submission ID" value={sid} onChange={(e) => setSid(e.target.value)} />
          <Select label="OE code" value={oe} onChange={(e) => setOe(e.target.value)}>
            {genCfg.oe_codes.map((c) => (
              <option key={c} value={c}>{c}</option>
            ))}
          </Select>
          <Select label="Currency" value={currency} onChange={(e) => setCurrency(e.target.value)}>
            {genCfg.currency_mix.map((c) => (
              <option key={c} value={c}>{c}</option>
            ))}
          </Select>
        </div>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <Input label="Employee ID" value={employee} onChange={(e) => setEmployee(e.target.value)} />
          <Input label="Cost center" value={costCenter} onChange={(e) => setCostCenter(e.target.value)} />
          <Select
            label="Source system"
            value={source}
            onChange={(e) => setSource(e.target.value)}
            hint="'concur' labels this as if a real Concur webhook sent it."
          >
            {SOURCE_SYSTEMS.map((s) => (
              <option key={s.value} value={s.value}>{s.label}</option>
            ))}
          </Select>
        </div>

        <Input
          label="Invoice (image or PDF) — may contain multiple charges"
          type="file"
          accept=".png,.jpg,.jpeg,.pdf"
          onChange={(e) => {
            setFile(e.target.files?.[0] ?? null)
            setDetected(null)
          }}
        />

        <div>
          <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-text-secondary">Testing helpers (optional)</p>
          <label className="flex items-center gap-2 text-sm text-text-secondary">
            <input
              type="checkbox"
              checked={simAuthenticity}
              onChange={(e) => setSimAuthenticity(e.target.checked)}
              className="size-4 rounded border-border accent-accent"
            />
            Simulate AI-generated / tampered receipt (forces an authenticity flag)
          </label>
        </div>

        <Button variant="secondary" onClick={() => detect.mutate()} loading={detect.isPending} disabled={!file}>
          <Sparkles className="size-4" /> Detect line items
        </Button>

        {detected && detected.length > 0 && (
          <>
            <Table>
              <Thead>
                <tr>
                  <Th>Description</Th>
                  <Th>Category</Th>
                  <Th>Amount</Th>
                  <Th>Tax</Th>
                </tr>
              </Thead>
              <Tbody>
                {detected.map((item, idx) => (
                  <Tr key={idx}>
                    <Td className="text-text-primary">{item.description ?? '—'}</Td>
                    <Td>
                      <Select
                        value={item.category}
                        onChange={(e) => updateItem(idx, { category: e.target.value })}
                        className="!mb-0 w-36"
                      >
                        {genCfg.categories.map((c) => (
                          <option key={c} value={c}>{c}</option>
                        ))}
                      </Select>
                    </Td>
                    <Td>
                      <Input
                        type="number"
                        min={0}
                        step={0.01}
                        value={item.amount ?? ''}
                        onChange={(e) => updateItem(idx, { amount: e.target.value === '' ? null : Number(e.target.value) })}
                        className="!mb-0 w-28"
                      />
                    </Td>
                    <Td>
                      <Input
                        type="number"
                        min={0}
                        step={0.01}
                        value={item.tax ?? ''}
                        onChange={(e) => updateItem(idx, { tax: e.target.value === '' ? null : Number(e.target.value) })}
                        className="!mb-0 w-24"
                      />
                    </Td>
                  </Tr>
                ))}
              </Tbody>
            </Table>
            <p className="text-xs text-text-muted">
              Detected currency/vendor read: {detected[0]?.currency ?? currency} · {detected[0]?.vendor ?? '(unknown)'}
            </p>

            <Button variant="primary" onClick={() => send.mutate()} loading={send.isPending}>
              <Send className="size-4" /> Send to webhook
            </Button>
          </>
        )}

        {result && <ResultBanner result={result} sid={sid} />}
      </CardBody>
    </Card>
  )
}
