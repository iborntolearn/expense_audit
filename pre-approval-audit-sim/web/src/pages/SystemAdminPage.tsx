import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { UserPlus, KeyRound, Trash2, ShieldAlert, Save, Plus, Ban } from 'lucide-react'
import {
  adminConfigApi,
  adminUsersApi,
  adminWatchlistApi,
  adminDangerApi,
  emailTemplatesApi,
  type Role,
  type MerchantRegistryRow,
} from '../lib/api'
import { useToast } from '../lib/toast'
import { Card, CardHeader, CardBody } from '../components/ui/Card'
import { Tabs } from '../components/ui/Tabs'
import { Table, Thead, Tbody, Tr, Th, Td } from '../components/ui/Table'
import { Input, Select, Textarea } from '../components/ui/Input'
import { Button } from '../components/ui/Button'
import { RoleBadge, Badge } from '../components/ui/Badge'
import { SkeletonTable } from '../components/ui/Skeleton'
import { CustomSubmissionTab } from '../components/admin/CustomSubmissionTab'
import { EnvironmentTab } from '../components/admin/EnvironmentTab'
import { ConnectorsTab } from '../components/admin/ConnectorsTab'
import { RunBatchTab } from '../components/admin/RunBatchTab'
import { ConcurWebhookTab } from '../components/admin/ConcurWebhookTab'

export function SystemAdminPage() {
  return (
    <div className="animate-in">
      <Tabs
        defaultKey="custom-submission"
        tabs={[
          { key: 'custom-submission', label: 'Concur simulator — custom submission', content: <CustomSubmissionTab /> },
          { key: 'run-batch', label: 'Run audit batch', content: <RunBatchTab /> },
          { key: 'webhook', label: 'Concur simulator — webhook', content: <ConcurWebhookTab /> },
          { key: 'users', label: 'Users', content: <UsersTab /> },
          { key: 'watchlist', label: 'Merchant watchlist', content: <WatchlistTab /> },
          { key: 'email', label: 'Email templates', content: <EmailTemplatesTab /> },
          { key: 'environment', label: 'Environment', content: <EnvironmentTab /> },
          { key: 'connectors', label: 'Connectors', content: <ConnectorsTab /> },
          { key: 'danger', label: 'Reset DB', content: <DangerZoneTab /> },
        ]}
      />
    </div>
  )
}

function UsersTab() {
  const qc = useQueryClient()
  const { push } = useToast()
  const { data: users, isLoading } = useQuery({ queryKey: ['admin-users'], queryFn: adminUsersApi.list })
  const { data: genCfg } = useQuery({
    queryKey: ['admin-config', 'generator', 'users-oe'],
    queryFn: () => adminConfigApi.getGenerator() as Promise<{ oe_codes: string[] }>,
  })
  const oeCodes = genCfg?.oe_codes ?? []

  const [username, setUsername] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [role, setRole] = useState<Role>('user')
  const [password, setPassword] = useState('')
  const [oeCode, setOeCode] = useState('')

  const invalidate = () => qc.invalidateQueries({ queryKey: ['admin-users'] })

  const add = useMutation({
    mutationFn: () => adminUsersApi.add(username, displayName || username, role, password, oeCode || null),
    onSuccess: () => {
      push('success', `User ${username} added.`)
      setUsername('')
      setDisplayName('')
      setPassword('')
      setOeCode('')
      invalidate()
    },
    onError: (e: any) => push('error', e.message ?? 'Add failed'),
  })

  const resetPw = useMutation({
    mutationFn: (vars: { username: string; password: string }) => adminUsersApi.resetPassword(vars.username, vars.password),
    onSuccess: (_, vars) => push('success', `Password reset for ${vars.username}.`),
    onError: (e: any) => push('error', e.message ?? 'Reset failed'),
  })

  const setRoleMut = useMutation({
    mutationFn: (vars: { username: string; role: Role }) => adminUsersApi.setRole(vars.username, vars.role),
    onSuccess: (_, vars) => {
      push('success', `${vars.username} is now ${vars.role}.`)
      invalidate()
    },
    onError: (e: any) => push('error', e.message ?? 'Role change failed'),
  })

  const setOeMut = useMutation({
    mutationFn: (vars: { username: string; oe_code: string | null }) => adminUsersApi.setOe(vars.username, vars.oe_code),
    onSuccess: (_, vars) => {
      push('success', `${vars.username} is now scoped to ${vars.oe_code ?? 'Global'}.`)
      invalidate()
    },
    onError: (e: any) => push('error', e.message ?? 'OE change failed'),
  })

  const remove = useMutation({
    mutationFn: (u: string) => adminUsersApi.remove(u),
    onSuccess: (_, u) => {
      push('success', `User ${u} deleted.`)
      invalidate()
    },
    onError: (e: any) => push('error', e.message ?? 'Delete failed'),
  })

  return (
    <div className="space-y-5">
      <Card>
        <CardHeader title="Accounts" subtitle="Passwords are salted + hashed (PBKDF2-HMAC-SHA256) — never stored in plain text." />
        <CardBody className="pt-0">
          {isLoading ? (
            <SkeletonTable rows={3} />
          ) : (
            <Table>
              <Thead>
                <tr>
                  <Th>Username</Th>
                  <Th>Display name</Th>
                  <Th>Role</Th>
                  <Th>OE</Th>
                  <Th>Actions</Th>
                </tr>
              </Thead>
              <Tbody>
                {users?.map((u) => (
                  <Tr key={u.username}>
                    <Td className="text-text-primary">{u.username}</Td>
                    <Td>{u.display_name}</Td>
                    <Td>
                      <RoleBadge role={u.role} />
                    </Td>
                    <Td>
                      <Select
                        value={u.oe_code ?? ''}
                        onChange={(e) => setOeMut.mutate({ username: u.username, oe_code: e.target.value || null })}
                        className="!mb-0 w-28"
                      >
                        <option value="">Global</option>
                        {oeCodes.map((oe) => (
                          <option key={oe} value={oe}>
                            {oe}
                          </option>
                        ))}
                      </Select>
                    </Td>
                    <Td>
                      <div className="flex flex-wrap items-center gap-1.5">
                        <Select
                          value={u.role}
                          onChange={(e) => setRoleMut.mutate({ username: u.username, role: e.target.value as Role })}
                          className="!mb-0 w-28"
                        >
                          <option value="user">user</option>
                          <option value="admin">admin</option>
                          <option value="auditor">auditor</option>
                        </Select>
                        <ResetPasswordButton username={u.username} onReset={(p) => resetPw.mutate({ username: u.username, password: p })} />
                        <Button variant="danger" size="sm" onClick={() => remove.mutate(u.username)}>
                          <Trash2 className="size-3.5" />
                        </Button>
                      </div>
                    </Td>
                  </Tr>
                ))}
              </Tbody>
            </Table>
          )}
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Add a user" />
        <CardBody className="flex flex-wrap items-end gap-3">
          <Input label="Username" value={username} onChange={(e) => setUsername(e.target.value)} className="w-40" />
          <Input label="Display name" value={displayName} onChange={(e) => setDisplayName(e.target.value)} className="w-44" />
          <Select label="Role" value={role} onChange={(e) => setRole(e.target.value as Role)} className="w-32">
            <option value="user">user</option>
            <option value="admin">admin</option>
            <option value="auditor">auditor</option>
          </Select>
          <Select
            label="OE"
            value={oeCode}
            onChange={(e) => setOeCode(e.target.value)}
            className="w-32"
            hint={role === 'admin' ? '"Global" = super-admin' : undefined}
          >
            <option value="">Global</option>
            {oeCodes.map((oe) => (
              <option key={oe} value={oe}>
                {oe}
              </option>
            ))}
          </Select>
          <Input label="Password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} className="w-44" />
          <Button
            variant="primary"
            onClick={() => add.mutate()}
            loading={add.isPending}
            disabled={!username.trim() || !password}
          >
            <UserPlus className="size-4" /> Add user
          </Button>
        </CardBody>
      </Card>
    </div>
  )
}

function ResetPasswordButton({ username, onReset }: { username: string; onReset: (p: string) => void }) {
  const [open, setOpen] = useState(false)
  const [pw, setPw] = useState('')
  if (!open) {
    return (
      <Button variant="secondary" size="sm" onClick={() => setOpen(true)} title={`Reset password for ${username}`}>
        <KeyRound className="size-3.5" />
      </Button>
    )
  }
  return (
    <div className="flex items-center gap-1">
      <Input value={pw} onChange={(e) => setPw(e.target.value)} placeholder="new password" type="password" className="!mb-0 w-32" />
      <Button
        variant="primary"
        size="sm"
        onClick={() => {
          if (pw) {
            onReset(pw)
            setOpen(false)
            setPw('')
          }
        }}
      >
        Set
      </Button>
    </div>
  )
}

function WatchlistTab() {
  const qc = useQueryClient()
  const { push } = useToast()
  const { data: entries, isLoading } = useQuery({ queryKey: ['admin-watchlist'], queryFn: adminWatchlistApi.list })
  const [name, setName] = useState('')
  const [type, setType] = useState('sanctioned')
  const [reason, setReason] = useState('Simulated watchlist entry')

  const invalidate = () => qc.invalidateQueries({ queryKey: ['admin-watchlist'] })

  const add = useMutation({
    mutationFn: () => adminWatchlistApi.add(name, type, reason),
    onSuccess: () => {
      push('success', `Added ${name} to the watchlist.`)
      setName('')
      invalidate()
    },
    onError: (e: any) => push('error', e.message ?? 'Add failed'),
  })
  const remove = useMutation({
    mutationFn: (n: string) => adminWatchlistApi.remove(n),
    onSuccess: (_, n) => {
      push('success', `Removed ${n}.`)
      invalidate()
    },
    onError: (e: any) => push('error', e.message ?? 'Remove failed'),
  })

  return (
    <div className="space-y-5">
      <Card>
        <CardHeader
          title="Simulated sanctions/PEP watchlist"
          subtitle="Vendor names are matched case-insensitively as a substring — not a real OFAC/PEP data feed."
        />
        <CardBody className="pt-0">
          {isLoading ? (
            <SkeletonTable rows={3} />
          ) : (
            <Table>
              <Thead>
                <tr>
                  <Th>Name</Th>
                  <Th>Type</Th>
                  <Th>Reason</Th>
                  <Th />
                </tr>
              </Thead>
              <Tbody>
                {entries?.map((e) => (
                  <Tr key={e.name}>
                    <Td className="text-text-primary">{e.name}</Td>
                    <Td>{e.type}</Td>
                    <Td>{e.reason}</Td>
                    <Td>
                      <Button variant="danger" size="sm" onClick={() => remove.mutate(e.name)}>
                        <Trash2 className="size-3.5" />
                      </Button>
                    </Td>
                  </Tr>
                ))}
              </Tbody>
            </Table>
          )}
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Add a watchlist entry" />
        <CardBody className="flex flex-wrap items-end gap-3">
          <Input label="Vendor name (or substring)" value={name} onChange={(e) => setName(e.target.value)} className="w-56" />
          <Select label="Type" value={type} onChange={(e) => setType(e.target.value)} className="w-36">
            <option value="sanctioned">sanctioned</option>
            <option value="pep">pep</option>
          </Select>
          <Input label="Reason" value={reason} onChange={(e) => setReason(e.target.value)} className="w-56" />
          <Button variant="primary" onClick={() => add.mutate()} loading={add.isPending} disabled={!name.trim()}>
            <Plus className="size-4" /> Add entry
          </Button>
        </CardBody>
      </Card>

      <MerchantRegistrySection />
    </div>
  )
}

function MerchantRegistrySection() {
  const qc = useQueryClient()
  const { push } = useToast()
  const { data: rows, isLoading } = useQuery({
    queryKey: ['admin-merchant-registry'],
    queryFn: () => adminWatchlistApi.listRegistry(),
  })

  const update = useMutation({
    mutationFn: ({ key, status, risk_tier }: { key: string; status?: string; risk_tier?: string }) =>
      adminWatchlistApi.updateRegistry(key, { status, risk_tier }),
    onSuccess: (_, { key }) => {
      push('success', `Updated ${key}.`)
      qc.invalidateQueries({ queryKey: ['admin-merchant-registry'] })
    },
    onError: (e: any) => push('error', e.message ?? 'Update failed'),
  })

  return (
    <Card>
      <CardHeader
        title="Merchant registry"
        subtitle="Real, DB-backed table the live pipeline actually reads — first/last-seen tracking plus any admin override. The watchlist above is only the one-time bootstrap seed."
      />
      <CardBody className="pt-0">
        {isLoading ? (
          <SkeletonTable rows={3} />
        ) : (
          <Table>
            <Thead>
              <tr>
                <Th>Merchant</Th>
                <Th>Status</Th>
                <Th>Risk tier</Th>
                <Th>Source</Th>
                <Th>Submissions</Th>
                <Th>Last seen</Th>
                <Th>Reason</Th>
              </tr>
            </Thead>
            <Tbody>
              {(rows as MerchantRegistryRow[] | undefined)?.map((r) => (
                <Tr key={r.merchant_key}>
                  <Td className="text-text-primary">{r.display_name}</Td>
                  <Td>
                    <Select
                      value={r.status}
                      onChange={(e) => update.mutate({ key: r.merchant_key, status: e.target.value })}
                      className="w-28"
                    >
                      <option value="clear">clear</option>
                      <option value="watch">watch</option>
                      <option value="blocked">blocked</option>
                    </Select>
                  </Td>
                  <Td>
                    <Select
                      value={r.risk_tier}
                      onChange={(e) => update.mutate({ key: r.merchant_key, risk_tier: e.target.value })}
                      className="w-28"
                    >
                      <option value="low">low</option>
                      <option value="medium">medium</option>
                      <option value="high">high</option>
                    </Select>
                  </Td>
                  <Td>
                    <Badge kind={r.source === 'admin_override' ? 'accent' : 'neutral'}>{r.source}</Badge>
                  </Td>
                  <Td>{r.submission_count}</Td>
                  <Td className="text-text-muted">{(r.last_seen_at || '').slice(0, 10)}</Td>
                  <Td className="max-w-[220px] truncate text-text-muted">{r.reason || '—'}</Td>
                </Tr>
              ))}
              {rows?.length === 0 && (
                <Tr>
                  <Td colSpan={7} className="text-center text-text-muted">
                    No merchants seen yet.
                  </Td>
                </Tr>
              )}
            </Tbody>
          </Table>
        )}
      </CardBody>
    </Card>
  )
}

function EmailTemplatesTab() {
  const qc = useQueryClient()
  const { push } = useToast()
  const { data: templates, isLoading } = useQuery({ queryKey: ['admin-email-templates'], queryFn: emailTemplatesApi.listRaw })
  const [selected, setSelected] = useState<string | null>(null)
  const [subject, setSubject] = useState('')
  const [body, setBody] = useState('')

  const current = templates?.find((t) => t.name === (selected ?? templates?.[0]?.name))

  const pick = (name: string) => {
    const t = templates?.find((x) => x.name === name)
    setSelected(name)
    setSubject(t?.subject ?? '')
    setBody(t?.body ?? '')
  }

  const save = useMutation({
    mutationFn: () => emailTemplatesApi.save(current!.name, subject, body),
    onSuccess: () => {
      push('success', `Saved ${current?.name}.`)
      qc.invalidateQueries({ queryKey: ['admin-email-templates'] })
    },
    onError: (e: any) => push('error', e.message ?? 'Save failed'),
  })

  if (isLoading) return <SkeletonTable rows={4} />
  if (!templates?.length) return <p className="text-sm text-text-muted">No templates configured.</p>

  const activeName = selected ?? templates[0].name
  const active = templates.find((t) => t.name === activeName)!

  return (
    <Card>
      <CardHeader
        title="Email templates"
        subtitle="Simulated — no real SMTP send in this build. Placeholders: {employee_id}, {submission_id}, {amount}, {currency}, {reason}."
      />
      <CardBody className="space-y-3">
        <Select label="Template" value={activeName} onChange={(e) => pick(e.target.value)}>
          {templates.map((t) => (
            <option key={t.name} value={t.name}>
              {t.name}
            </option>
          ))}
        </Select>
        <Input label="Subject" value={selected ? subject : active.subject} onChange={(e) => setSubject(e.target.value)} />
        <Textarea
          label="Body"
          rows={10}
          value={selected ? body : active.body}
          onChange={(e) => setBody(e.target.value)}
        />
        <Button
          variant="primary"
          size="sm"
          onClick={() => {
            if (!selected) {
              setSelected(active.name)
              setSubject(active.subject)
              setBody(active.body)
            }
            save.mutate()
          }}
          loading={save.isPending}
        >
          <Save className="size-3.5" /> Save template
        </Button>
      </CardBody>
    </Card>
  )
}

function DangerZoneTab() {
  const qc = useQueryClient()
  const { push } = useToast()
  const { data: summary, isLoading } = useQuery({ queryKey: ['admin-danger-summary'], queryFn: adminDangerApi.summary })
  const [confirmed, setConfirmed] = useState(false)

  const purge = useMutation({
    mutationFn: adminDangerApi.purge,
    onSuccess: (result) => {
      push('success', `Deleted ${result.rows_deleted} row(s), ${result.blobs_deleted} blob file(s).`)
      setConfirmed(false)
      qc.invalidateQueries({ queryKey: ['admin-danger-summary'] })
    },
    onError: (e: any) => push('error', e.message ?? 'Purge failed'),
  })

  return (
    <Card>
      <CardHeader title="Danger zone" subtitle="Deletes every submission and everything derived from it. Config is untouched." />
      <CardBody className="space-y-4">
        {isLoading ? (
          <SkeletonTable rows={1} />
        ) : (
          <div className="grid grid-cols-3 gap-3">
            <div className="rounded-lg border border-border bg-bg-elevated px-3 py-2.5 text-center">
              <div className="text-lg font-bold text-text-primary">{summary?.submissions}</div>
              <div className="text-[10px] font-semibold uppercase tracking-wider text-text-muted">Submissions</div>
            </div>
            <div className="rounded-lg border border-border bg-bg-elevated px-3 py-2.5 text-center">
              <div className="text-lg font-bold text-text-primary">{summary?.blob_files}</div>
              <div className="text-[10px] font-semibold uppercase tracking-wider text-text-muted">Blob files</div>
            </div>
            <div className="rounded-lg border border-border bg-bg-elevated px-3 py-2.5 text-center">
              <div className="text-lg font-bold text-text-primary">{summary?.checkpoint_present ? 'present' : 'none'}</div>
              <div className="text-[10px] font-semibold uppercase tracking-wider text-text-muted">Checkpoint db</div>
            </div>
          </div>
        )}

        <div className="flex items-center gap-2 rounded-lg border border-error-border bg-error-bg px-3 py-2 text-xs font-semibold text-error-text">
          <ShieldAlert className="size-3.5" /> Danger zone — this cannot be undone
        </div>

        <label className="flex items-center gap-2 text-sm text-text-secondary">
          <input
            type="checkbox"
            checked={confirmed}
            onChange={(e) => setConfirmed(e.target.checked)}
            className="size-4 rounded border-border accent-error"
          />
          I understand this will permanently delete all submissions, decisions, receipt files, and checkpoints
        </label>

        {confirmed && (
          <Button variant="danger" onClick={() => purge.mutate()} loading={purge.isPending}>
            <Ban className="size-4" /> Delete all transactional data
          </Button>
        )}
      </CardBody>
    </Card>
  )
}
