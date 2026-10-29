import { useRef, useState, type FormEvent } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Sparkles, Send, Bot } from 'lucide-react'
import { ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip, CartesianGrid } from 'recharts'
import { assistantApi, type AssistantAnswer, type AssistantHistoryTurn } from '../lib/api'
import { useAuth } from '../lib/auth'
import { Card } from '../components/ui/Card'
import { Input } from '../components/ui/Input'
import { Button } from '../components/ui/Button'
import { Table, Thead, Tbody, Tr, Th, Td } from '../components/ui/Table'
import { CHART_COLORS, tooltipStyle, axisStyle } from '../components/charts/theme'
import { initials } from '../lib/utils'

interface ChatEntry {
  question: string
  answer: AssistantAnswer
}

// Last few turns only - enough for the assistant to resolve a follow-up
// ("what about just DE?") without growing the request unbounded.
const HISTORY_TURNS = 6

function toHistory(chat: ChatEntry[]): AssistantHistoryTurn[] {
  return chat.slice(-HISTORY_TURNS).flatMap((e) => [
    { role: 'user' as const, content: e.question },
    { role: 'assistant' as const, content: e.answer.text },
  ])
}

export function AssistantPage() {
  const { user, oeScope } = useAuth()
  const [chat, setChat] = useState<ChatEntry[]>([])
  const [input, setInput] = useState('')
  const scrollRef = useRef<HTMLDivElement>(null)

  const { data: examples } = useQuery({ queryKey: ['assistant-examples'], queryFn: assistantApi.examples })

  const ask = useMutation({
    mutationFn: (question: string) => assistantApi.ask(question, oeScope || undefined, toHistory(chat)),
    onSuccess: (answer, question) => {
      setChat((prev) => [...prev, { question, answer }])
      setInput('')
      requestAnimationFrame(() => scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' }))
    },
  })

  function submit(e?: FormEvent) {
    e?.preventDefault()
    if (!input.trim() || ask.isPending) return
    ask.mutate(input.trim())
  }

  return (
    <div className="flex h-[calc(100vh-8.5rem)] flex-col animate-in">
      <p className="mb-4 text-sm text-text-muted">
        Ask about unauthorized spend, duplicates, high-risk reports, automation, and more.
      </p>

      {examples && examples.length > 0 && (
        <div className="mb-4 flex flex-wrap gap-2">
          {examples.map((ex) => (
            <button
              key={ex}
              onClick={() => ask.mutate(ex)}
              disabled={ask.isPending}
              className="rounded-full border border-border bg-bg-elevated px-3 py-1.5 text-xs text-text-secondary transition-colors hover:border-accent hover:text-accent-bright disabled:opacity-50"
            >
              {ex}
            </button>
          ))}
        </div>
      )}

      <div ref={scrollRef} className="flex-1 space-y-4 overflow-y-auto pr-1">
        {chat.length === 0 && (
          <div className="flex h-full flex-col items-center justify-center gap-2 text-text-faint">
            <Sparkles className="size-8" />
            <p className="text-sm">Ask a question to get started.</p>
          </div>
        )}
        {chat.map((entry, i) => (
          <div key={i} className="space-y-3">
            <div className="flex items-start justify-end gap-2.5">
              <div className="max-w-[75%] rounded-2xl rounded-tr-sm bg-accent px-4 py-2.5 text-sm text-white">
                {entry.question}
              </div>
              <div className="flex size-7 shrink-0 items-center justify-center rounded-full bg-bg-elevated text-[10px] font-bold text-text-secondary">
                {initials(user?.display_name ?? 'U')}
              </div>
            </div>
            <div className="flex items-start gap-2.5">
              <div className="flex size-7 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-accent to-purple text-white">
                <Bot className="size-3.5" />
              </div>
              <div className="max-w-[85%] flex-1">
                <AnswerCard answer={entry.answer} onFollowUp={(q) => ask.mutate(q)} />
              </div>
            </div>
          </div>
        ))}
        {ask.isPending && (
          <div className="flex items-center gap-2.5">
            <div className="flex size-7 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-accent to-purple text-white">
              <Bot className="size-3.5" />
            </div>
            <div className="flex gap-1 rounded-2xl rounded-tl-sm bg-bg-elevated px-4 py-3">
              {[0, 1, 2].map((i) => (
                <span
                  key={i}
                  className="size-1.5 animate-bounce rounded-full bg-text-muted"
                  style={{ animationDelay: `${i * 0.15}s` }}
                />
              ))}
            </div>
          </div>
        )}
      </div>

      <form onSubmit={submit} className="mt-4 flex items-center gap-2 border-t border-border pt-4">
        <Input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask a question about expense audit data"
          className="flex-1"
        />
        <Button type="submit" variant="primary" loading={ask.isPending} disabled={!input.trim()}>
          <Send className="size-4" />
        </Button>
      </form>
    </div>
  )
}

function AnswerCard({ answer, onFollowUp }: { answer: AssistantAnswer; onFollowUp: (q: string) => void }) {
  const chartData = answer.chart?.data ?? []
  const tableRows = answer.table ?? []
  const tableCols = tableRows.length > 0 ? Object.keys(tableRows[0]) : []

  return (
    <Card className="rounded-tl-sm">
      <div className="space-y-3 p-4">
        <p className="whitespace-pre-wrap text-sm text-text-primary">{answer.text}</p>

        {answer.metric && (
          <div className="inline-flex flex-col rounded-lg border border-border bg-bg-elevated px-4 py-2">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-text-muted">
              {answer.metric[0]}
            </span>
            <span className="text-lg font-bold text-text-primary">{answer.metric[1]}</span>
          </div>
        )}

        {answer.chart && chartData.length > 0 && (
          <ResponsiveContainer width="100%" height={Math.max(160, chartData.length * 32)}>
            <BarChart data={chartData} layout="vertical" margin={{ left: 8 }}>
              <CartesianGrid stroke={CHART_COLORS.grid} horizontal={false} />
              <XAxis type="number" {...axisStyle} />
              <YAxis type="category" dataKey={answer.chart.label} {...axisStyle} width={100} />
              <Tooltip {...tooltipStyle} cursor={{ fill: 'rgba(255,255,255,0.03)' }} />
              <Bar dataKey={answer.chart.value} fill={CHART_COLORS.accent} radius={[0, 4, 4, 0]} />
            </BarChart>
          </ResponsiveContainer>
        )}

        {tableRows.length > 0 && (
          <Table>
            <Thead>
              <tr>
                {tableCols.map((c) => (
                  <Th key={c}>{c}</Th>
                ))}
              </tr>
            </Thead>
            <Tbody>
              {tableRows.map((row, i) => (
                <Tr key={i}>
                  {tableCols.map((c) => (
                    <Td key={c}>{String(row[c])}</Td>
                  ))}
                </Tr>
              ))}
            </Tbody>
          </Table>
        )}

        {answer.suggestions.length > 0 && (
          <div className="flex flex-wrap gap-2 pt-1">
            {answer.suggestions.map((s) => (
              <button
                key={s}
                onClick={() => onFollowUp(s)}
                className="rounded-full border border-border px-3 py-1 text-xs text-text-muted transition-colors hover:border-accent hover:text-accent-bright"
              >
                {s}
              </button>
            ))}
          </div>
        )}
      </div>
    </Card>
  )
}
