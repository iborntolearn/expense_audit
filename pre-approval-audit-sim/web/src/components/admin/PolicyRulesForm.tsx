import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus, Trash2, Save, Search } from 'lucide-react'
import { adminConfigApi } from '../../lib/api'
import { useToast } from '../../lib/toast'
import { Card, CardHeader, CardBody } from '../ui/Card'
import { Input, Select, Textarea } from '../ui/Input'
import { Button } from '../ui/Button'
import { Badge } from '../ui/Badge'
import { Table, Thead, Tbody, Tr, Th, Td, EmptyState } from '../ui/Table'
import { Sheet } from '../ui/Sheet'
import { Skeleton } from '../ui/Skeleton'
import { AmountMapEditor } from './AmountMapEditor'
import { JsonConfigEditor } from './JsonConfigEditor'

type RuleType =
  | 'amount_cap'
  | 'receipt_required_above'
  | 'prohibited_category'
  | 'weekend_spend_flag'
  | 'round_amount_flag'
  | 'tax_ratio_check'
  | 'late_submission_flag'
  | 'currency_mismatch_flag'
  | 'cumulative_amount_cap'

interface Rule {
  id: string
  description: string
  type: RuleType
  enabled?: boolean
  applies_to: { category?: string; oe_code?: string }
  cap?: Record<string, number>
  threshold?: Record<string, number>
  min_ratio?: number
  max_ratio?: number
  max_days?: number
  window_days?: number
}

interface PolicyData {
  rule_version: string
  rules: Rule[]
}

const RULE_TYPE_INFO: Record<RuleType, { label: string; hint: string }> = {
  amount_cap: { label: 'Amount cap', hint: 'Per-line amount cap, by currency.' },
  receipt_required_above: { label: 'Receipt required above', hint: 'Requires a receipt at/above this amount, by currency.' },
  prohibited_category: { label: 'Prohibited category', hint: 'Always fails — no additional parameters.' },
  weekend_spend_flag: { label: 'Weekend spend flag', hint: 'Flags Saturday/Sunday transaction dates — no additional parameters.' },
  round_amount_flag: { label: 'Round amount flag', hint: 'Flags suspiciously round amounts at/above this threshold, by currency.' },
  tax_ratio_check: { label: 'Tax ratio check', hint: 'Flags a tax/amount ratio outside this band.' },
  late_submission_flag: { label: 'Late submission flag', hint: 'Flags a submission filed more than N days after the transaction.' },
  currency_mismatch_flag: { label: 'Currency mismatch flag', hint: "Flags a receipt currency that doesn't match the submission currency — no additional parameters." },
  cumulative_amount_cap: { label: 'Cumulative amount cap', hint: 'Rolling-window cap across all of one employee\'s submissions, by currency.' },
}

function blankRule(): Rule {
  return { id: '', description: '', type: 'amount_cap', enabled: true, applies_to: {}, cap: {} }
}

export function PolicyRulesForm({ oe }: { oe?: string } = {}) {
  const qc = useQueryClient()
  const { push } = useToast()
  const queryKey = ['admin-config', 'policy', oe ?? 'all']
  const { data, isLoading } = useQuery({ queryKey, queryFn: () => adminConfigApi.getPolicy(oe) })
  const [form, setForm] = useState<PolicyData | null>(null)
  const [search, setSearch] = useState('')
  const [editing, setEditing] = useState<{ index: number; rule: Rule; isNew: boolean } | null>(null)

  useEffect(() => {
    if (data) setForm(data as PolicyData)
  }, [data])

  const save = useMutation({
    mutationFn: (next: PolicyData) => adminConfigApi.putPolicy(next as unknown as Record<string, any>, oe),
    onSuccess: () => {
      push('success', `Business rules saved${oe ? ` for ${oe}` : ''}.`)
      qc.invalidateQueries({ queryKey })
    },
    onError: (e: any) => push('error', e.message ?? 'Save failed'),
  })

  if (isLoading || !form) return <Skeleton className="h-96 rounded-xl" />

  const filtered = form.rules.filter((r) => {
    const q = search.toLowerCase()
    return !q || r.id.toLowerCase().includes(q) || r.description.toLowerCase().includes(q) || r.type.includes(q)
  })

  function openEdit(index: number) {
    setEditing({ index, rule: { ...form!.rules[index] }, isNew: false })
  }
  function openAdd() {
    // Editing scoped to one OE: a new rule defaults to that OE rather than
    // "any OE", since that's almost always what someone editing one
    // country's rules intends.
    setEditing({ index: form!.rules.length, rule: { ...blankRule(), applies_to: { oe_code: oe } }, isNew: true })
  }
  function deleteRule(index: number) {
    const nextRules = form!.rules.filter((_, i) => i !== index)
    const next = { ...form!, rules: nextRules }
    setForm(next)
    save.mutate(next)
  }
  function commitEdit(rule: Rule) {
    const nextRules = [...form!.rules]
    if (editing!.isNew) nextRules.push(rule)
    else nextRules[editing!.index] = rule
    const next = { ...form!, rules: nextRules }
    setForm(next)
    save.mutate(next)
    setEditing(null)
  }
  function toggleEnabled(index: number) {
    const nextRules = [...form!.rules]
    nextRules[index] = { ...nextRules[index], enabled: nextRules[index].enabled === false }
    const next = { ...form!, rules: nextRules }
    setForm(next)
    save.mutate(next)
  }

  return (
    <div className="space-y-5">
      <Card>
        <CardHeader
          title="Business rules"
          subtitle="The deterministic policy engine — every rule here runs against every submission line."
          action={
            <div className="flex items-center gap-2">
              <Input
                value={form.rule_version}
                onChange={(e) => setForm({ ...form, rule_version: e.target.value })}
                className="w-44"
                placeholder="rule set version"
              />
              <Button variant="primary" size="sm" onClick={openAdd}>
                <Plus className="size-3.5" /> Add rule
              </Button>
            </div>
          }
        />
        <CardBody className="pt-0">
          <div className="mb-3 flex items-center gap-2">
            <Search className="size-4 text-text-muted" />
            <Input
              placeholder="Search by id, description, or type…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-72"
            />
            <span className="text-xs text-text-muted">
              {filtered.length} of {form.rules.length} rules
            </span>
          </div>

          {filtered.length === 0 ? (
            <EmptyState title="No matching rules" />
          ) : (
            <Table>
              <Thead>
                <tr>
                  <Th>ID</Th>
                  <Th>Type</Th>
                  <Th>Description</Th>
                  <Th>Applies to</Th>
                  <Th>Enabled</Th>
                  <Th />
                </tr>
              </Thead>
              <Tbody>
                {filtered.map((r) => {
                  const realIndex = form.rules.indexOf(r)
                  return (
                    <Tr key={r.id || realIndex}>
                      <Td className="font-mono text-xs text-text-primary">{r.id}</Td>
                      <Td>
                        <Badge kind="accent">{RULE_TYPE_INFO[r.type]?.label ?? r.type}</Badge>
                      </Td>
                      <Td className="max-w-[280px] truncate" title={r.description}>
                        {r.description}
                      </Td>
                      <Td className="text-xs text-text-muted">
                        {r.applies_to.category ?? '—'} / {r.applies_to.oe_code ?? 'any OE'}
                      </Td>
                      <Td>
                        <button
                          type="button"
                          onClick={() => toggleEnabled(realIndex)}
                          title={r.enabled === false ? 'Click to enable' : 'Click to disable'}
                        >
                          <Badge kind={r.enabled === false ? 'neutral' : 'success'}>
                            {r.enabled === false ? 'Disabled' : 'Enabled'}
                          </Badge>
                        </button>
                      </Td>
                      <Td>
                        <div className="flex gap-1.5">
                          <Button variant="secondary" size="sm" onClick={() => openEdit(realIndex)}>
                            Edit
                          </Button>
                          <Button variant="danger" size="sm" onClick={() => deleteRule(realIndex)}>
                            <Trash2 className="size-3.5" />
                          </Button>
                        </div>
                      </Td>
                    </Tr>
                  )
                })}
              </Tbody>
            </Table>
          )}
        </CardBody>
      </Card>

      <details className="rounded-lg border border-border">
        <summary className="cursor-pointer px-4 py-3 text-sm font-medium text-text-muted">
          Advanced: raw YAML (JSON)
        </summary>
        <div className="border-t border-border p-4">
          <JsonConfigEditor
            queryKey={queryKey}
            fetcher={() => adminConfigApi.getPolicy(oe)}
            saver={(data) => adminConfigApi.putPolicy(data, oe)}
            title="Policy rules"
          />
        </div>
      </details>

      <Sheet
        open={!!editing}
        onClose={() => setEditing(null)}
        title={editing?.isNew ? 'Add rule' : editing?.rule.id}
        subtitle={editing?.isNew ? 'New business rule' : 'Edit business rule'}
        width="max-w-2xl"
      >
        {editing && (
          <RuleEditor
            key={editing.index}
            rule={editing.rule}
            isNew={editing.isNew}
            existingIds={form.rules.map((r) => r.id)}
            oeScope={oe}
            onSave={commitEdit}
            onCancel={() => setEditing(null)}
            saving={save.isPending}
          />
        )}
      </Sheet>
    </div>
  )
}

function RuleEditor({
  rule: initialRule,
  isNew,
  existingIds,
  oeScope,
  onSave,
  onCancel,
  saving,
}: {
  rule: Rule
  isNew: boolean
  existingIds: string[]
  oeScope?: string
  onSave: (rule: Rule) => void
  onCancel: () => void
  saving: boolean
}) {
  const [rule, setRule] = useState<Rule>(initialRule)
  const idTaken = isNew && existingIds.includes(rule.id.trim())
  const canSave = rule.id.trim().length > 0 && !idTaken

  function setType(type: RuleType) {
    // Reset type-specific fields when switching type, so stale fields from a
    // previous type don't linger unused in the saved rule.
    const base: Rule = {
      id: rule.id, description: rule.description, type, enabled: rule.enabled, applies_to: rule.applies_to,
    }
    if (type === 'amount_cap' || type === 'cumulative_amount_cap') base.cap = {}
    if (type === 'receipt_required_above' || type === 'round_amount_flag') base.threshold = {}
    if (type === 'tax_ratio_check') { base.min_ratio = 0; base.max_ratio = 0.25 }
    if (type === 'late_submission_flag') base.max_days = 90
    if (type === 'cumulative_amount_cap') base.window_days = 365
    setRule(base)
  }

  return (
    <div className="space-y-4">
      <Input
        label="ID"
        value={rule.id}
        onChange={(e) => setRule({ ...rule, id: e.target.value })}
        disabled={!isNew}
        hint={!isNew ? 'The ID is the rule\'s identity and can\'t be changed after creation.' : undefined}
      />
      {idTaken && <p className="-mt-2 text-xs text-error-text">A rule with this ID already exists.</p>}

      <Textarea
        label="Description"
        rows={2}
        value={rule.description}
        onChange={(e) => setRule({ ...rule, description: e.target.value })}
      />

      <label className="flex items-center gap-2 text-sm text-text-secondary">
        <input
          type="checkbox"
          checked={rule.enabled !== false}
          onChange={(e) => setRule({ ...rule, enabled: e.target.checked })}
          className="size-4 rounded border-border accent-accent"
        />
        Enabled — an unchecked rule is skipped entirely (kept, not deleted)
      </label>

      <Select label="Type" value={rule.type} onChange={(e) => setType(e.target.value as RuleType)}>
        {Object.entries(RULE_TYPE_INFO).map(([type, info]) => (
          <option key={type} value={type}>
            {info.label}
          </option>
        ))}
      </Select>
      <p className="-mt-2 text-xs text-text-muted">{RULE_TYPE_INFO[rule.type].hint}</p>

      <div className="grid grid-cols-2 gap-3">
        <Input
          label="Applies to: category"
          placeholder="any category"
          value={rule.applies_to.category ?? ''}
          onChange={(e) =>
            setRule({ ...rule, applies_to: { ...rule.applies_to, category: e.target.value || undefined } })
          }
        />
        {oeScope ? (
          <Select
            label="Applies to: OE code"
            value={rule.applies_to.oe_code ?? ''}
            onChange={(e) =>
              setRule({ ...rule, applies_to: { ...rule.applies_to, oe_code: e.target.value || undefined } })
            }
            hint={`Editing scoped to ${oeScope} — this rule can only be global or ${oeScope}.`}
          >
            <option value="">Global (any OE)</option>
            <option value={oeScope}>{oeScope}</option>
          </Select>
        ) : (
          <Input
            label="Applies to: OE code"
            placeholder="any OE"
            value={rule.applies_to.oe_code ?? ''}
            onChange={(e) =>
              setRule({ ...rule, applies_to: { ...rule.applies_to, oe_code: e.target.value || undefined } })
            }
          />
        )}
      </div>

      <div className="rounded-lg border border-border bg-bg-elevated p-4">
        {(rule.type === 'amount_cap' || rule.type === 'cumulative_amount_cap') && (
          <div className="space-y-3">
            {rule.type === 'cumulative_amount_cap' && (
              <Input
                label="Rolling window (days)"
                type="number" min={1} step={1}
                value={rule.window_days ?? 365}
                onChange={(e) => setRule({ ...rule, window_days: Number(e.target.value) })}
              />
            )}
            <AmountMapEditor
              label="Cap by currency"
              value={rule.cap ?? {}}
              onChange={(next) => setRule({ ...rule, cap: next })}
            />
          </div>
        )}
        {(rule.type === 'receipt_required_above' || rule.type === 'round_amount_flag') && (
          <AmountMapEditor
            label="Threshold by currency"
            value={rule.threshold ?? {}}
            onChange={(next) => setRule({ ...rule, threshold: next })}
          />
        )}
        {rule.type === 'tax_ratio_check' && (
          <div className="grid grid-cols-2 gap-3">
            <Input
              label="Min ratio"
              type="number" step={0.01} min={0}
              value={rule.min_ratio ?? 0}
              onChange={(e) => setRule({ ...rule, min_ratio: Number(e.target.value) })}
            />
            <Input
              label="Max ratio"
              type="number" step={0.01} min={0}
              value={rule.max_ratio ?? 0}
              onChange={(e) => setRule({ ...rule, max_ratio: Number(e.target.value) })}
            />
          </div>
        )}
        {rule.type === 'late_submission_flag' && (
          <Input
            label="Max days after transaction"
            type="number" step={1} min={0}
            value={rule.max_days ?? 90}
            onChange={(e) => setRule({ ...rule, max_days: Number(e.target.value) })}
          />
        )}
        {(rule.type === 'prohibited_category' ||
          rule.type === 'weekend_spend_flag' ||
          rule.type === 'currency_mismatch_flag') && (
          <p className="text-sm text-text-muted">No additional parameters for this rule type.</p>
        )}
      </div>

      <div className="flex gap-2 border-t border-border pt-4">
        <Button variant="primary" onClick={() => onSave(rule)} loading={saving} disabled={!canSave}>
          <Save className="size-4" /> {isNew ? 'Add rule' : 'Save rule'}
        </Button>
        <Button variant="secondary" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </div>
  )
}
