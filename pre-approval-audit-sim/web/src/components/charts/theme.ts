export const CHART_COLORS = {
  accent: '#3b7be8',
  accentBright: '#60a5fa',
  purple: '#8b5cf6',
  success: '#22c55e',
  warning: '#f59e0b',
  error: '#ef4444',
  grid: '#232c3e',
  axis: '#56698a',
  tooltipBg: '#161c2b',
  tooltipBorder: '#232c3e',
}

export const PIE_PALETTE = ['#3b7be8', '#8b5cf6', '#22c55e', '#f59e0b', '#ef4444', '#60a5fa', '#a78bfa']

export const tooltipStyle = {
  contentStyle: {
    background: CHART_COLORS.tooltipBg,
    border: `1px solid ${CHART_COLORS.tooltipBorder}`,
    borderRadius: 10,
    fontSize: 12,
    color: '#eef2fb',
    boxShadow: '0 12px 40px -8px rgba(0,0,0,0.5)',
  },
  labelStyle: { color: '#93a5c4', marginBottom: 4, fontWeight: 600 },
  itemStyle: { color: '#eef2fb' },
}

export const axisStyle = {
  tick: { fill: CHART_COLORS.axis, fontSize: 11 },
  axisLine: { stroke: CHART_COLORS.grid },
  tickLine: { stroke: CHART_COLORS.grid },
}
