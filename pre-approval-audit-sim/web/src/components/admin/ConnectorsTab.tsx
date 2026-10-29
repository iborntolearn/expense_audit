import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { PlugZap } from 'lucide-react'
import { connectorsApi, type ConnectorsConfigInput, type ConnectorsStatus } from '../../lib/api'
import { useToast } from '../../lib/toast'
import { Card, CardHeader, CardBody } from '../ui/Card'
import { Table, Thead, Tbody, Tr, Th, Td } from '../ui/Table'
import { Badge } from '../ui/Badge'
import { Button } from '../ui/Button'
import { Select } from '../ui/Input'
import { SkeletonTable } from '../ui/Skeleton'

type Role = keyof ConnectorsStatus

const ROLE_LABELS: Record<Role, string> = {
  submission_source: 'Expense / travel submissions',
  employee_directory: 'Employee directory',
  finance_master: 'Finance master data',
}

const ROLE_SYSTEMS: Record<Role, string> = {
  submission_source: 'SAP Concur, Cytric',
  employee_directory: 'Workday',
  finance_master: 'Oracle E-Business Suite',
}

const PROVIDER_LABELS: Record<string, string> = {
  simulated: 'Simulated (offline)',
  concur: 'SAP Concur',
  cytric: 'Cytric',
  workday: 'Workday',
  oracle_ebs: 'Oracle E-Business Suite',
}

export function ConnectorsTab() {
  const qc = useQueryClient()
  const { push } = useToast()
  const { data: status, isLoading } = useQuery({ queryKey: ['admin-connectors'], queryFn: connectorsApi.get })
  const [testResults, setTestResults] = useState<Record<string, { ok: boolean; detail: string }>>({})
  const [pendingRole, setPendingRole] = useState<Role | null>(null)

  const setProvider = useMutation({
    mutationFn: (next: ConnectorsConfigInput) => connectorsApi.putConfig(next),
    onSuccess: (result) => {
      push('success', result.note)
      qc.invalidateQueries({ queryKey: ['admin-connectors'] })
    },
    onError: (e: any) => push('error', e.message ?? 'Save failed'),
    onSettled: () => setPendingRole(null),
  })

  const testConnection = useMutation({
    mutationFn: (role: Role) => connectorsApi.test(role),
    onSuccess: (result, role) => {
      setTestResults((prev) => ({ ...prev, [role]: result }))
      push(result.ok ? 'success' : 'error', result.ok ? `${ROLE_LABELS[role]}: connected` : result.detail)
    },
    onError: (e: any, role) => {
      setTestResults((prev) => ({ ...prev, [role]: { ok: false, detail: e.message ?? 'Test failed' } }))
      push('error', e.message ?? 'Test failed')
    },
  })

  function changeProvider(role: Role, provider: string) {
    if (!status) return
    setPendingRole(role)
    setProvider.mutate({
      submission_source: status.submission_source.provider,
      employee_directory: status.employee_directory.provider,
      finance_master: status.finance_master.provider,
      [role]: provider,
    } as ConnectorsConfigInput)
  }

  return (
    <Card>
      <CardHeader
        title="Integration connectors"
        subtitle="Cytric, SAP Concur, Workday, and Oracle E-Business Suite - pick the active provider per role and test the connection. Real credentials go in .env (see the Environment tab)."
      />
      <CardBody className="pt-0">
        {isLoading || !status ? (
          <SkeletonTable rows={3} />
        ) : (
          <Table>
            <Thead>
              <tr>
                <Th>Role</Th>
                <Th>Provider</Th>
                <Th>Status</Th>
                <Th />
              </tr>
            </Thead>
            <Tbody>
              {(Object.keys(status) as Role[]).map((role) => {
                const info = status[role]
                const result = testResults[role]
                const saving = setProvider.isPending && pendingRole === role
                const testing = testConnection.isPending && testConnection.variables === role
                return (
                  <Tr key={role}>
                    <Td className="text-text-primary">
                      {ROLE_LABELS[role]}
                      <div className="text-xs text-text-muted">{ROLE_SYSTEMS[role]}</div>
                    </Td>
                    <Td>
                      <Select
                        value={info.provider}
                        onChange={(e) => changeProvider(role, e.target.value)}
                        disabled={saving}
                        className="w-56"
                      >
                        {info.options.map((opt) => (
                          <option key={opt} value={opt}>
                            {PROVIDER_LABELS[opt] ?? opt}
                          </option>
                        ))}
                      </Select>
                    </Td>
                    <Td>
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge kind={info.configured ? 'success' : 'neutral'}>
                          {info.configured ? 'configured' : 'not configured'}
                        </Badge>
                        {result && (
                          <Badge kind={result.ok ? 'success' : 'error'}>
                            {result.ok ? 'connected' : result.detail}
                          </Badge>
                        )}
                      </div>
                    </Td>
                    <Td>
                      <Button
                        variant="secondary"
                        size="sm"
                        onClick={() => testConnection.mutate(role)}
                        loading={testing}
                      >
                        <PlugZap className="size-3.5" /> Test connection
                      </Button>
                    </Td>
                  </Tr>
                )
              })}
            </Tbody>
          </Table>
        )}
        <p className="mt-4 text-xs text-text-muted">
          Provider changes save to <code>config/connectors.yaml</code> immediately - "Test connection" always builds
          a fresh connector from the current config, so a just-saved change is reflected without an API restart. A
          real (non-simulated) provider can only be tested once live mode is fully unlocked (see the Environment
          tab) - this build ships with that gate off by design.
        </p>
      </CardBody>
    </Card>
  )
}
