import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
} from 'recharts'
import { Download, FileSpreadsheet, Activity, ShieldCheck as ShieldIcon, Landmark } from 'lucide-react'
import { reportsApi, reportsExportApi } from '../lib/api'
import { useAuth } from '../lib/auth'
import { downloadAuthed } from '../lib/useAuthedBlobUrl'
import { Card, CardHeader, CardBody } from '../components/ui/Card'
import { Button } from '../components/ui/Button'
import { Tabs } from '../components/ui/Tabs'
import { Table, Thead, Tbody, Tr, Th, Td, EmptyState } from '../components/ui/Table'
import { KpiRow, KpiTile } from '../components/ui/KpiTile'
import { Badge } from '../components/ui/Badge'
import { SkeletonTable } from '../components/ui/Skeleton'
import { CHART_COLORS, tooltipStyle, axisStyle } from '../components/charts/theme'
import { formatMoney, rowsToCsv, downloadText } from '../lib/utils'

export function ReportsExportsPage() {
  return (
    <div className="animate-in">
      <Tabs
        defaultKey="decisions"
        tabs={[
          { key: 'decisions', label: 'Decision extract', icon: <FileSpreadsheet className="size-3.5" />, content: <DecisionExtractTab /> },
          { key: 'accuracy', label: 'Accuracy & latency', icon: <Activity className="size-3.5" />, content: <AccuracyLatencyTab /> },
          { key: 'observability', label: 'Observability', icon: <Activity className="size-3.5" />, content: <ObservabilityTab /> },
          { key: 'compliance', label: 'Compliance packs', icon: <ShieldIcon className="size-3.5" />, content: <CompliancePacksTab /> },
        ]}
      />
    </div>
  )
}

function DecisionExtractTab() {
  const { oeScope } = useAuth()
  const filters = useMemo(() => ({ oe_code: oeScope || undefined }), [oeScope])
  const { data: rows, isLoading } = useQuery({ queryKey: ['reports', filters], queryFn: () => reportsApi.list(filters) })

  if (isLoading) return <SkeletonTable rows={8} />
  if (!rows?.length) return <EmptyState title="No data yet" hint="Run a batch first." />

  return (
    <Card>
      <CardHeader
        title={`${rows.length} audited reports`}
        action={
          <Button variant="secondary" size="sm" onClick={() => downloadText(rowsToCsv(rows), 'expense_audit_decisions.csv')}>
            <Download className="size-3.5" /> Download CSV
          </Button>
        }
      />
      <CardBody className="pt-0">
        <Table>
          <Thead>
            <tr>
              <Th>Report</Th>
              <Th>User</Th>
              <Th>Date</Th>
              <Th>Total</Th>
              <Th>Risk</Th>
              <Th>Status</Th>
            </tr>
          </Thead>
          <Tbody>
            {rows.map((r) => (
              <Tr key={r.submission_id}>
                <Td className="font-mono text-xs">{r.submission_id}</Td>
                <Td>{r.employee_id}</Td>
                <Td>{r.submitted_at.slice(0, 10)}</Td>
                <Td>{formatMoney(r.total, r.currency)}</Td>
                <Td>{r.risk_band}</Td>
                <Td>{r.status}</Td>
              </Tr>
            ))}
          </Tbody>
        </Table>
      </CardBody>
    </Card>
  )
}

function AccuracyLatencyTab() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['accuracy-latency'],
    queryFn: reportsExportApi.accuracyLatency,
    retry: false,
  })

  if (isLoading) return <SkeletonTable rows={5} />
  if (isError || !data) {
    return <EmptyState title="No accuracy/latency report yet" hint="Generate one via `python scripts/report.py`." />
  }

  return (
    <Card>
      <CardHeader
        title="Accuracy & latency report"
        subtitle={data.source}
        action={
          <div className="flex gap-2">
            <Button
              variant="secondary"
              size="sm"
              onClick={() => downloadAuthed(reportsExportApi.downloadUrl('json'), 'report.json')}
            >
              <Download className="size-3.5" /> JSON
            </Button>
            {data.markdown_available && (
              <Button
                variant="secondary"
                size="sm"
                onClick={() => downloadAuthed(reportsExportApi.downloadUrl('markdown'), 'report.md')}
              >
                <Download className="size-3.5" /> Markdown
              </Button>
            )}
          </div>
        }
      />
      <CardBody className="pt-0">
        <Table>
          <Thead>
            <tr>
              <Th>Metric</Th>
              <Th>Measured</Th>
              <Th>Threshold</Th>
              <Th>Meets</Th>
            </tr>
          </Thead>
          <Tbody>
            {data.metrics.map((m: any) => (
              <Tr key={m.metric}>
                <Td>{m.metric}</Td>
                <Td className="text-text-primary">{m.measured}</Td>
                <Td>{m.threshold ?? '—'}</Td>
                <Td>
                  {m.meets == null ? (
                    <Badge kind="neutral">info</Badge>
                  ) : m.meets ? (
                    <Badge kind="success">meets</Badge>
                  ) : (
                    <Badge kind="error">below</Badge>
                  )}
                </Td>
              </Tr>
            ))}
          </Tbody>
        </Table>
      </CardBody>
    </Card>
  )
}

function ObservabilityTab() {
  const { oeScope } = useAuth()
  const { data: logs, isLoading } = useQuery({
    queryKey: ['pipeline-logs', oeScope],
    queryFn: () => reportsExportApi.pipelineLogs(5000, oeScope || undefined),
  })

  const stats = useMemo(() => {
    if (!logs?.length) return null
    const totalSteps = logs.length
    const submissions = new Set(logs.map((l) => l.submission_id)).size
    const errors = logs.filter((l) => !l.ok).length
    const avgLatency = logs.reduce((s, l) => s + Number(l.latency_ms || 0), 0) / totalSteps
    const byNode: Record<string, { total: number; count: number }> = {}
    for (const l of logs) {
      byNode[l.node] ??= { total: 0, count: 0 }
      byNode[l.node].total += Number(l.latency_ms || 0)
      byNode[l.node].count += 1
    }
    const latencyByNode = Object.entries(byNode).map(([node, v]) => ({ node, latency: Math.round(v.total / v.count) }))
    return { totalSteps, submissions, errors, avgLatency, latencyByNode }
  }, [logs])

  if (isLoading) return <SkeletonTable rows={5} />
  if (!logs?.length) return <EmptyState title="No pipeline runs logged yet" hint="Run a batch first." />

  return (
    <div className="space-y-4">
      <KpiRow>
        <KpiTile label="Steps logged" value={stats!.totalSteps} icon={Activity} />
        <KpiTile label="Submissions traced" value={stats!.submissions} />
        <KpiTile
          label="Node error rate"
          value={`${((stats!.errors / stats!.totalSteps) * 100).toFixed(1)}%`}
          bad={stats!.errors > 0}
        />
        <KpiTile label="Avg node latency" value={`${stats!.avgLatency.toFixed(0)} ms`} />
      </KpiRow>

      <Card>
        <CardHeader title="Avg latency by node" />
        <CardBody>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={stats!.latencyByNode}>
              <CartesianGrid stroke={CHART_COLORS.grid} vertical={false} />
              <XAxis dataKey="node" {...axisStyle} />
              <YAxis {...axisStyle} />
              <Tooltip {...tooltipStyle} cursor={{ fill: 'rgba(255,255,255,0.03)' }} />
              <Bar dataKey="latency" fill={CHART_COLORS.accent} radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          title={`Raw pipeline log (${logs.length} rows)`}
          action={
            <Button
              variant="secondary"
              size="sm"
              onClick={() => downloadText(rowsToCsv(logs), `pipeline_log_${new Date().toISOString().slice(0, 10)}.csv`)}
            >
              <Download className="size-3.5" /> Download CSV
            </Button>
          }
        />
        <CardBody className="pt-0">
          <div className="max-h-96 overflow-y-auto">
            <Table>
              <Thead>
                <tr>
                  <Th>Submission</Th>
                  <Th>Node</Th>
                  <Th>OK</Th>
                  <Th>Latency (ms)</Th>
                  <Th>Attempts</Th>
                </tr>
              </Thead>
              <Tbody>
                {logs.slice(0, 200).map((l, i) => (
                  <Tr key={i}>
                    <Td className="font-mono text-xs">{l.submission_id}</Td>
                    <Td>{l.node}</Td>
                    <Td>{l.ok ? <Badge kind="success">ok</Badge> : <Badge kind="error">error</Badge>}</Td>
                    <Td>{Number(l.latency_ms).toFixed(0)}</Td>
                    <Td>{l.attempts}</Td>
                  </Tr>
                ))}
              </Tbody>
            </Table>
          </div>
        </CardBody>
      </Card>
    </div>
  )
}

function CompliancePacksTab() {
  const { oeScope } = useAuth()
  const { data, isLoading } = useQuery({
    queryKey: ['compliance-packs', oeScope],
    queryFn: () => reportsExportApi.compliancePacks(oeScope || undefined),
  })

  if (isLoading || !data) return <SkeletonTable rows={6} />

  const { sox_icfr, fcpa_sanctions, recoverable_funds } = data

  return (
    <div className="space-y-5">
      <Card>
        <CardHeader
          title="SOX / ICFR summary"
          subtitle="Automation mix, policy-violation counts by rule, and the full decision trail — a starting evidence pack, not a certified report."
          action={
            sox_icfr.violations_by_rule.length > 0 && (
              <Button
                variant="secondary"
                size="sm"
                onClick={() => downloadText(rowsToCsv(sox_icfr.violations_by_rule), 'sox_icfr_violations_by_rule.csv')}
              >
                <Download className="size-3.5" /> CSV
              </Button>
            )
          }
        />
        <CardBody>
          {!sox_icfr.total_submissions ? (
            <p className="text-sm text-text-muted">No submissions audited yet.</p>
          ) : (
            <>
              <KpiRow>
                <KpiTile label="Total submissions" value={sox_icfr.total_submissions} />
                <KpiTile label="Auto-approved" value={`${(sox_icfr.auto_approved_pct * 100).toFixed(0)}%`} />
                <KpiTile
                  label="Auto-rejected"
                  value={`${(sox_icfr.auto_rejected_pct * 100).toFixed(0)}%`}
                  bad={sox_icfr.auto_rejected_pct > 0}
                />
                <KpiTile label="Human review" value={`${(sox_icfr.human_review_pct * 100).toFixed(0)}%`} />
              </KpiRow>
              {sox_icfr.violations_by_rule.length > 0 && (
                <Table>
                  <Thead>
                    <tr>
                      <Th>Rule ID</Th>
                      <Th>Violation count</Th>
                    </tr>
                  </Thead>
                  <Tbody>
                    {sox_icfr.violations_by_rule.map((r) => (
                      <Tr key={r.rule_id}>
                        <Td className="font-mono text-xs">{r.rule_id}</Td>
                        <Td>{r.violation_count}</Td>
                      </Tr>
                    ))}
                  </Tbody>
                </Table>
              )}
            </>
          )}
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          title="FCPA / anti-bribery & sanctions summary"
          subtitle="Cumulative-compliance flags (BR-TE-AU-04) or merchant sanctions/PEP watchlist hits (BR-TE-AU-03, simulated)."
          action={
            fcpa_sanctions.flagged.length > 0 && (
              <Button
                variant="secondary"
                size="sm"
                onClick={() =>
                  downloadText(
                    rowsToCsv(
                      fcpa_sanctions.flagged.map((f) => ({
                        ...f,
                        compliance_flags: f.compliance_flags.join('; '),
                        merchant_flags: f.merchant_flags.join('; '),
                      })),
                    ),
                    'fcpa_sanctions_evidence.csv',
                  )
                }
              >
                <Download className="size-3.5" /> CSV
              </Button>
            )
          }
        />
        <CardBody className="pt-0">
          {fcpa_sanctions.flagged.length === 0 ? (
            <p className="text-sm text-text-muted">No FCPA/anti-bribery or sanctions/PEP signals recorded yet.</p>
          ) : (
            <Table>
              <Thead>
                <tr>
                  <Th>Submission</Th>
                  <Th>Employee</Th>
                  <Th>Date</Th>
                  <Th>Routing</Th>
                  <Th>Compliance flags</Th>
                  <Th>Merchant flags</Th>
                </tr>
              </Thead>
              <Tbody>
                {fcpa_sanctions.flagged.map((f) => (
                  <Tr key={f.submission_id}>
                    <Td className="font-mono text-xs">{f.submission_id}</Td>
                    <Td>{f.employee_id}</Td>
                    <Td>{f.submitted_at}</Td>
                    <Td>{f.routing_decision}</Td>
                    <Td className="max-w-[200px] truncate">{f.compliance_flags.join('; ') || '—'}</Td>
                    <Td className="max-w-[200px] truncate">{f.merchant_flags.join('; ') || '—'}</Td>
                  </Tr>
                ))}
              </Tbody>
            </Table>
          )}
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          title="Recoverable funds"
          subtitle="Cases tracked through the case-management workflow, with amounts recovered through audit claw-back."
          action={
            recoverable_funds.cases.length > 0 && (
              <Button
                variant="secondary"
                size="sm"
                onClick={() => downloadText(rowsToCsv(recoverable_funds.cases), 'case_status_recoverable_funds.csv')}
              >
                <Download className="size-3.5" /> CSV
              </Button>
            )
          }
        />
        <CardBody>
          {!recoverable_funds.cases_tracked ? (
            <p className="text-sm text-text-muted">No cases have a tracked status yet.</p>
          ) : (
            <>
              <KpiRow>
                <KpiTile label="Cases tracked" value={recoverable_funds.cases_tracked} icon={Landmark} />
                <KpiTile
                  label="Claw-back pending"
                  value={recoverable_funds.claw_back_pending}
                  bad={recoverable_funds.claw_back_pending > 0}
                />
                <KpiTile label="Resolved" value={recoverable_funds.resolved} />
                <KpiTile label="Total recovered" value={formatMoney(recoverable_funds.total_recovered)} />
              </KpiRow>
              <Table>
                <Thead>
                  <tr>
                    <Th>Submission</Th>
                    <Th>Status</Th>
                    <Th>Recovered</Th>
                    <Th>Updated by</Th>
                    <Th>Updated at</Th>
                  </tr>
                </Thead>
                <Tbody>
                  {recoverable_funds.cases.map((c) => (
                    <Tr key={c.submission_id}>
                      <Td className="font-mono text-xs">{c.submission_id}</Td>
                      <Td>{c.status}</Td>
                      <Td>{c.recovered_amount ?? '—'}</Td>
                      <Td>{c.updated_by ?? '—'}</Td>
                      <Td>{c.updated_at ?? '—'}</Td>
                    </Tr>
                  ))}
                </Tbody>
              </Table>
            </>
          )}
        </CardBody>
      </Card>
    </div>
  )
}
