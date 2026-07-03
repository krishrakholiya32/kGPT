import { useState, type ReactNode } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import rehypeHighlight from 'rehype-highlight'
import { copyToClipboard } from '../lib/clipboard'
import { looksLikeHtml } from '../lib/preview'
import { useArtifact } from './Artifact'

// NOTE: react-markdown does NOT render raw HTML from the source by default, and
// we deliberately do NOT add rehype-raw here — this preserves the same
// sanitization guarantee the original app got from DOMPurify (no XSS via the
// model's output).

// Convert LaTeX \[..\] / \(..\) delimiters to the $$..$$ / $..$ forms that
// remark-math understands, but only outside code spans/fences so code content
// is never mangled (mirrors the original math-protection behaviour).
function normalizeMath(src: string): string {
  const parts = src.split(/(```[\s\S]*?```|`[^`]*`)/g)
  return parts
    .map((seg, i) => {
      if (i % 2 === 1) return seg // code span/fence — leave untouched
      let out = seg.replace(/\\\[([\s\S]+?)\\\]/g, (_m, inner) => `$$${inner}$$`)
      out = out.replace(/\\\(([\s\S]+?)\\\)/g, (_m, inner) => `$${inner}$`)
      return out
    })
    .join('')
}

interface HastNode {
  type?: string
  tagName?: string
  value?: string
  properties?: { className?: string[] }
  children?: HastNode[]
}

function hastText(n: HastNode | undefined): string {
  if (!n) return ''
  if (n.type === 'text') return n.value || ''
  if (n.children) return n.children.map(hastText).join('')
  return ''
}

function CodePre(props: { children?: ReactNode; node?: HastNode }) {
  const { children, node } = props
  const { openArtifact } = useArtifact()
  const [label, setLabel] = useState('Copy')

  const codeEl = node?.children?.find((c) => c.tagName === 'code') ?? node?.children?.[0]
  const codeText = hastText(codeEl)
  const className = (codeEl?.properties?.className || []).join(' ')
  const isHtml = looksLikeHtml(codeText, className)

  return (
    <pre>
      {children}
      {isHtml && (
        <button type="button" className="code-preview-btn" onClick={() => openArtifact(codeText)}>
          Preview
        </button>
      )}
      <button
        type="button"
        className="code-copy-btn"
        onClick={() => {
          copyToClipboard(codeText)
          setLabel('Copied!')
          setTimeout(() => setLabel('Copy'), 1500)
        }}
      >
        {label}
      </button>
    </pre>
  )
}

export default function Markdown({ text }: { text: string }) {
  return (
    <div className="md">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[rehypeKatex, rehypeHighlight]}
        components={{ pre: CodePre as never }}
      >
        {normalizeMath(text)}
      </ReactMarkdown>
    </div>
  )
}
