import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Search,
  Filter,
  Check,
  X as XIcon,
  FileText,
  ShieldQuestion,
  ScrollText,
  Image as ImageIcon,
  Lightbulb,
  Workflow,
  Mail,
  FolderKanban,
} from 'lucide-react'
import {
  reportsApi,
  caseStatusApi,
  emailTemplatesApi,
  type ReportRow,
  type ReportDetail,
} from '../lib/api'
import { useAuth } from '../lib/auth'
import { useToast } from '../lib/toast'
import { Card, CardBody } from '../components/ui/Card'
import { Button } from '../components/ui/Button'
import { Input, Select } from '../components/ui/Input'
import { Table, Thead, Tbody, Tr, Th, Td, EmptyState } from '../components/ui/Table'
import { RiskBadge, StatusBadge, Badge } from '../components/ui/Badge'
import { Sheet } from '../components/ui/Sheet'
import { Tabs } from '../components/ui/Tabs'
import { SkeletonTable } from '../components/ui/Skeleton'
import { formatMoney, formatDate, cn } from '../lib/utils'
import { ReceiptViewer } from '../components/expenses/ReceiptViewer'
import { CaseManagementPanel } from '../components/expenses/CaseManagementPanel'

const STATUS_OPTIONS = ['', 'APPROVED', 'REJECTED', 'SUBMITTED']
const RISK_OPTIONS = ['', 'LOW', 'PENDING', 'HIGH']

export function ExpenseReportsPage() {
  const { hasRole, oeScope } = useAuth()
  const [employeeId, setEmployeeId] = useState('')
  const [submissionId, setSubmissionId] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [riskBand, setRiskBand] = useState('')
  const [pendingOnly, setPendingOnly] = useState(false)
  const [selected, setSelected] = useState<ReportRow | null>(null)

  const filters = useMemo(
    () => ({
      employee_id: employeeId || undefined,
      submission_id: submissionId || undefined,
      status_filter: statusFilter || undefined,
      risk_band: riskBand || undefined,
      pending_only: pendingOnly || undefined,
      oe_code: oeScope || undefined,
    }),
    [employeeId, submissionId, statusFilter, riskBand, pendingOnly, oeScope],
  )

  const { data: rows, isLoading } = useQuery({
    queryKey: ['reports', filters],
    queryFn: () => reportsApi.list(filters),
  })

  return (
    <div className="space-y-5 animate-in">
      <Card>
        <CardBody className="flex flex-wrap items-end gap-3 pt-5">
          <Input
            label="User"
            placeholder="employee id"
            value={employeeId}
            onChange={(e) => setEmployeeId(e.target.value)}
            className="w-44"
          />
          <Input
            label="Report"
            placeholder="submission id"
            value={submissionId}
            onChange={(e) => setSubmissionId(e.target.value)}
            className="w-44"
          />
          <Select label="Status" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} className="w-40">
            {STATUS_OPTIONS.map((s) => (
              <option key={s} value={s}>
                {s || 'All'}
              </option>
            ))}
          </Select>
          <Select label="Risk" value={riskBand} onChange={(e) => setRiskBand(e.target.value)} className="w-36">
            {RISK_OPTIONS.map((s) => (
              <option key={s} value={s}>
                {s || 'All'}
              </option>
            ))}
          </Select>
          <label className="flex h-9 items-center gap-2 text-sm text-text-secondary">
            <input
              type="checkbox"
              checked={pendingOnly}
              onChange={(e) => setPendingOnly(e.target.checked)}
              className="size-4 rounded border-border accent-accent"
            />
            Pending review only
          </label>
          <div className="ml-auto flex items-center gap-1.5 text-xs text-text-muted">
            <Filter className="size-3.5" />
            {rows ? `${rows.length} report${rows.length === 1 ? '' : 's'}` : ''}
          </div>
        </CardBody>
      </Card>

      <Card>
        <CardBody className="pt-4">
          {isLoading ? (
            <SkeletonTable rows={8} />
          ) : !rows?.length ? (
            <EmptyState
              icon={<Search className="size-8" />}
              title="No expense reports match these filters"
              hint="Try clearing a filter, or run a batch to populate the store."
            />
          ) : (
            <Table>
              <Thead>
                <tr>
                  <Th>Report</Th>
                  <Th>User</Th>
                  <Th>Date</Th>
                  <Th>Total</Th>
                  <Th>Risk</Th>
                  <Th>Reason</Th>
                  <Th>Approver</Th>
                  <Th>Violations</Th>
                  <Th>Insights</Th>
                  <Th>Status</Th>
                </tr>
              </Thead>
              <Tbody>
                {rows.map((r: ReportRow) => (
                  <Tr key={r.submission_id} clickable onClick={() => setSelected(r)}>
                    <Td className="font-mono text-xs text-text-primary">{r.submission_id}</Td>
                    <Td>{r.employee_id}</Td>
                    <Td>{formatDate(r.submitted_at)}</Td>
                    <Td className="text-text-primary">{formatMoney(r.total, r.currency)}</Td>
                    <Td>
                      <RiskBadge band={r.risk_band} />
                    </Td>
                    <Td className="max-w-[160px] truncate">{r.risk_reason || '—'}</Td>
                    <Td>{r.approver}</Td>
                    <Td>
                      {r.violations > 0 ? (
                        <Badge kind="error">{r.violations}</Badge>
                      ) : (
                        <span className="text-text-faint">0</span>
                      )}
                    </Td>
                    <Td>
                      {r.insight_count > 0 ? (
                        <Badge kind="warning">{r.insight_count}</Badge>
                      ) : (
                        <span className="text-text-faint">0</span>
                      )}
                    </Td>
                    <Td>
                      <StatusBadge status={r.status} />
                    </Td>
                  </Tr>
                ))}
              </Tbody>
            </Table>
          )}
        </CardBody>
      </Card>

      <Sheet
        open={!!selected}
        onClose={() => setSelected(null)}
        title={selected?.submission_id}
        subtitle="Report detail"
        width="max-w-4xl"
      >
        {selected && (
          <ReportDetailView
            sid={selected.submission_id}
            isNonAuditor={!hasRole('auditor')}
            isPending={selected.status === 'SUBMITTED'}
            onClose={() => setSelected(null)}
          />
        )}
      </Sheet>
    </div>
  )
}

function ReportDetailView({
  sid,
  isNonAuditor,
  isPending,
  onClose,
}: {
  sid: string
  isNonAuditor: boolean
  isPending: boolean
  onClose: () => void
}) {
  const qc = useQueryClient()
  const { push } = useToast()
  const { user } = useAuth()
  const [notes, setNotes] = useState('')
  // Approve/reject only applies to a submission still awaiting a decision
  // (matches ReviewService.queue() / app_pages/expenses.py's _pending_ids) -
  // case management and email compose stay available regardless of decision
  // status (claw-back tracking commonly happens after the fact), gated only
  // on role.
  const canDecide = isNonAuditor && isPending

  const { data: detail, isLoading } = useQuery({
    queryKey: ['reports', 'detail', sid],
    queryFn: () => reportsApi.detail(sid),
  })
  const { data: insights } = useQuery({
    queryKey: ['reports', 'insights', sid],
    queryFn: () => reportsApi.insights(sid),
  })
  const { data: caseStatus } = useQuery({
    queryKey: ['case-status', sid],
    queryFn: () => caseStatusApi.get(sid),
  })
  const { data: templates } = useQuery({
    queryKey: ['email-templates'],
    queryFn: emailTemplatesApi.list,
    enabled: isNonAuditor,
  })

  const decide = useMutation({
    mutationFn: (approved: boolean) =>
      reportsApi.decide(sid, user?.username ?? 'REV-1', approved, notes || undefined),
    onSuccess: (_, approved) => {
      push('success', `Report ${approved ? 'approved' : 'rejected'}.`)
      qc.invalidateQueries({ queryKey: ['reports'] })
      onClose()
    },
    onError: (e: any) => push('error', e.message ?? 'Decision failed'),
  })

  if (isLoading || !detail) {
    return <SkeletonTable rows={5} />
  }

  const sub = detail.submission
  const risk = detail.risk
  const ver = detail.verification

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-4 gap-3">
        <MetricBox label="Risk score" value={Number(risk?.risk_score ?? 0).toFixed(2)} />
        <MetricBox label="OE" value={sub.oe_code} />
        <MetricBox label="Employee" value={sub.employee_id} />
        <MetricBox label="Currency" value={sub.currency} />
      </div>

      <div className="rounded-lg border border-info-border bg-info-bg px-4 py-3 text-sm text-info-text">
        {risk?.explanation || '(no explanation)'}
      </div>

      {insights && insights.length > 0 && (
        <div>
          <div className="mb-2 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-text-muted">
            <Lightbulb className="size-3.5" />
            Consolidated insight summary ({insights.length})
          </div>
          <div className="space-y-1.5">
            {insights.map((i) => (
              <div key={i.type} className="flex items-start gap-3 rounded-lg bg-bg-elevated px-3 py-2 text-sm">
                <Badge kind="warning" className="shrink-0">
                  {i.label}
                </Badge>
                <span className="text-text-secondary">{i.detail}</span>
              </div>
            ))}
          </div>
          {insights.length > 1 && (
            <p className="mt-1.5 text-xs text-text-muted">
              {insights.length} distinct insight types fired on this one case — resolved together with a single
              approve/reject/case-status action below.
            </p>
          )}
        </div>
      )}

      <Tabs
        defaultKey="lines"
        tabs={[
          {
            key: 'lines',
            label: 'Extracted lines',
            icon: <FileText className="size-3.5" />,
            content: (
              <Table>
                <Thead>
                  <tr>
                    <Th>Line</Th>
                    <Th>Vendor</Th>
                    <Th>Date</Th>
                    <Th>Amount</Th>
                    <Th>Confidence</Th>
                  </tr>
                </Thead>
                <Tbody>
                  {detail.extracted_lines.map((l: any) => (
                    <Tr key={l.line_item_id}>
                      <Td>{l.line_item_id?.split(':').pop()}</Td>
                      <Td>{l.vendor}</Td>
                      <Td>{formatDate(l.txn_date)}</Td>
                      <Td>{l.amount}</Td>
                      <Td>{l.confidence != null ? Number(l.confidence).toFixed(2) : '—'}</Td>
                    </Tr>
                  ))}
                </Tbody>
              </Table>
            ),
          },
          {
            key: 'verification',
            label: 'Verification',
            icon: <ShieldQuestion className="size-3.5" />,
            content: <VerificationTab ver={ver} />,
          },
          {
            key: 'policy',
            label: 'Policy',
            icon: <ScrollText className="size-3.5" />,
            content: (
              <Table>
                <Thead>
                  <tr>
                    <Th>Rule</Th>
                    <Th>Passed</Th>
                  </tr>
                </Thead>
                <Tbody>
                  {detail.policy.map((p) => (
                    <Tr key={p.rule_id}>
                      <Td className="font-mono text-xs">{p.rule_id}</Td>
                      <Td>{p.passed ? <Badge kind="success">Pass</Badge> : <Badge kind="error">Fail</Badge>}</Td>
                    </Tr>
                  ))}
                </Tbody>
              </Table>
            ),
          },
          {
            key: 'evidence',
            label: 'Evidence',
            icon: <ImageIcon className="size-3.5" />,
            content: <ReceiptViewer sid={sid} receipts={detail.receipts} />,
          },
          {
            key: 'trace',
            label: 'Pipeline log',
            icon: <Workflow className="size-3.5" />,
            content: <PipelineTraceTab sid={sid} />,
          },
        ]}
      />

      <div className="border-t border-border pt-5">
        <div className="mb-2 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-text-muted">
          <FolderKanban className="size-3.5" />
          Case management
        </div>
        <CaseManagementPanel sid={sid} readOnly={!isNonAuditor} caseStatus={caseStatus} currency={sub.currency} />
      </div>

      {isNonAuditor && templates && templates.length > 0 && (
        <EmailComposePanel sid={sid} templates={templates} reasonDefault={risk?.explanation ?? ''} />
      )}

      {canDecide ? (
        <div className="flex items-center gap-2 border-t border-border pt-5">
          <Input
            placeholder="Reviewer notes (optional)"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            className="flex-1"
          />
          <Button variant="danger" onClick={() => decide.mutate(false)} loading={decide.isPending}>
            <XIcon className="size-4" /> Reject
          </Button>
          <Button variant="primary" onClick={() => decide.mutate(true)} loading={decide.isPending}>
            <Check className="size-4" /> Approve
          </Button>
        </div>
      ) : (
        <p className="border-t border-border pt-4 text-xs text-text-muted">
          {!isNonAuditor
            ? 'Read-only auditor view — approve/reject is not available for this role.'
            : 'This case already has a final decision — approve/reject only applies to submissions still awaiting review.'}
        </p>
      )}
    </div>
  )
}

function MetricBox({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-border bg-bg-elevated px-3 py-2.5 text-center">
      <div className="text-lg font-bold text-text-primary">{value}</div>
      <div className="mt-0.5 text-[10px] font-semibold uppercase tracking-wider text-text-muted">{label}</div>
    </div>
  )
}

function VerificationTab({ ver }: { ver: ReportDetail['verification'] }) {
  // duplicate_match_details is the richer sibling of duplicate_match_ids -
  // {submission_id, similarity, match_type} - render "SUB-X (invoice #)" for
  // a structured match vs "SUB-Y (94% similar)" for embedding-only, falling
  // back to the bare ID list if details aren't present (older rows).
  const details: Array<{ submission_id: string; similarity: number; match_type: string }> =
    ver.duplicate_match_details ?? []
  const duplicateOf = details.length
    ? details
        .map((d) =>
          d.match_type === 'invoice_number'
            ? `${d.submission_id} (invoice #)`
            : `${d.submission_id} (${Math.round(d.similarity * 100)}% similar)`,
        )
        .join(', ')
    : ver.duplicate_match_ids?.length
      ? ver.duplicate_match_ids.join(', ')
      : '—'

  const rows: Array<[string, any]> = [
    ['Authenticity flags', ver.authenticity_flags?.length ? ver.authenticity_flags.join(', ') : '—'],
    ['Duplicate of', duplicateOf],
    ['Subtotal variance %', ver.subtotal_variance_pct ?? '—'],
    ['Velocity flags', ver.velocity_flags?.length ? ver.velocity_flags.join(', ') : '—'],
    ['Split-transaction flags', ver.split_transaction_flags?.length ? ver.split_transaction_flags.join(', ') : '—'],
    ['Merchant validation', ver.merchant_validation ?? '—'],
    ['Merchant flags', ver.merchant_flags?.length ? ver.merchant_flags.join(', ') : '—'],
    ['Compliance flags', ver.compliance_flags?.length ? ver.compliance_flags.join(', ') : '—'],
    ['Peer-group outlier flags', ver.peer_outlier_flags?.length ? ver.peer_outlier_flags.join(', ') : '—'],
    ['Merchant network flags', ver.merchant_network_flags?.length ? ver.merchant_network_flags.join(', ') : '—'],
  ]
  return (
    <dl className="grid grid-cols-2 gap-3">
      {rows.map(([k, v]) => (
        <div key={k} className="rounded-lg bg-bg-elevated px-3 py-2">
          <dt className="text-[10px] font-semibold uppercase tracking-wider text-text-muted">{k}</dt>
          <dd className="mt-0.5 truncate text-sm text-text-secondary" title={String(v)}>
            {String(v)}
          </dd>
        </div>
      ))}
    </dl>
  )
}

function PipelineTraceTab({ sid }: { sid: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ['reports', 'pipeline-log', sid],
    queryFn: () => reportsApi.pipelineLog(sid),
  })
  if (isLoading) return <SkeletonTable rows={4} />
  if (!data?.length) return <p className="text-sm text-text-muted">No pipeline trace recorded yet.</p>
  return (
    <div className="space-y-2">
      {data.map((s, i) => (
        <div
          key={i}
          className={cn(
            'rounded-lg border px-3 py-2.5 text-sm',
            s.ok ? 'border-border bg-bg-elevated' : 'border-error-border bg-error-bg',
          )}
        >
          <div className="flex items-center justify-between">
            <span className="font-semibold text-text-primary">
              {s.ok ? '✅' : '❌'} {s.node}
            </span>
            <span className="text-xs text-text-muted">
              {s.latency_ms?.toFixed?.(0)} ms{s.attempts > 1 ? `, ${s.attempts} attempts` : ''}
            </span>
          </div>
          {s.error_message && <p className="mt-1 text-xs text-error-text">{s.error_message}</p>}
        </div>
      ))}
    </div>
  )
}

function EmailComposePanel({
  sid,
  templates,
  reasonDefault,
}: {
  sid: string
  templates: string[]
  reasonDefault: string
}) {
  const [template, setTemplate] = useState(templates[0])
  const [reason, setReason] = useState(reasonDefault)
  const { data, isFetching } = useQuery({
    queryKey: ['email-render', sid, template, reason],
    queryFn: () => emailTemplatesApi.render(template, sid, reason),
    enabled: !!template,
  })

  return (
    <details className="rounded-lg border border-border">
      <summary className="flex cursor-pointer items-center gap-2 px-4 py-3 text-sm font-medium text-text-secondary">
        <Mail className="size-4" /> Compose email to traveller (simulated — not actually sent)
      </summary>
      <div className="space-y-3 border-t border-border p-4">
        <div className="grid grid-cols-2 gap-3">
          <Select label="Template" value={template} onChange={(e) => setTemplate(e.target.value)}>
            {templates.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </Select>
          <Input label="Reason (fills {reason})" value={reason} onChange={(e) => setReason(e.target.value)} />
        </div>
        <Input label="Subject" value={isFetching ? '…' : data?.subject ?? ''} readOnly />
        <label className="block">
          <span className="mb-1.5 block text-[11px] font-semibold uppercase tracking-wide text-text-secondary">
            Body
          </span>
          <textarea
            readOnly
            value={isFetching ? '…' : data?.body ?? ''}
            rows={8}
            className="w-full rounded-lg border border-border bg-bg-elevated px-3 py-2 text-sm text-text-primary"
          />
        </label>
        <p className="text-xs text-text-muted">Simulated — no real email is sent. Copy this into your mail client.</p>
      </div>
    </details>
  )
}
