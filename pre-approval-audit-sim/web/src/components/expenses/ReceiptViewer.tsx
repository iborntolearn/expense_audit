import { Download, AlertTriangle } from 'lucide-react'
import { reportsApi } from '../../lib/api'
import { useAuthedBlobUrl } from '../../lib/useAuthedBlobUrl'

export function ReceiptViewer({ sid, receipts }: { sid: string; receipts: Array<{ line_id: string; receipt_url: string }> }) {
  if (!receipts.length) return <p className="text-sm text-text-muted">No receipts on file for this submission.</p>
  return (
    <div className="space-y-4">
      {receipts.map((ref) => (
        <ReceiptItem key={ref.line_id} sid={sid} lineId={ref.line_id} url={ref.receipt_url} />
      ))}
    </div>
  )
}

function ReceiptItem({ sid, lineId, url }: { sid: string; lineId: string; url: string }) {
  const isPdf = url.endsWith('.pdf')
  const fetchUrl = reportsApi.receiptUrl(sid, lineId)
  const { objectUrl, error } = useAuthedBlobUrl(fetchUrl)

  return (
    <div className="rounded-lg border border-border bg-bg-elevated p-3">
      <div className="mb-2 flex items-center justify-between">
        <span className="text-xs font-medium text-text-secondary">{lineId}</span>
        {objectUrl && (
          <a
            href={objectUrl}
            download={`${sid}_${lineId}${isPdf ? '.pdf' : '.png'}`}
            className="flex items-center gap-1 text-xs text-accent-bright hover:underline"
          >
            <Download className="size-3.5" /> Download
          </a>
        )}
      </div>
      {error ? (
        <div className="flex items-center gap-2 rounded-lg bg-error-bg px-3 py-2 text-xs text-error-text">
          <AlertTriangle className="size-3.5" /> {error}
        </div>
      ) : !objectUrl ? (
        <div className="skeleton h-48 rounded-lg" />
      ) : isPdf ? (
        <iframe src={objectUrl} className="h-[500px] w-full rounded-lg border border-border" title={lineId} />
      ) : (
        <img src={objectUrl} alt={lineId} className="max-h-[500px] w-full rounded-lg object-contain" />
      )}
    </div>
  )
}
