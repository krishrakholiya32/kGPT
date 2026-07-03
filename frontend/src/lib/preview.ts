// Detect whether a code block looks like renderable HTML/SVG markup, so the
// message renderer can offer a live "Preview" button (mirrors the original).

export function looksLikeHtml(codeText: string, className: string): boolean {
  if (/language-(html|xml|xhtml|svg|markup)/i.test(className)) return true
  const t = (codeText || '').trim().toLowerCase()
  if (t.includes('<!doctype html') || t.includes('<html') || t.includes('<svg')) return true
  return /^<(div|section|main|body|head|style|h[1-6]|p|ul|ol|table|canvas|form|button|span|a|img)\b/.test(t)
}
