import { forwardRef, type ButtonHTMLAttributes } from 'react'
import { Loader2 } from 'lucide-react'
import { cn } from '../../lib/utils'

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'outline'
type Size = 'sm' | 'md' | 'lg'

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
  size?: Size
  loading?: boolean
}

const variantClasses: Record<Variant, string> = {
  primary:
    'bg-accent text-white border border-accent hover:bg-accent-dim hover:shadow-[0_2px_16px_-2px_var(--color-accent-glow)] active:scale-[0.98]',
  secondary:
    'bg-bg-elevated text-text-secondary border border-border hover:bg-bg-hover hover:text-text-primary hover:border-border-focus',
  outline:
    'bg-transparent text-text-secondary border border-border hover:bg-bg-elevated hover:text-text-primary',
  ghost:
    'bg-transparent text-text-secondary border border-transparent hover:bg-bg-elevated hover:text-text-primary',
  danger:
    'bg-error/10 text-error-text border border-error-border hover:bg-error/20',
}

const sizeClasses: Record<Size, string> = {
  sm: 'h-8 px-3 text-xs gap-1.5',
  md: 'h-9 px-4 text-sm gap-2',
  lg: 'h-11 px-5 text-sm gap-2',
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = 'secondary', size = 'md', loading, disabled, children, ...props }, ref) => {
    return (
      <button
        ref={ref}
        disabled={disabled || loading}
        className={cn(
          'inline-flex items-center justify-center rounded-lg font-medium tracking-tight transition-all duration-150',
          'disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:shadow-none',
          'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/50',
          variantClasses[variant],
          sizeClasses[size],
          className,
        )}
        {...props}
      >
        {loading && <Loader2 className="size-3.5 animate-spin" />}
        {children}
      </button>
    )
  },
)
Button.displayName = 'Button'
