import { useEffect, useState } from 'react'
import { useMutation, useQueries } from '@tanstack/react-query'
import { Save } from 'lucide-react'
import { adminConfigApi } from '../lib/api'
import { useAuth } from '../lib/auth'
import { useToast } from '../lib/toast'
import { Card, CardHeader, CardBody } from '../components/ui/Card'
import { Tabs } from '../components/ui/Tabs'
import { Input } from '../components/ui/Input'
import { Button } from '../components/ui/Button'
import { JsonConfigEditor } from '../components/admin/JsonConfigEditor'
import { ThresholdsForm } from '../components/admin/ThresholdsForm'
import { PipelineRiskForm } from '../components/admin/PipelineRiskForm'
import { PolicyRulesForm } from '../components/admin/PolicyRulesForm'
import { StatisticalRulesForm } from '../components/admin/StatisticalRulesForm'

const ENV_KEYS = [
  'AZURE_OPENAI_KEY',
  'AZURE_OPENAI_ENDPOINT',
  'AZURE_DEPLOYMENT_NAME',
  'AZURE_API_VERSION',
  'ANTHROPIC_API_KEY',
  'LLM_VISION_MODEL',
]

export function SettingsPage() {
  const { hasRole, user, oeScope } = useAuth()
  const isGlobalAdmin = hasRole('admin') && user?.oe_code == null
  const scope = oeScope || undefined

  return (
    <div className="animate-in space-y-4">
      {isGlobalAdmin && (
        <div className="rounded-lg border border-info-border bg-info-bg px-3 py-2 text-xs text-info-text">
          {scope ? (
            <>
              Editing the <b>{scope}</b> override — use the OE switcher (top right) to edit the base config or
              another OE instead.
            </>
          ) : (
            <>Editing the base config (applies to every OE without an override) — use the OE switcher (top right) to edit one OE's override instead.</>
          )}
        </div>
      )}
      {!isGlobalAdmin && user?.oe_code && (
        <div className="rounded-lg border border-info-border bg-info-bg px-3 py-2 text-xs text-info-text">
          Editing settings scoped to your OE: <b>{user.oe_code}</b>
        </div>
      )}
      <Tabs
        defaultKey="llm"
        tabs={[
          { key: 'llm', label: 'LLM & extraction', content: <LlmEnvTab /> },
          { key: 'thresholds', label: 'Thresholds', content: <ThresholdsForm oe={scope} /> },
          { key: 'risk', label: 'Risk & pipeline', content: <PipelineRiskForm oe={scope} /> },
          { key: 'rules', label: 'Business rules', content: <PolicyRulesForm oe={scope} /> },
          { key: 'statistical', label: 'Statistical rules', content: <StatisticalRulesForm oe={scope} /> },
          {
            key: 'generator',
            label: 'Data generator',
            content: (
              <JsonConfigEditor
                queryKey={['admin-config', 'generator', scope ?? 'base']}
                fetcher={() => adminConfigApi.getGenerator(scope)}
                saver={(data) => adminConfigApi.putGenerator(data, scope)}
                title="Data generator"
                subtitle="config/generator.yaml — synthetic-data generation for test batches."
              />
            ),
          },
        ]}
      />
    </div>
  )
}

function LlmEnvTab() {
  const { push } = useToast()
  const [values, setValues] = useState<Record<string, string>>({})
  const [loaded, setLoaded] = useState(false)

  const results = useQueries({
    queries: ENV_KEYS.map((key) => ({ queryKey: ['admin-env', key], queryFn: () => adminConfigApi.getEnv(key) })),
  })

  useEffect(() => {
    if (!loaded && results.every((r) => r.data)) {
      const v: Record<string, string> = {}
      results.forEach((r, i) => {
        v[ENV_KEYS[i]] = r.data?.value ?? ''
      })
      setValues(v)
      setLoaded(true)
    }
  }, [results, loaded])

  const save = useMutation({
    mutationFn: () => adminConfigApi.putEnv(values),
    onSuccess: () => push('success', 'Environment settings saved. Restart the API process to fully apply.'),
    onError: (e: any) => push('error', e.message ?? 'Save failed'),
  })

  return (
    <Card>
      <CardHeader
        title="LLM & extraction provider"
        subtitle="API keys / model settings (.env) — extraction.provider itself is set in the Risk & pipeline tab."
      />
      <CardBody className="space-y-3">
        {ENV_KEYS.map((key) => (
          <Input
            key={key}
            label={key}
            type={key.includes('KEY') ? 'password' : 'text'}
            value={values[key] ?? ''}
            onChange={(e) => setValues((v) => ({ ...v, [key]: e.target.value }))}
          />
        ))}
        <Button variant="primary" size="sm" onClick={() => save.mutate()} loading={save.isPending}>
          <Save className="size-3.5" /> Save
        </Button>
        <p className="text-xs text-text-muted">
          Anything already baked into the running API process (data layer, pipeline, vision provider) needs a
          process restart to fully pick up a changed value here.
        </p>
      </CardBody>
    </Card>
  )
}
