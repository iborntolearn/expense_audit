import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Save, RotateCcw } from 'lucide-react'
import { adminConfigApi } from '../../lib/api'
import { useToast } from '../../lib/toast'
import { Card, CardHeader, CardBody, SectionLabel } from '../ui/Card'
import { Input } from '../ui/Input'
import { Button } from '../ui/Button'
import { Skeleton } from '../ui/Skeleton'
import { JsonConfigEditor } from './JsonConfigEditor'

interface Thresholds {
  extraction: { field_accuracy_min: number }
  duplicate_detection: { recall_min: number; false_positive_rate_max: number }
  latency: { extraction_p95_seconds_max: number; pipeline_p95_seconds_max: number }
  confidence: { min_accuracy_gap: number; low_confidence_cutoff: number }
}

export function ThresholdsForm({ oe }: { oe?: string } = {}) {
  const qc = useQueryClient()
  const { push } = useToast()
  const queryKey = ['admin-config', 'thresholds', oe ?? 'base']
  const { data, isLoading } = useQuery({ queryKey, queryFn: () => adminConfigApi.getThresholds(oe) })
  const [form, setForm] = useState<Thresholds | null>(null)

  useEffect(() => {
    if (data) setForm(data as Thresholds)
  }, [data])

  const save = useMutation({
    mutationFn: () => adminConfigApi.putThresholds(form as unknown as Record<string, any>, oe),
    onSuccess: () => {
      push('success', `Thresholds saved${oe ? ` for ${oe}` : ''}.`)
      qc.invalidateQueries({ queryKey })
    },
    onError: (e: any) => push('error', e.message ?? 'Save failed'),
  })

  if (isLoading || !form) return <Skeleton className="h-64 rounded-xl" />

  const num = (path: (f: Thresholds) => number, setPath: (f: Thresholds, v: number) => Thresholds) => ({
    value: path(form),
    onChange: (e: React.ChangeEvent<HTMLInputElement>) => setForm(setPath(form, Number(e.target.value))),
  })

  return (
    <div className="space-y-5">
      <Card>
        <CardHeader
          title="Accuracy & latency gate thresholds"
          subtitle="Read by the reporting harness — informative in simulation mode, not an auto-gate (the real gate is real-data validation, deferred)."
        />
        <CardBody className="space-y-5">
          <div>
            <SectionLabel>Extraction</SectionLabel>
            <Input
              label="Field-level accuracy minimum (vendor / date / amount)"
              type="number" step={0.01} min={0} max={1}
              {...num(
                (f) => f.extraction.field_accuracy_min,
                (f, v) => ({ ...f, extraction: { ...f.extraction, field_accuracy_min: v } }),
              )}
            />
          </div>

          <div>
            <SectionLabel>Duplicate detection</SectionLabel>
            <div className="grid grid-cols-2 gap-3">
              <Input
                label="Recall minimum"
                type="number" step={0.01} min={0} max={1}
                {...num(
                  (f) => f.duplicate_detection.recall_min,
                  (f, v) => ({ ...f, duplicate_detection: { ...f.duplicate_detection, recall_min: v } }),
                )}
              />
              <Input
                label="False-positive rate maximum"
                type="number" step={0.01} min={0} max={1}
                {...num(
                  (f) => f.duplicate_detection.false_positive_rate_max,
                  (f, v) => ({ ...f, duplicate_detection: { ...f.duplicate_detection, false_positive_rate_max: v } }),
                )}
              />
            </div>
          </div>

          <div>
            <SectionLabel>Latency</SectionLabel>
            <div className="grid grid-cols-2 gap-3">
              <Input
                label="Extraction p95 (seconds, per receipt)"
                type="number" step={1} min={0}
                {...num(
                  (f) => f.latency.extraction_p95_seconds_max,
                  (f, v) => ({ ...f, latency: { ...f.latency, extraction_p95_seconds_max: v } }),
                )}
              />
              <Input
                label="Pipeline p95 (seconds, end-to-end SLA)"
                type="number" step={1} min={0}
                {...num(
                  (f) => f.latency.pipeline_p95_seconds_max,
                  (f, v) => ({ ...f, latency: { ...f.latency, pipeline_p95_seconds_max: v } }),
                )}
              />
            </div>
          </div>

          <div>
            <SectionLabel>Confidence</SectionLabel>
            <div className="grid grid-cols-2 gap-3">
              <Input
                label="Minimum accuracy gap (low vs. high confidence)"
                type="number" step={0.01} min={0} max={1}
                {...num(
                  (f) => f.confidence.min_accuracy_gap,
                  (f, v) => ({ ...f, confidence: { ...f.confidence, min_accuracy_gap: v } }),
                )}
              />
              <Input
                label="Low-confidence cutoff"
                type="number" step={0.01} min={0} max={1}
                {...num(
                  (f) => f.confidence.low_confidence_cutoff,
                  (f, v) => ({ ...f, confidence: { ...f.confidence, low_confidence_cutoff: v } }),
                )}
              />
            </div>
          </div>

          <div className="flex gap-2 border-t border-border pt-4">
            <Button variant="primary" size="sm" onClick={() => save.mutate()} loading={save.isPending}>
              <Save className="size-3.5" /> Save
            </Button>
            <Button variant="secondary" size="sm" onClick={() => data && setForm(data as Thresholds)}>
              <RotateCcw className="size-3.5" /> Reset
            </Button>
          </div>
        </CardBody>
      </Card>

      <details className="rounded-lg border border-border">
        <summary className="cursor-pointer px-4 py-3 text-sm font-medium text-text-muted">
          Advanced: raw YAML (JSON)
        </summary>
        <div className="border-t border-border p-4">
          <JsonConfigEditor
            queryKey={queryKey}
            fetcher={() => adminConfigApi.getThresholds(oe)}
            saver={(data) => adminConfigApi.putThresholds(data, oe)}
            title="Thresholds"
          />
        </div>
      </details>
    </div>
  )
}
