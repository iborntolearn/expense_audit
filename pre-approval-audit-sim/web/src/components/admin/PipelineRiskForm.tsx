import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Save, RotateCcw } from 'lucide-react'
import { adminConfigApi } from '../../lib/api'
import { useToast } from '../../lib/toast'
import { Card, CardHeader, CardBody, SectionLabel } from '../ui/Card'
import { Input, Select } from '../ui/Input'
import { Button } from '../ui/Button'
import { Skeleton } from '../ui/Skeleton'
import { JsonConfigEditor } from './JsonConfigEditor'

export interface PipelineData {
  engine: string
  node_timeouts: Record<string, number>
  retry: { max_retries: number; backoff_seconds: number[] }
  extraction: {
    provider: string
    confidence_cutoff: number
    simulation: {
      base_confidence: number
      error_rate: number
      illegible_rate: number
      low_conf_range: number[]
      illegible_conf_max: number
    }
  }
  verification: {
    subtotal_tolerance_pct: number
    duplicate_similarity_threshold: number
    duplicate_top_k: number
    duplicate_amount_tolerance_pct: number
    duplicate_require_same_employee: boolean
    velocity_window_days: number
    velocity_count_threshold: number
    split_window_days: number
    // Statistical peer-group amount-outlier detection - edited in the
    // Statistical rules tab (StatisticalRulesForm.tsx), not here, but part
    // of the same pipeline.yaml blob so it round-trips through this form's
    // fetch/save cycle untouched.
    peer_outlier: {
      enabled: boolean
      z_score_threshold: number
      min_peer_sample_size: number
    }
  }
  risk: {
    weights: Record<string, number>
    auto_approve_cutoff: number
    auto_reject_cutoff: number
    model_version: string
  }
}

const NODE_LABELS: Record<string, string> = {
  ingest: 'Ingest',
  extraction: 'Extraction',
  verification: 'Verification',
  policy: 'Policy',
  risk_scoring: 'Risk scoring',
  decision_writeback: 'Decision write-back',
}

const WEIGHT_LABELS: Record<string, string> = {
  policy_violation: 'Policy violation',
  duplicate_match: 'Duplicate match',
  authenticity_flag: 'Authenticity flag',
  subtotal_variance: 'Subtotal variance',
  low_confidence: 'Low confidence',
  velocity_flag: 'Velocity flag',
  split_transaction_flag: 'Split-transaction flag',
  merchant_blocklist: 'Merchant blocklist',
  compliance_cumulative: 'Compliance cumulative',
  forensics_strong_signal: 'Strong forensics signal',
  peer_amount_outlier: 'Peer-group amount outlier',
}

export function PipelineRiskForm({ oe }: { oe?: string } = {}) {
  const qc = useQueryClient()
  const { push } = useToast()
  const queryKey = ['admin-config', 'pipeline', oe ?? 'base']
  const { data, isLoading } = useQuery({ queryKey, queryFn: () => adminConfigApi.getPipeline(oe) })
  const [form, setForm] = useState<PipelineData | null>(null)

  useEffect(() => {
    if (data) setForm(data as PipelineData)
  }, [data])

  const save = useMutation({
    mutationFn: () => adminConfigApi.putPipeline(form as unknown as Record<string, any>, oe),
    onSuccess: () => {
      push('success', `Pipeline config saved${oe ? ` for ${oe}` : ''}.`)
      qc.invalidateQueries({ queryKey })
    },
    onError: (e: any) => push('error', e.message ?? 'Save failed'),
  })

  if (isLoading || !form) return <Skeleton className="h-96 rounded-xl" />

  return (
    <div className="space-y-5">
      <Card>
        <CardHeader title="Orchestration" subtitle="config/pipeline.yaml — engine, per-node timeouts, and retry policy." />
        <CardBody className="space-y-5">
          {oe && (
            <p className="rounded-lg border border-warning-border bg-warning-bg px-3 py-2 text-xs text-warning-text">
              Engine, node timeouts, and retry policy are process topology — fixed for the life of the running API
              process from the base config only. Saving them here under a {oe} override stores the value, but it
              won't take effect until the process restarts with that override wired into startup (not yet
              implemented). Verification and Risk scoring below <b>do</b> take effect on the very next submission.
            </p>
          )}
          <div className="grid grid-cols-2 gap-3">
            <Select
              label="Engine"
              value={form.engine}
              onChange={(e) => setForm({ ...form, engine: e.target.value })}
            >
              <option value="langgraph">langgraph</option>
              <option value="sequential">sequential</option>
            </Select>
            <Input
              label="Risk model version"
              value={form.risk.model_version}
              onChange={(e) => setForm({ ...form, risk: { ...form.risk, model_version: e.target.value } })}
            />
          </div>

          <div>
            <SectionLabel>Node timeouts (seconds)</SectionLabel>
            <div className="grid grid-cols-3 gap-3">
              {Object.entries(form.node_timeouts).map(([node, val]) => (
                <Input
                  key={node}
                  label={NODE_LABELS[node] ?? node}
                  type="number" step={1} min={0}
                  value={val}
                  onChange={(e) =>
                    setForm({ ...form, node_timeouts: { ...form.node_timeouts, [node]: Number(e.target.value) } })
                  }
                />
              ))}
            </div>
          </div>

          <div>
            <SectionLabel>Retry policy</SectionLabel>
            <div className="grid grid-cols-2 gap-3">
              <Input
                label="Max retries"
                type="number" step={1} min={0}
                value={form.retry.max_retries}
                onChange={(e) => setForm({ ...form, retry: { ...form.retry, max_retries: Number(e.target.value) } })}
              />
              <Input
                label="Backoff seconds (comma-separated, one per retry)"
                value={form.retry.backoff_seconds.join(', ')}
                onChange={(e) =>
                  setForm({
                    ...form,
                    retry: {
                      ...form.retry,
                      backoff_seconds: e.target.value.split(',').map((s) => Number(s.trim())).filter((n) => !Number.isNaN(n)),
                    },
                  })
                }
              />
            </div>
          </div>
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Extraction (vision)" subtitle="Provider and confidence cutoff — simulation parameters only apply when provider is 'simulated'." />
        <CardBody className="space-y-5">
          <div className="grid grid-cols-2 gap-3">
            <Select
              label="Provider"
              value={form.extraction.provider}
              onChange={(e) => setForm({ ...form, extraction: { ...form.extraction, provider: e.target.value } })}
              hint={oe ? `Bound at process startup — a saved ${oe} override has no live effect until restart.` : undefined}
            >
              <option value="simulated">simulated</option>
              <option value="azure_openai">azure_openai</option>
              <option value="anthropic">anthropic</option>
            </Select>
            <Input
              label="Confidence cutoff"
              type="number" step={0.01} min={0} max={1}
              value={form.extraction.confidence_cutoff}
              onChange={(e) =>
                setForm({ ...form, extraction: { ...form.extraction, confidence_cutoff: Number(e.target.value) } })
              }
              hint={oe ? `Live — used by Risk scoring's low-confidence signal for every ${oe} submission.` : undefined}
            />
          </div>

          <div>
            <SectionLabel>Simulation parameters</SectionLabel>
            <div className="grid grid-cols-2 gap-3">
              <Input
                label="Base confidence"
                type="number" step={0.01} min={0} max={1}
                value={form.extraction.simulation.base_confidence}
                onChange={(e) =>
                  setForm({
                    ...form,
                    extraction: {
                      ...form.extraction,
                      simulation: { ...form.extraction.simulation, base_confidence: Number(e.target.value) },
                    },
                  })
                }
              />
              <Input
                label="Error rate"
                type="number" step={0.01} min={0} max={1}
                value={form.extraction.simulation.error_rate}
                onChange={(e) =>
                  setForm({
                    ...form,
                    extraction: {
                      ...form.extraction,
                      simulation: { ...form.extraction.simulation, error_rate: Number(e.target.value) },
                    },
                  })
                }
              />
              <Input
                label="Illegible rate"
                type="number" step={0.01} min={0} max={1}
                value={form.extraction.simulation.illegible_rate}
                onChange={(e) =>
                  setForm({
                    ...form,
                    extraction: {
                      ...form.extraction,
                      simulation: { ...form.extraction.simulation, illegible_rate: Number(e.target.value) },
                    },
                  })
                }
              />
              <Input
                label="Illegible confidence max"
                type="number" step={0.01} min={0} max={1}
                value={form.extraction.simulation.illegible_conf_max}
                onChange={(e) =>
                  setForm({
                    ...form,
                    extraction: {
                      ...form.extraction,
                      simulation: { ...form.extraction.simulation, illegible_conf_max: Number(e.target.value) },
                    },
                  })
                }
              />
              <Input
                label="Low-confidence range — min"
                type="number" step={0.01} min={0} max={1}
                value={form.extraction.simulation.low_conf_range[0]}
                onChange={(e) =>
                  setForm({
                    ...form,
                    extraction: {
                      ...form.extraction,
                      simulation: {
                        ...form.extraction.simulation,
                        low_conf_range: [Number(e.target.value), form.extraction.simulation.low_conf_range[1]],
                      },
                    },
                  })
                }
              />
              <Input
                label="Low-confidence range — max"
                type="number" step={0.01} min={0} max={1}
                value={form.extraction.simulation.low_conf_range[1]}
                onChange={(e) =>
                  setForm({
                    ...form,
                    extraction: {
                      ...form.extraction,
                      simulation: {
                        ...form.extraction.simulation,
                        low_conf_range: [form.extraction.simulation.low_conf_range[0], Number(e.target.value)],
                      },
                    },
                  })
                }
              />
            </div>
          </div>
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Verification" subtitle="Subtotal tolerance, duplicate detection, and velocity/split-transaction detection (BR-TE-AU-19)." />
        <CardBody>
          <div className="grid grid-cols-2 gap-3">
            <Input
              label="Subtotal tolerance %"
              type="number" step={0.1} min={0}
              value={form.verification.subtotal_tolerance_pct}
              onChange={(e) =>
                setForm({ ...form, verification: { ...form.verification, subtotal_tolerance_pct: Number(e.target.value) } })
              }
            />
            <Input
              label="Duplicate similarity threshold"
              type="number" step={0.01} min={0} max={1}
              value={form.verification.duplicate_similarity_threshold}
              onChange={(e) =>
                setForm({
                  ...form,
                  verification: { ...form.verification, duplicate_similarity_threshold: Number(e.target.value) },
                })
              }
            />
            <Input
              label="Duplicate top-K"
              type="number" step={1} min={1}
              value={form.verification.duplicate_top_k}
              onChange={(e) =>
                setForm({ ...form, verification: { ...form.verification, duplicate_top_k: Number(e.target.value) } })
              }
            />
            <Input
              label="Duplicate amount tolerance %"
              type="number" step={0.1} min={0}
              value={form.verification.duplicate_amount_tolerance_pct}
              onChange={(e) =>
                setForm({
                  ...form,
                  verification: { ...form.verification, duplicate_amount_tolerance_pct: Number(e.target.value) },
                })
              }
            />
            <Input
              label="Velocity window (days)"
              type="number" step={1} min={1}
              value={form.verification.velocity_window_days}
              onChange={(e) =>
                setForm({ ...form, verification: { ...form.verification, velocity_window_days: Number(e.target.value) } })
              }
            />
            <Input
              label="Velocity count threshold"
              type="number" step={1} min={1}
              value={form.verification.velocity_count_threshold}
              onChange={(e) =>
                setForm({
                  ...form,
                  verification: { ...form.verification, velocity_count_threshold: Number(e.target.value) },
                })
              }
            />
            <Input
              label="Split-transaction window (days)"
              type="number" step={1} min={1}
              value={form.verification.split_window_days}
              onChange={(e) =>
                setForm({ ...form, verification: { ...form.verification, split_window_days: Number(e.target.value) } })
              }
            />
          </div>
          <label className="mt-3 flex items-center gap-2 text-sm text-text-secondary">
            <input
              type="checkbox"
              checked={form.verification.duplicate_require_same_employee}
              onChange={(e) =>
                setForm({
                  ...form,
                  verification: { ...form.verification, duplicate_require_same_employee: e.target.checked },
                })
              }
              className="size-4 rounded border-border accent-accent"
            />
            Require same employee for a duplicate match
          </label>
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Risk scoring" subtitle="Signal weights and auto-approve/auto-reject cutoffs." />
        <CardBody className="space-y-5">
          <div className="grid grid-cols-2 gap-3">
            <Input
              label="Auto-approve cutoff"
              type="number" step={0.01} min={0} max={1}
              value={form.risk.auto_approve_cutoff}
              onChange={(e) => setForm({ ...form, risk: { ...form.risk, auto_approve_cutoff: Number(e.target.value) } })}
            />
            <Input
              label="Auto-reject cutoff"
              type="number" step={0.01} min={0} max={1}
              value={form.risk.auto_reject_cutoff}
              onChange={(e) => setForm({ ...form, risk: { ...form.risk, auto_reject_cutoff: Number(e.target.value) } })}
            />
          </div>
          <div>
            <SectionLabel>Signal weights</SectionLabel>
            <div className="grid grid-cols-3 gap-3">
              {Object.entries(form.risk.weights).map(([signal, val]) => (
                <Input
                  key={signal}
                  label={WEIGHT_LABELS[signal] ?? signal}
                  type="number" step={0.05} min={0} max={1}
                  value={val}
                  onChange={(e) =>
                    setForm({ ...form, risk: { ...form.risk, weights: { ...form.risk.weights, [signal]: Number(e.target.value) } } })
                  }
                />
              ))}
            </div>
          </div>
        </CardBody>
      </Card>

      <div className="flex gap-2">
        <Button variant="primary" size="sm" onClick={() => save.mutate()} loading={save.isPending}>
          <Save className="size-3.5" /> Save
        </Button>
        <Button variant="secondary" size="sm" onClick={() => data && setForm(data as PipelineData)}>
          <RotateCcw className="size-3.5" /> Reset
        </Button>
      </div>

      <details className="rounded-lg border border-border">
        <summary className="cursor-pointer px-4 py-3 text-sm font-medium text-text-muted">
          Advanced: raw YAML (JSON)
        </summary>
        <div className="border-t border-border p-4">
          <JsonConfigEditor
            queryKey={queryKey}
            fetcher={() => adminConfigApi.getPipeline(oe)}
            saver={(data) => adminConfigApi.putPipeline(data, oe)}
            title="Pipeline config"
          />
        </div>
      </details>
    </div>
  )
}
