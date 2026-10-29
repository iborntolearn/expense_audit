import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { RefreshCw } from 'lucide-react'
import { adminEnvironmentApi } from '../../lib/api'
import { useToast } from '../../lib/toast'
import { Card, CardHeader, CardBody } from '../ui/Card'
import { Table, Thead, Tbody, Tr, Th, Td } from '../ui/Table'
import { Badge } from '../ui/Badge'
import { Button } from '../ui/Button'
import { SkeletonTable } from '../ui/Skeleton'

const LABELS: Record<string, string> = {
  mode_requested: 'Mode (requested)',
  live_mode_active: 'Live mode active',
  storage_backend: 'Storage backend',
  engine: 'Orchestration engine',
  vision_provider: 'Vision provider',
  embedding_dim: 'Embedding dim',
  azure_deployment: 'Azure deployment',
  azure_api_version: 'Azure API version',
  azure_endpoint: 'Azure endpoint',
  azure_openai_key_set: 'Azure OpenAI key',
  vision_model: 'Vision model',
  anthropic_key_set: 'Anthropic API key',
  sqlite_path: 'SQLite path',
  checkpoint_path: 'Checkpoint path',
}

const ROW_ORDER = [
  'mode_requested', 'live_mode_active', 'storage_backend', 'engine', 'vision_provider', 'embedding_dim',
  'azure_deployment', 'azure_api_version', 'azure_endpoint', 'azure_openai_key_set',
  'vision_model', 'anthropic_key_set', 'sqlite_path', 'checkpoint_path',
]

function formatValue(key: string, value: unknown): string {
  if (key === 'azure_openai_key_set' || key === 'anthropic_key_set') return value ? 'set' : 'not set'
  if (typeof value === 'boolean') return value ? 'true' : 'false'
  return String(value)
}

export function EnvironmentTab() {
  const qc = useQueryClient()
  const { push } = useToast()
  const { data: env, isLoading } = useQuery({ queryKey: ['admin-environment'], queryFn: adminEnvironmentApi.get })

  const reload = useMutation({
    mutationFn: adminEnvironmentApi.reload,
    onSuccess: (result) => {
      push('success', result.note ?? 'Reloaded.')
      qc.invalidateQueries({ queryKey: ['admin-environment'] })
    },
    onError: (e: any) => push('error', e.message ?? 'Reload failed'),
  })

  return (
    <Card>
      <CardHeader title="Environment" subtitle="Read-only diagnostic snapshot of the active configuration." />
      <CardBody className="space-y-4 pt-0">
        {isLoading || !env ? (
          <SkeletonTable rows={6} />
        ) : (
          <>
            <Table>
              <Thead>
                <tr>
                  <Th>Setting</Th>
                  <Th>Value</Th>
                </tr>
              </Thead>
              <Tbody>
                {ROW_ORDER.filter((k) => env[k as keyof typeof env] !== undefined).map((k) => (
                  <Tr key={k}>
                    <Td className="text-text-primary">{LABELS[k] ?? k}</Td>
                    <Td>{formatValue(k, env[k as keyof typeof env])}</Td>
                  </Tr>
                ))}
              </Tbody>
            </Table>

            {env.live_mode_blocked_reason && (
              <div className="flex items-center gap-2 rounded-lg border border-warning-border bg-warning-bg px-3 py-2 text-xs font-medium text-warning-text">
                <Badge kind="warning">blocked</Badge>
                <code>SIMULATION_MODE=live</code> is set but has no effect — {env.live_mode_blocked_reason}
              </div>
            )}
          </>
        )}

        <div className="border-t border-border pt-4">
          <Button variant="secondary" size="sm" onClick={() => reload.mutate()} loading={reload.isPending}>
            <RefreshCw className="size-3.5" /> Reload configuration & caches
          </Button>
          <p className="mt-2 text-xs text-text-muted">
            Clears the settings cache so the next request re-reads <code>.env</code>. Resources already built into
            this running API process (data layer, pipeline, vision provider) still need a process restart.
          </p>
        </div>
      </CardBody>
    </Card>
  )
}
