import { useQuery } from '@tanstack/react-query'
import {
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  AreaChart,
  Area,
  CartesianGrid,
  Legend,
} from 'recharts'
import {
  Inbox,
  Zap,
  CheckCircle2,
  AlertTriangle,
  DollarSign,
  Flag,
  Gauge,
  Clock,
} from 'lucide-react'
import { analyticsApi } from '../lib/api'
import { useAuth } from '../lib/auth'
import { Card, CardHeader, CardBody } from '../components/ui/Card'
import { KpiRow, KpiTile } from '../components/ui/KpiTile'
import { SkeletonKpiRow, Skeleton } from '../components/ui/Skeleton'
import { Table, Thead, Tbody, Tr, Th, Td } from '../components/ui/Table'
import { StatusBadge } from '../components/ui/Badge'
import { CHART_COLORS, PIE_PALETTE, tooltipStyle, axisStyle } from '../components/charts/theme'
import { formatMoney, formatPct, formatDate } from '../lib/utils'

const ROUTING_LABELS: Record<string, string> = {
  auto_approve: 'Auto-approved',
  auto_reject: 'Auto-rejected',
  human_review: 'Human review',
}
const REASON_LABELS: Record<string, string> = {
  policy_violation: 'Policy violation',
  duplicate: 'Duplicate',
  authenticity: 'Authenticity',
  subtotal_variance: 'Amount mismatch',
  low_confidence: 'Low confidence',
}

export function DashboardPage() {
  const { oeScope } = useAuth()
  const { data, isLoading, isError } = useQuery({
    queryKey: ['dashboard', oeScope],
    queryFn: () => analyticsApi.dashboard(oeScope || undefined),
  })

  if (isLoading) {
    return (
      <div className="space-y-6">
        <SkeletonKpiRow count={4} />
        <div className="grid gap-4 lg:grid-cols-2">
          <Skeleton className="h-72 rounded-xl" />
          <Skeleton className="h-72 rounded-xl" />
        </div>
      </div>
    )
  }
  if (isError || !data) {
    return (
      <Card>
        <CardBody className="pt-5 text-sm text-text-muted">
          No data yet. Run a batch first (System admin, or <code>python scripts/run_batch.py</code>).
        </CardBody>
      </Card>
    )
  }

  const routingData = Object.entries(data.routing).map(([k, v]) => ({
    name: ROUTING_LABELS[k] ?? k,
    value: v,
  }))
  const histData = Object.entries(data.risk_histogram).map(([bucket, count]) => ({ bucket, count }))
  const spendCatData = Object.entries(data.spend_by_category)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 8)
    .map(([category, spend]) => ({ category, spend }))
  const reasonData = Object.entries(data.exception_reasons).map(([k, v]) => ({
    reason: REASON_LABELS[k] ?? k,
    count: v,
  }))

  return (
    <div className="space-y-6 animate-in">
      <KpiRow>
        <KpiTile label="Total submissions" value={data.kpis.total_submissions} icon={Inbox} />
        <KpiTile label="Automation rate" value={formatPct(data.kpis.automation_rate)} icon={Zap} />
        <KpiTile
          label="Straight-through rate"
          value={formatPct(data.kpis.straight_through_rate)}
          icon={CheckCircle2}
        />
        <KpiTile
          label="Exception rate"
          value={formatPct(data.kpis.exception_rate)}
          icon={AlertTriangle}
          bad={data.kpis.exception_rate > 0.3}
        />
        <KpiTile label="Total spend" value={formatMoney(data.kpis.total_spend)} icon={DollarSign} />
        <KpiTile
          label="Flagged spend"
          value={formatMoney(data.kpis.flagged_spend)}
          icon={Flag}
          bad={data.kpis.flagged_spend > 0}
        />
        <KpiTile label="Avg risk score" value={data.kpis.avg_risk_score.toFixed(2)} icon={Gauge} />
        <KpiTile
          label="Review backlog"
          value={data.kpis.review_backlog}
          icon={Clock}
          bad={data.kpis.review_backlog > 0}
        />
      </KpiRow>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader title="Routing mix" subtitle="Auto-approve / auto-reject / human review" />
          <CardBody>
            <ResponsiveContainer width="100%" height={220}>
              <PieChart>
                <Pie data={routingData} dataKey="value" nameKey="name" innerRadius={55} outerRadius={85} paddingAngle={3}>
                  {routingData.map((_, i) => (
                    <Cell key={i} fill={PIE_PALETTE[i % PIE_PALETTE.length]} stroke="none" />
                  ))}
                </Pie>
                <Tooltip {...tooltipStyle} />
                <Legend wrapperStyle={{ fontSize: 12, color: '#93a5c4' }} />
              </PieChart>
            </ResponsiveContainer>
          </CardBody>
        </Card>

        <Card>
          <CardHeader title="Risk score distribution" subtitle="Submissions by risk-score bucket" />
          <CardBody>
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={histData}>
                <CartesianGrid stroke={CHART_COLORS.grid} vertical={false} />
                <XAxis dataKey="bucket" {...axisStyle} interval={1} />
                <YAxis {...axisStyle} allowDecimals={false} />
                <Tooltip {...tooltipStyle} cursor={{ fill: 'rgba(255,255,255,0.03)' }} />
                <Bar dataKey="count" fill={CHART_COLORS.accent} radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </CardBody>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader title="Spend by category" subtitle="Top 8 categories" />
          <CardBody>
            <ResponsiveContainer width="100%" height={240}>
              <BarChart data={spendCatData} layout="vertical" margin={{ left: 8 }}>
                <CartesianGrid stroke={CHART_COLORS.grid} horizontal={false} />
                <XAxis type="number" {...axisStyle} />
                <YAxis type="category" dataKey="category" {...axisStyle} width={90} />
                <Tooltip {...tooltipStyle} cursor={{ fill: 'rgba(255,255,255,0.03)' }}
                  formatter={(v) => formatMoney(Number(v))} />
                <Bar dataKey="spend" fill={CHART_COLORS.purple} radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </CardBody>
        </Card>

        <Card>
          <CardHeader title="Submission trend" subtitle="Daily volume + automation rate" />
          <CardBody>
            <ResponsiveContainer width="100%" height={240}>
              <AreaChart data={data.trend}>
                <defs>
                  <linearGradient id="trendFill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor={CHART_COLORS.accent} stopOpacity={0.35} />
                    <stop offset="100%" stopColor={CHART_COLORS.accent} stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke={CHART_COLORS.grid} vertical={false} />
                <XAxis dataKey="date" {...axisStyle} tickFormatter={(d) => d.slice(5)} />
                <YAxis {...axisStyle} allowDecimals={false} />
                <Tooltip {...tooltipStyle} />
                <Area
                  type="monotone"
                  dataKey="submissions"
                  stroke={CHART_COLORS.accent}
                  fill="url(#trendFill)"
                  strokeWidth={2}
                />
              </AreaChart>
            </ResponsiveContainer>
          </CardBody>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader title="Exception reasons" subtitle="Why submissions reached human review" />
          <CardBody className="space-y-2">
            {reasonData.length === 0 ? (
              <p className="text-sm text-text-muted">No exceptions recorded.</p>
            ) : (
              reasonData
                .sort((a, b) => b.count - a.count)
                .map((r) => (
                  <div key={r.reason} className="flex items-center justify-between rounded-lg bg-bg-elevated px-3 py-2">
                    <span className="text-sm text-text-secondary">{r.reason}</span>
                    <span className="text-sm font-semibold text-text-primary">{r.count}</span>
                  </div>
                ))
            )}
          </CardBody>
        </Card>

        <Card>
          <CardHeader title="Top violated rules" subtitle="Most frequently triggered policy rules" />
          <CardBody className="space-y-2">
            {data.top_rules.length === 0 ? (
              <p className="text-sm text-text-muted">No policy violations recorded.</p>
            ) : (
              data.top_rules.slice(0, 8).map((r) => (
                <div key={r.rule_id} className="flex items-center justify-between rounded-lg bg-bg-elevated px-3 py-2">
                  <span className="truncate text-sm text-text-secondary" title={r.rule_id}>
                    {r.rule_id}
                  </span>
                  <span className="text-sm font-semibold text-text-primary">{r.violations}</span>
                </div>
              ))
            )}
          </CardBody>
        </Card>
      </div>

      <Card>
        <CardHeader title="Recent decisions" subtitle="Most recent 25 risk decisions" />
        <CardBody className="pt-0">
          <Table>
            <Thead>
              <tr>
                <Th>Submission</Th>
                <Th>Risk score</Th>
                <Th>Routing</Th>
                <Th>Decided at</Th>
              </tr>
            </Thead>
            <Tbody>
              {data.recent_decisions.map((r) => (
                <Tr key={r.submission_id}>
                  <Td className="font-mono text-xs text-text-primary">{r.submission_id}</Td>
                  <Td>{Number(r.risk_score).toFixed(2)}</Td>
                  <Td>
                    <StatusBadge
                      status={
                        r.routing_decision === 'auto_approve'
                          ? 'APPROVED'
                          : r.routing_decision === 'auto_reject'
                            ? 'REJECTED'
                            : 'SUBMITTED'
                      }
                    />
                  </Td>
                  <Td>{formatDate(r.decided_at)}</Td>
                </Tr>
              ))}
            </Tbody>
          </Table>
        </CardBody>
      </Card>
    </div>
  )
}
