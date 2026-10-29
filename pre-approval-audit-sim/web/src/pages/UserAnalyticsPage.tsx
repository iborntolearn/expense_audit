import { useMemo, useState } from 'react'
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
import { Wallet, ShieldAlert, Gauge, CheckCircle2, FileStack } from 'lucide-react'
import { analyticsApi, reportsApi } from '../lib/api'
import { useAuth } from '../lib/auth'
import { Card, CardHeader, CardBody } from '../components/ui/Card'
import { KpiRow, KpiTile } from '../components/ui/KpiTile'
import { Select } from '../components/ui/Input'
import { SkeletonKpiRow, Skeleton } from '../components/ui/Skeleton'
import { CHART_COLORS, tooltipStyle, axisStyle } from '../components/charts/theme'
import { formatMoney } from '../lib/utils'

const PERIODS: Record<string, number | undefined> = { 'All time': undefined, 'Last 30 days': 30, 'Last 90 days': 90 }

export function UserAnalyticsPage() {
  const { oeScope } = useAuth()
  const reportFilters = useMemo(() => ({ oe_code: oeScope || undefined }), [oeScope])
  const { data: allReports } = useQuery({ queryKey: ['reports', reportFilters], queryFn: () => reportsApi.list(reportFilters) })
  const employees = useMemo(
    () => Array.from(new Set((allReports ?? []).map((r) => r.employee_id))).sort(),
    [allReports],
  )
  const [employeeId, setEmployeeId] = useState('')
  const [period, setPeriod] = useState('All time')

  const active = employeeId || employees[0] || ''

  const { data, isLoading } = useQuery({
    queryKey: ['user-analytics', active, period, oeScope],
    queryFn: () => analyticsApi.userAnalytics(active, PERIODS[period], oeScope || undefined),
    enabled: !!active,
  })

  if (!employees.length) {
    return (
      <Card>
        <CardBody className="pt-5 text-sm text-text-muted">No data yet. Run a batch to populate the store.</CardBody>
      </Card>
    )
  }

  const spendByType = data
    ? Object.entries(data.spend_by_type).map(([category, v]) => ({ category, spend: v.spend }))
    : []
  const highRiskByType = data
    ? Object.entries(data.high_risk_spend_by_type).map(([category, spend]) => ({ category, spend }))
    : []
  const spendByGeo = data ? Object.entries(data.spend_by_geo).map(([oe, spend]) => ({ oe, spend })) : []

  return (
    <div className="space-y-5 animate-in">
      <Card>
        <CardBody className="flex flex-wrap items-end gap-3 pt-5">
          <Select label="Employee" value={active} onChange={(e) => setEmployeeId(e.target.value)} className="w-56">
            {employees.map((e) => (
              <option key={e} value={e}>
                {e}
              </option>
            ))}
          </Select>
          <Select label="Period" value={period} onChange={(e) => setPeriod(e.target.value)} className="w-44">
            {Object.keys(PERIODS).map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </Select>
        </CardBody>
      </Card>

      {isLoading || !data ? (
        <SkeletonKpiRow count={5} />
      ) : (
        <KpiRow>
          <KpiTile label="T&E spend" value={formatMoney(data.kpis.te_spend)} icon={Wallet} />
          <KpiTile
            label="Rejected / high-risk spend"
            value={formatMoney(data.kpis.rejected_high_risk_spend)}
            icon={ShieldAlert}
            bad={data.kpis.rejected_high_risk_spend > 0}
          />
          <KpiTile label="ABI score" value={data.kpis.abi_score} icon={Gauge} />
          <KpiTile label="Auto-approved" value={data.kpis.auto_approved} icon={CheckCircle2} />
          <KpiTile label="Total reports" value={data.kpis.total_reports} icon={FileStack} />
        </KpiRow>
      )}

      {isLoading || !data ? (
        <Skeleton className="h-72 rounded-xl" />
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          <Card>
            <CardHeader title="Spend by category" />
            <CardBody>
              {spendByType.length === 0 ? (
                <p className="text-sm text-text-muted">No spend recorded for this period.</p>
              ) : (
                <ResponsiveContainer width="100%" height={240}>
                  <BarChart data={spendByType} layout="vertical" margin={{ left: 8 }}>
                    <CartesianGrid stroke={CHART_COLORS.grid} horizontal={false} />
                    <XAxis type="number" {...axisStyle} />
                    <YAxis type="category" dataKey="category" {...axisStyle} width={90} />
                    <Tooltip {...tooltipStyle} cursor={{ fill: 'rgba(255,255,255,0.03)' }}
                      formatter={(v) => formatMoney(Number(v))} />
                    <Bar dataKey="spend" fill={CHART_COLORS.accent} radius={[0, 4, 4, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              )}
            </CardBody>
          </Card>

          <Card>
            <CardHeader title="High-risk spend by category" subtitle="Categories on high-risk/rejected submissions" />
            <CardBody>
              {highRiskByType.length === 0 ? (
                <p className="text-sm text-text-muted">No high-risk spend recorded.</p>
              ) : (
                <ResponsiveContainer width="100%" height={240}>
                  <BarChart data={highRiskByType} layout="vertical" margin={{ left: 8 }}>
                    <CartesianGrid stroke={CHART_COLORS.grid} horizontal={false} />
                    <XAxis type="number" {...axisStyle} />
                    <YAxis type="category" dataKey="category" {...axisStyle} width={90} />
                    <Tooltip {...tooltipStyle} cursor={{ fill: 'rgba(255,255,255,0.03)' }}
                      formatter={(v) => formatMoney(Number(v))} />
                    <Bar dataKey="spend" fill={CHART_COLORS.error} radius={[0, 4, 4, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              )}
            </CardBody>
          </Card>
        </div>
      )}

      {!isLoading && data && (
        <div className="grid gap-4 lg:grid-cols-2">
          <Card>
            <CardHeader title="Behavioral trends" subtitle="Signals observed across this employee's reports" />
            <CardBody className="space-y-2">
              {data.behavioral_trends.length === 0 ? (
                <p className="text-sm text-text-muted">No flags recorded.</p>
              ) : (
                data.behavioral_trends.map((t) => (
                  <div key={t.trend} className="flex items-center justify-between rounded-lg bg-bg-elevated px-3 py-2">
                    <span className="text-sm text-text-secondary">{t.trend}</span>
                    <span className="text-sm font-semibold text-text-primary">{t.value}</span>
                  </div>
                ))
              )}
            </CardBody>
          </Card>

          <Card>
            <CardHeader title="Behavioral integrity score" subtitle="This employee vs. company distribution" />
            <CardBody>
              <div className="mb-3 flex items-center gap-3">
                <div className="text-3xl font-bold text-text-primary">{data.my_abi}</div>
                <div className="text-xs text-text-muted">
                  out of 100 · company median{' '}
                  {data.company_abi.length
                    ? data.company_abi[Math.floor(data.company_abi.length / 2)]
                    : '—'}
                </div>
              </div>
              {data.company_abi.length > 0 && (
                <div className="flex h-8 items-end gap-0.5">
                  {data.company_abi.map((score, i) => (
                    <div
                      key={i}
                      className="flex-1 rounded-t"
                      style={{
                        height: `${Math.max(8, score)}%`,
                        background: score === data.my_abi ? CHART_COLORS.accentBright : CHART_COLORS.grid,
                      }}
                      title={`${score}`}
                    />
                  ))}
                </div>
              )}
              {spendByGeo.length > 0 && (
                <>
                  <div className="mt-4 mb-2 text-[11px] font-semibold uppercase tracking-wide text-text-muted">
                    Spend by OE
                  </div>
                  <div className="space-y-1.5">
                    {spendByGeo.map((g) => (
                      <div key={g.oe} className="flex items-center justify-between text-sm">
                        <span className="text-text-secondary">{g.oe}</span>
                        <span className="text-text-primary">{formatMoney(g.spend)}</span>
                      </div>
                    ))}
                  </div>
                </>
              )}
            </CardBody>
          </Card>
        </div>
      )}
    </div>
  )
}
