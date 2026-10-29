import { useState } from 'react'
import { Plus, Trash2 } from 'lucide-react'
import { Button } from '../ui/Button'
import { Input } from '../ui/Input'

/** Editor for a {currency: amount} map (used by amount_cap / receipt_required_above /
 * round_amount_flag / cumulative_amount_cap rules) - currencies aren't a fixed enum
 * in this data (EUR/USD/GBP plus country-specific CNY/INR etc.), so this lets an
 * admin add any 3-letter code rather than hardcoding a currency list. */
export function AmountMapEditor({
  label,
  value,
  onChange,
}: {
  label: string
  value: Record<string, number>
  onChange: (next: Record<string, number>) => void
}) {
  const [newCurrency, setNewCurrency] = useState('')
  const entries = Object.entries(value)

  function updateAmount(currency: string, amount: number) {
    onChange({ ...value, [currency]: amount })
  }
  function removeCurrency(currency: string) {
    const next = { ...value }
    delete next[currency]
    onChange(next)
  }
  function addCurrency() {
    const code = newCurrency.trim().toUpperCase()
    if (!code || code in value) return
    onChange({ ...value, [code]: 0 })
    setNewCurrency('')
  }

  return (
    <div>
      <span className="mb-1.5 block text-[11px] font-semibold uppercase tracking-wide text-text-secondary">
        {label}
      </span>
      <div className="space-y-2">
        {entries.length === 0 && <p className="text-xs text-text-muted">No currencies set.</p>}
        {entries.map(([currency, amount]) => (
          <div key={currency} className="flex items-center gap-2">
            <span className="w-14 shrink-0 rounded-lg bg-bg-elevated px-2.5 py-2 text-center text-xs font-semibold text-text-secondary">
              {currency}
            </span>
            <Input
              type="number"
              step={0.01}
              min={0}
              value={amount}
              onChange={(e) => updateAmount(currency, Number(e.target.value))}
              className="flex-1"
            />
            <button
              onClick={() => removeCurrency(currency)}
              className="rounded-lg p-2 text-text-muted transition-colors hover:bg-error-bg hover:text-error-text"
            >
              <Trash2 className="size-3.5" />
            </button>
          </div>
        ))}
        <div className="flex items-center gap-2">
          <Input
            placeholder="e.g. USD"
            value={newCurrency}
            onChange={(e) => setNewCurrency(e.target.value)}
            maxLength={3}
            className="w-24"
          />
          <Button variant="secondary" size="sm" onClick={addCurrency} disabled={!newCurrency.trim()}>
            <Plus className="size-3.5" /> Add currency
          </Button>
        </div>
      </div>
    </div>
  )
}
