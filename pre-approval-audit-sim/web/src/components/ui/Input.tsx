import {
  Children,
  forwardRef,
  isValidElement,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type InputHTMLAttributes,
  type OptionHTMLAttributes,
  type ReactElement,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from 'react'
import { ChevronDown } from 'lucide-react'
import { cn } from '../../lib/utils'
import { DropdownPortal, useAnchoredRect } from './Popover'

const fieldBase =
  'w-full rounded-lg border border-border bg-bg-elevated px-3 py-2 text-sm text-text-primary placeholder:text-text-faint ' +
  'transition-all focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/25 disabled:opacity-50'

interface FieldWrapProps {
  label?: string
  hint?: string
  className?: string
}

export const Input = forwardRef<
  HTMLInputElement,
  InputHTMLAttributes<HTMLInputElement> & FieldWrapProps
>(({ label, hint, className, id, ...props }, ref) => (
  <label className={cn('block', className)}>
    {label && (
      <span className="mb-1.5 block text-[11px] font-semibold uppercase tracking-wide text-text-secondary">
        {label}
      </span>
    )}
    <input ref={ref} id={id} className={fieldBase} {...props} />
    {hint && <span className="mt-1 block text-xs text-text-muted">{hint}</span>}
  </label>
))
Input.displayName = 'Input'

export const Textarea = forwardRef<
  HTMLTextAreaElement,
  TextareaHTMLAttributes<HTMLTextAreaElement> & FieldWrapProps
>(({ label, hint, className, ...props }, ref) => (
  <label className={cn('block', className)}>
    {label && (
      <span className="mb-1.5 block text-[11px] font-semibold uppercase tracking-wide text-text-secondary">
        {label}
      </span>
    )}
    <textarea ref={ref} className={cn(fieldBase, 'resize-y')} {...props} />
    {hint && <span className="mt-1 block text-xs text-text-muted">{hint}</span>}
  </label>
))
Textarea.displayName = 'Textarea'

// Custom-rendered dropdown, NOT a native <select> - a native select's open
// POPUP is OS-native chrome that browsers (Chromium on Windows especially)
// frequently render with the OS's default light theme regardless of the
// closed box's own dark styling or `color-scheme`/`option` CSS hints, so no
// amount of CSS can reliably theme it. The popup is portal-rendered into
// document.body (Popover.tsx) rather than absolutely positioned inline -
// this Select is used inside Card, and Card's `backdrop-blur-sm` creates its
// own CSS stacking context, which traps a plain `absolute` + `z-*` popup
// behind later sibling elements no matter how high the z-index is set; only
// a portal genuinely escapes that. Every call site in this app already only
// uses the plain `value`/`onChange`/`<option>` shape (no ref, no `multiple`,
// no native-only features), so this is a drop-in replacement with no other
// files needing to change.
interface SelectOption {
  value: string
  label: ReactNode
  disabled?: boolean
}

function optionsFromChildren(children: ReactNode): SelectOption[] {
  return Children.toArray(children)
    .filter((c): c is ReactElement<OptionHTMLAttributes<HTMLOptionElement>> => isValidElement(c))
    .map((c) => ({
      value: String(c.props.value ?? ''),
      label: c.props.children,
      disabled: c.props.disabled,
    }))
}

export const Select = forwardRef<
  HTMLButtonElement,
  SelectHTMLAttributes<HTMLSelectElement> & FieldWrapProps
>(({ label, hint, className, children, value, onChange, disabled, id, name }, ref) => {
  const options = useMemo(() => optionsFromChildren(children), [children])
  const selected = options.find((o) => o.value === String(value ?? ''))
  const [open, setOpen] = useState(false)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const panelRef = useRef<HTMLDivElement>(null)
  const rect = useAnchoredRect(triggerRef, open)

  useEffect(() => {
    if (!open) return
    function onDocPointerDown(e: MouseEvent) {
      const target = e.target as Node
      if (triggerRef.current?.contains(target) || panelRef.current?.contains(target)) return
      setOpen(false)
    }
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onDocPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('mousedown', onDocPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [open])

  function choose(v: string) {
    setOpen(false)
    onChange?.({ target: { value: v, name } } as unknown as ChangeEvent<HTMLSelectElement>)
  }

  return (
    <label className={cn('block', className)}>
      {label && (
        <span className="mb-1.5 block text-[11px] font-semibold uppercase tracking-wide text-text-secondary">
          {label}
        </span>
      )}
      <button
        ref={(node) => {
          triggerRef.current = node
          if (typeof ref === 'function') ref(node)
          else if (ref) ref.current = node
        }}
        type="button"
        id={id}
        disabled={disabled}
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className={cn(fieldBase, 'flex w-full cursor-pointer items-center justify-between gap-2 text-left')}
      >
        <span className="truncate">{selected?.label ?? ''}</span>
        <ChevronDown
          className={cn('size-3.5 shrink-0 text-text-muted transition-transform', open && 'rotate-180')}
        />
      </button>
      <DropdownPortal rect={rect}>
        <div
          ref={panelRef}
          role="listbox"
          className="max-h-60 overflow-auto rounded-lg border border-border bg-bg-elevated py-1 shadow-popover"
        >
          {options.map((o) => (
            <button
              key={o.value}
              type="button"
              role="option"
              aria-selected={o.value === selected?.value}
              disabled={o.disabled}
              onClick={() => choose(o.value)}
              className={cn(
                'flex w-full items-center px-3 py-1.5 text-left text-sm transition-colors disabled:cursor-not-allowed disabled:opacity-50',
                o.value === selected?.value
                  ? 'bg-bg-hover text-accent-bright'
                  : 'text-text-primary hover:bg-bg-hover',
              )}
            >
              {o.label}
            </button>
          ))}
        </div>
      </DropdownPortal>
      {hint && <span className="mt-1 block text-xs text-text-muted">{hint}</span>}
    </label>
  )
})
Select.displayName = 'Select'
