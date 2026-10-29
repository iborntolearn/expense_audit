// Abstract illustration for the login page's AI-showcase panel: a receipt
// being read by a scanning beam, with the agent pipeline (extract → verify →
// score → decide) rendered as a small connected-node graph beside it, and a
// risk-score dial reporting the outcome. Pure inline SVG (no external image
// asset) so it stays self-contained and themeable via the existing CSS
// custom properties (web/src/index.css's @theme block).
export function AiAuditIllustration() {
  return (
    <svg viewBox="0 0 480 420" fill="none" xmlns="http://www.w3.org/2000/svg" className="h-auto w-full max-w-[260px]">
      <defs>
        <linearGradient id="ai-illo-scan" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="var(--color-accent-bright)" stopOpacity="0" />
          <stop offset="50%" stopColor="var(--color-accent-bright)" stopOpacity="0.55" />
          <stop offset="100%" stopColor="var(--color-accent-bright)" stopOpacity="0" />
        </linearGradient>
        <linearGradient id="ai-illo-card" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="var(--color-bg-elevated)" />
          <stop offset="100%" stopColor="var(--color-bg-overlay)" />
        </linearGradient>
        <radialGradient id="ai-illo-glow" cx="50%" cy="35%" r="65%">
          <stop offset="0%" stopColor="var(--color-purple)" stopOpacity="0.28" />
          <stop offset="100%" stopColor="var(--color-purple)" stopOpacity="0" />
        </radialGradient>
      </defs>

      <rect x="0" y="0" width="480" height="420" fill="url(#ai-illo-glow)" />

      {/* Receipt card */}
      <g transform="translate(60,50)">
        <rect x="0" y="0" width="190" height="270" rx="14" fill="url(#ai-illo-card)"
              stroke="var(--color-border)" strokeWidth="1.5" />
        {/* Zigzag torn edge at the bottom, like a real receipt */}
        <path d="M0 258 L11 270 L23 258 L35 270 L47 258 L59 270 L71 258 L83 270 L95 258 L107 270 L119 258 L131 270 L143 258 L155 270 L167 258 L179 270 L190 260 V300 H0 Z"
              fill="var(--color-bg-base)" />
        {/* Header block */}
        <rect x="24" y="26" width="80" height="10" rx="3" fill="var(--color-text-secondary)" opacity="0.55" />
        <rect x="24" y="44" width="52" height="7" rx="3" fill="var(--color-text-muted)" opacity="0.5" />
        {/* Line items */}
        {[76, 96, 116, 136, 156].map((y, i) => (
          <g key={y}>
            <rect x="24" y={y} width={i === 2 ? 96 : 70} height="7" rx="3" fill="var(--color-text-muted)" opacity="0.4" />
            <rect x="150" y={y} width="26" height="7" rx="3" fill="var(--color-text-secondary)" opacity="0.45" />
          </g>
        ))}
        <line x1="24" y1="182" x2="176" y2="182" stroke="var(--color-border)" strokeWidth="1" />
        {/* Total, emphasised */}
        <rect x="24" y="196" width="46" height="9" rx="3" fill="var(--color-text-primary)" opacity="0.7" />
        <rect x="140" y="196" width="36" height="9" rx="3" fill="var(--color-accent-bright)" opacity="0.9" />

        {/* Scanning beam sweeping the receipt */}
        <rect x="-6" y="70" width="202" height="46" fill="url(#ai-illo-scan)">
          <animate attributeName="y" values="10;250;10" dur="4.5s" repeatCount="indefinite" />
        </rect>
      </g>

      {/* Agent pipeline node graph */}
      <g transform="translate(290,90)" stroke="var(--color-border-focus)" strokeWidth="1.5" opacity="0.8">
        <line x1="8" y1="20" x2="8" y2="80" />
        <line x1="8" y1="80" x2="8" y2="150" />
        <line x1="8" y1="150" x2="8" y2="210" />
      </g>
      <g transform="translate(290,90)">
        {[
          { y: 20, label: 'Extract', color: 'var(--color-accent-bright)' },
          { y: 80, label: 'Verify', color: 'var(--color-purple-bright)' },
          { y: 150, label: 'Score', color: 'var(--color-warning)' },
          { y: 210, label: 'Decide', color: 'var(--color-success)' },
        ].map((node) => (
          <g key={node.label}>
            <circle cx="8" cy={node.y} r="8" fill="var(--color-bg-base)" stroke={node.color} strokeWidth="2" />
            <circle cx="8" cy={node.y} r="3" fill={node.color} />
            <text x="26" y={node.y + 4} fontSize="13" fontWeight="600" fill="var(--color-text-secondary)"
                  fontFamily="Inter, sans-serif">
              {node.label}
            </text>
          </g>
        ))}
      </g>

      {/* Risk-score outcome dial */}
      <g transform="translate(120,340)">
        <circle cx="0" cy="0" r="26" fill="var(--color-bg-elevated)" stroke="var(--color-success-border)" strokeWidth="2" />
        <path d="M-10 1 L-3 8 L11 -8" stroke="var(--color-success)" strokeWidth="3" fill="none"
              strokeLinecap="round" strokeLinejoin="round" />
        <text x="40" y="-4" fontSize="13" fontWeight="700" fill="var(--color-text-primary)" fontFamily="Inter, sans-serif">
          Auto-approved
        </text>
        <text x="40" y="14" fontSize="11" fill="var(--color-text-muted)" fontFamily="Inter, sans-serif">
          risk score 0.12 · under 2s
        </text>
      </g>
    </svg>
  )
}
