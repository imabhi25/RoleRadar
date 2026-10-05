/** Keep link icons crisp even on systems whose text fonts do not include the diagonal arrow glyph. */
export function ExternalArrow({ className, size = 14 }: { className?: string; size?: number }) {
  return (
    <svg className={className} width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
      <path d="M7 17 17 7M7 7h10v10" />
    </svg>
  );
}
