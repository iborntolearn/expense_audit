import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Save, RotateCcw, TrendingUp } from 'lucide-react'
import { adminConfigApi } from '../../lib/api'
import { useToast } from '../../lib/toast'
import { Card, CardHeader, CardBody } from '../ui/Card'
import { Input } from '../ui/Input'
import { Button } from '../ui/Button'
import { Skeleton } from '../ui/Skeleton'
import type { PipelineData } from './PipelineRiskForm'

// Catalog of statistical/anomaly-detection rules - distinct from the flat,
// author-set thresholds in the "Business rules" tab (policy_rules.yaml):
// each of these compares a submission against a LIVE-COMPUTED population
// baseline (mean/stddev queried from AuditStore) rather than a fixed number.
// Today there is exactly one; new statistical checks should be added here
// as their own card, following the same enabled/config/description shape.
interface StatisticalRuleDef {
  key: 'peer_outlier'
  name: string
  description: string
}

const STATISTICAL_RULES: StatisticalRuleDef[] = [
  {
    key: 'peer_outlier',
    name: 'Peer-group amount outlier',
    description:
      "Flags a submission's category spend when it's far above the live-computed average for every OTHER " +
      'employee in the same operating entity + category - catches spend that never breaches a flat authored ' +
      "cap but is still statistically unusual against how peers actually spend (e.g. an employee who's always " +
      'just under the cap, every time, while peers average far less).',
  },
]

export function StatisticalRulesForm({ oe }: { oe?: string } = {}) {
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
      push('success', `Statistical rules saved${oe ? ` for ${oe}` : ''}.`)
      qc.invalidateQueries({ queryKey })
    },
    onError: (e: any) => push('error', e.message ?? 'Save failed'),
  })

  if (isLoading || !form) return <Skeleton className="h-72 rounded-xl" />

  return (
    <div className="space-y-5">
      {STATISTICAL_RULES.map((def) => {
        const cfg = form.verification.peer_outlier
        return (
          <Card key={def.key}>
            <CardHeader
              title={
                <span className="flex items-center gap-2">
                  <TrendingUp className="size-4 text-accent-bright" />
                  {def.name}
                </span>
              }
              subtitle={def.description}
              action={
                <label className="flex items-center gap-2 text-sm text-text-secondary">
                  <input
                    type="checkbox"
                    checked={cfg.enabled}
                    onChange={(e) =>
                      setForm({
                        ...form,
                        verification: {
                          ...form.verification,
                          peer_outlier: { ...cfg, enabled: e.target.checked },
                        },
                      })
                    }
                    className="size-4 rounded border-border accent-accent"
                  />
                  {cfg.enabled ? 'Enabled' : 'Disabled'}
                </label>
              }
            />
            <CardBody className="space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <Input
                  label="Z-score threshold"
                  type="number" step={0.1} min={0}
                  value={cfg.z_score_threshold}
                  disabled={!cfg.enabled}
                  hint="How many standard deviations above the peer average before flagging."
                  onChange={(e) =>
                    setForm({
                      ...form,
                      verification: {
                        ...form.verification,
                        peer_outlier: { ...cfg, z_score_threshold: Number(e.target.value) },
                      },
                    })
                  }
                />
                <Input
                  label="Minimum peer sample size"
                  type="number" step={1} min={1}
                  value={cfg.min_peer_sample_size}
                  disabled={!cfg.enabled}
                  hint="Guards against flagging off a thin/near-empty baseline (e.g. a new OE or category)."
                  onChange={(e) =>
                    setForm({
                      ...form,
                      verification: {
                        ...form.verification,
                        peer_outlier: { ...cfg, min_peer_sample_size: Number(e.target.value) },
                      },
                    })
                  }
                />
              </div>
            </CardBody>
          </Card>
        )
      })}

      <div className="flex gap-2">
        <Button variant="primary" size="sm" onClick={() => save.mutate()} loading={save.isPending}>
          <Save className="size-3.5" /> Save
        </Button>
        <Button variant="secondary" size="sm" onClick={() => data && setForm(data as PipelineData)}>
          <RotateCcw className="size-3.5" /> Reset
        </Button>
      </div>
    </div>
  )
}
