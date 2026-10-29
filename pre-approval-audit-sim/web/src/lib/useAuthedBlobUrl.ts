import { useEffect, useState } from 'react'
import { getToken } from './api'

// <img>/<iframe> tags can't send an Authorization header, but our receipt
// endpoint requires one (it's JWT-protected media) - fetch it as a blob and
// hand back an object URL instead.
export function useAuthedBlobUrl(url: string | null): { objectUrl: string | null; error: string | null } {
  const [objectUrl, setObjectUrl] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!url) {
      setObjectUrl(null)
      return
    }
    let cancelled = false
    let created: string | null = null
    setError(null)
    fetch(url, { headers: { Authorization: `Bearer ${getToken() ?? ''}` } })
      .then(async (res) => {
        if (!res.ok) throw new Error(`could not load receipt (${res.status})`)
        const blob = await res.blob()
        if (cancelled) return
        created = URL.createObjectURL(blob)
        setObjectUrl(created)
      })
      .catch((e) => !cancelled && setError(e.message))
    return () => {
      cancelled = true
      if (created) URL.revokeObjectURL(created)
    }
  }, [url])

  return { objectUrl, error }
}

// One-shot authenticated download (for endpoints behind JWT auth that a
// plain <a href> can't reach, e.g. reports-export downloads).
export async function downloadAuthed(url: string, filename: string) {
  const res = await fetch(url, { headers: { Authorization: `Bearer ${getToken() ?? ''}` } })
  if (!res.ok) throw new Error(`download failed (${res.status})`)
  const blob = await res.blob()
  const objectUrl = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = objectUrl
  a.download = filename
  a.click()
  URL.revokeObjectURL(objectUrl)
}
