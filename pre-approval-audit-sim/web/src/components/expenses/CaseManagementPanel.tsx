import { useEffect, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { caseStatusApi, type CaseStatus } from '../../lib/api'
import { useAuth } from '../../lib/auth'
import { useToast } from '../../lib/toast'
import { Select, Input } from '../ui/Input'
import { Button } from '../ui/Button'
import { formatMoney } from '../../lib/utils'

const CASE_STATUSES = ['open', 'in_review', 'awaiting_traveller', 'resolved', 'claw_back_pending']

export function CaseManagementPanel({
  sid,
  readOnly,
  caseStatus,
  currency,
}: {
  sid: string
  readOnly: boolean
  caseStatus?: CaseStatus
  currency: string
}) {
  const qc = useQueryClient()
  const { user } = useAuth()
  const { push } = useToast()
  const [status, setStatus] = useState(caseStatus?.status ?? 'open')
  const [recovered, setRecovered] = useState(String(caseStatus?.recovered_amount ?? ''))

  useEffect(() => {
    setStatus(caseStatus?.status ?? 'open')
    setRecovered(caseStatus?.recovered_amount != null ? String(caseStatus.recovered_amount) : '')
  }, [caseStatus])

  const update = useMutation({
    mutationFn: () =>
      caseStatusApi.update(sid, status, recovered ? Number(recovered) : null, user?.username ?? 'REV-1'),
    onSuccess: () => {
      push('success', 'Case updated.')
      qc.invalidateQueries({ queryKey: ['case-status', sid] })
    },
    onError: (e: any) => push('error', e.message ?? 'Update failed'),
  })

  if (readOnly) {
    return (
      <p className="text-sm text-text-secondary">
        Case status: <span className="font-semibold text-text-primary">{caseStatus?.status ?? 'open'}</span>
        {caseStatus?.recovered_amount ? (
          <> · Recovered: {formatMoney(caseStatus.recovered_amount, currency)}</>
        ) : null}
      </p>
    )
  }

  return (
    <div className="flex flex-wrap items-end gap-3">
      <Select label="Case status" value={status} onChange={(e) => setStatus(e.target.value)} className="w-48">
        {CASE_STATUSES.map((s) => (
          <option key={s} value={s}>
            {s.replace(/_/g, ' ')}
          </option>
        ))}
      </Select>
      <Input
        label="Recovered amount (claw-back)"
        type="number"
        min={0}
        step={1}
        value={recovered}
        onChange={(e) => setRecovered(e.target.value)}
        className="w-52"
      />
      <Button variant="secondary" onClick={() => update.mutate()} loading={update.isPending}>
        Update case
      </Button>
    </div>
  )
}
