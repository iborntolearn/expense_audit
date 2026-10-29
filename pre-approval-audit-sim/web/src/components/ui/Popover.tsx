import { useLayoutEffect, useState, type ReactNode, type RefObject } from 'react'
import { createPortal } from 'react-dom'

export interface AnchoredRect {
  top: number
  left: number
  width: number
}

/** Tracks `anchorRef`'s viewport position while `open`, re-measuring on
 * scroll/resize so a portal-rendered popup stays attached to its trigger. */
export function useAnchoredRect(anchorRef: RefObject<HTMLElement | null>, open: boolean): AnchoredRect | null {
  const [rect, setRect] = useState<AnchoredRect | null>(null)

  useLayoutEffect(() => {
    if (!open || !anchorRef.current) {
      setRect(null)
      return
    }
    function update() {
      const r = anchorRef.current!.getBoundingClientRect()
      setRect({ top: r.bottom + 6, left: r.left, width: r.width })
    }
    update()
    window.addEventListener('scroll', update, true)
    window.addEventListener('resize', update)
    return () => {
      window.removeEventListener('scroll', update, true)
      window.removeEventListener('resize', update)
    }
  }, [open, anchorRef])

  return rect
}

/** Renders `children` into `document.body` as a `position: fixed` panel
 * anchored to `rect`, escaping any ancestor's CSS stacking context - e.g.
 * Card/Topbar's `backdrop-blur` each create a new one, which traps a plain
 * `absolute` + `z-*` child behind later sibling elements no matter how high
 * the z-index is set. Only a portal genuinely escapes that. */
export function DropdownPortal({ rect, children }: { rect: AnchoredRect | null; children: ReactNode }) {
  if (!rect) return null
  return createPortal(
    <div style={{ position: 'fixed', top: rect.top, left: rect.left, width: rect.width, zIndex: 9999 }}>
      {children}
    </div>,
    document.body,
  )
}
