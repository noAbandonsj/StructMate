/** Preserve HTTP(S) source links; disable unsupported protocols and relative URLs. */
export function safeSourceLink(value: string): string {
  try {
    return ['https:', 'http:'].includes(new URL(value).protocol) ? value : '#'
  } catch {
    return '#'
  }
}
