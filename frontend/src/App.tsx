import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import type { KeyboardEvent, ChangeEvent, MouseEvent } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

interface ModelOption {
  id: string
  name: string
  description: string
  color: string
  default_reasoning: string
}

interface ReasoningOption {
  id: string
  name: string
  description: string
}

type ThinkingBlock = { kind: 'thinking'; id: number; content: string; done: boolean }
type ToolCallBlock = { kind: 'tool_call'; id: number; tool_name: string; args: string; done: boolean }
type ToolResponseBlock = { kind: 'tool_response'; tool_name: string; content: string }
type TextBlock = { kind: 'text'; content: string }
type Block = ThinkingBlock | ToolCallBlock | ToolResponseBlock | TextBlock

interface Message {
  role: 'user' | 'assistant'
  content: string        // user messages and error text
  blocks?: Block[]       // assistant messages only
  streaming?: boolean
  error?: boolean
}

const URL_REGEX = /(https?:\/\/[^\s<>"')\]]+)/g

function linkify(text: string): ReactNode[] {
  const parts = text.split(URL_REGEX)
  return parts.map((part, i) =>
    URL_REGEX.test(part)
      ? <a key={i} href={part} target="_blank" rel="noopener noreferrer">{part}</a>
      : part
  )
}

function ThinkingBlock({ block }: { block: ThinkingBlock }) {
  const [expanded, setExpanded] = useState(!block.done)

  useEffect(() => {
    if (block.done) setExpanded(false)
  }, [block.done])

  return (
    <div className="op-block thinking-block">
      <button className="op-block-header" onClick={() => setExpanded(e => !e)}>
        <span className="op-block-icon">💭</span>
        <span className="op-block-title">
          {block.done ? 'Thought for a moment' : 'Thinking...'}
        </span>
        <span className={`op-block-caret${expanded ? ' open' : ''}`}>▸</span>
      </button>
      {expanded && (
        <div className="op-block-body">
          <pre className="op-block-pre">
            {block.content}
            {!block.done && <span className="cursor">▋</span>}
          </pre>
        </div>
      )}
    </div>
  )
}

function ToolCallBlock({ call, response }: { call: ToolCallBlock; response: ToolResponseBlock | undefined }) {
  const [expanded, setExpanded] = useState(true)
  const shouldCollapse = call.done && response !== undefined

  useEffect(() => {
    if (shouldCollapse) setExpanded(false)
  }, [shouldCollapse])

  return (
    <div className="op-block tool-block">
      <button className="op-block-header" onClick={() => setExpanded(e => !e)}>
        <span className="op-block-icon">🔧</span>
        <span className="op-block-title">
          {call.done ? `${call.tool_name} ✓` : `Calling ${call.tool_name}...`}
        </span>
        <span className={`op-block-caret${expanded ? ' open' : ''}`}>▸</span>
      </button>
      {expanded && (
        <div className="op-block-body">
          <div className="op-block-section-label">Args</div>
          <pre className="op-block-pre">
            {call.args}
            {!call.done && <span className="cursor">▋</span>}
          </pre>
          {response !== undefined && (
            <>
              <div className="op-block-section-label">Response</div>
              <pre className="op-block-pre">{response.content}</pre>
            </>
          )}
        </div>
      )}
    </div>
  )
}

function AssistantMessage({ msg }: { msg: Message }) {
  if (msg.error) {
    return <div className="bubble">{msg.content}</div>
  }

  const blocks = msg.blocks ?? []
  const rendered: ReactNode[] = []
  let i = 0
  while (i < blocks.length) {
    const block = blocks[i]
    if (block.kind === 'thinking') {
      rendered.push(<ThinkingBlock key={`t-${block.id}`} block={block} />)
      i++
    } else if (block.kind === 'tool_call') {
      const next = blocks[i + 1]
      const response = next?.kind === 'tool_response' ? next : undefined
      rendered.push(<ToolCallBlock key={`c-${block.id}`} call={block} response={response} />)
      i += response !== undefined ? 2 : 1
    } else if (block.kind === 'tool_response') {
      // Orphaned (shouldn't occur), skip
      i++
    } else {
      // text block
      const isLast = i === blocks.length - 1
      rendered.push(
        <div key={`tx-${i}`} className="bubble">
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={{ a: ({ href, children }) => <a href={href} target="_blank" rel="noopener noreferrer">{children}</a> }}
          >
            {block.content}
          </ReactMarkdown>
          {msg.streaming && isLast && <span className="cursor">▋</span>}
        </div>
      )
      i++
    }
  }

  if (blocks.length === 0 && msg.streaming) {
    rendered.push(<div key="empty" className="bubble"><span className="cursor">▋</span></div>)
  }

  return <>{rendered}</>
}

function getOrCreateSessionId() {
  let id = localStorage.getItem('lorekeeper_session_id')
  if (!id) {
    id = crypto.randomUUID()
    localStorage.setItem('lorekeeper_session_id', id)
  }
  return id
}

function getOrCreateModel() {
  return localStorage.getItem('lorekeeper_model') ?? 'gpt-5-mini-2025-08-07'
}

function getOrCreateReasoningEffort() {
  return localStorage.getItem('lorekeeper_reasoning_effort') ?? 'medium'
}

export default function App() {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [sessionId] = useState(getOrCreateSessionId)
  const [lastFetched, setLastFetched] = useState<string | null>(null)
  const [isFetching, setIsFetching] = useState(false)
  const [nextAllowedAt, setNextAllowedAt] = useState<string | null>(null)
  const [showConfirm, setShowConfirm] = useState(false)
  const [models, setModels] = useState<ModelOption[]>([])
  const [model, setModel] = useState<string>(getOrCreateModel)
  const [modelDropdownOpen, setModelDropdownOpen] = useState(false)
  const modelDropdownRef = useRef<HTMLDivElement>(null)
  const [reasoningLevels, setReasoningLevels] = useState<ReasoningOption[]>([])
  const [reasoningEffort, setReasoningEffort] = useState<string>(getOrCreateReasoningEffort)
  const [reasoningDropdownOpen, setReasoningDropdownOpen] = useState(false)
  const reasoningDropdownRef = useRef<HTMLDivElement>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  async function loadFetchStatus() {
    const d = await fetch('/api/fetch-status').then(r => r.json())
    setIsFetching(d.running)
    setNextAllowedAt(d.next_allowed_at ?? null)
  }

  useEffect(() => {
    fetch('/api/last-fetched')
      .then(r => r.json())
      .then(d => setLastFetched(d.fetched_at))
      .catch(() => {})
    loadFetchStatus().catch(() => {})
    fetch('/api/models')
      .then(r => r.json())
      .then(d => setModels(d))
      .catch(() => {})
    fetch('/api/reasoning-levels')
      .then(r => r.json())
      .then(d => setReasoningLevels(d))
      .catch(() => {})
  }, [])

  useEffect(() => {
    if (!isFetching) return
    const id = setInterval(() => {
      loadFetchStatus().then(() => {
        if (!isFetching) {
          fetch('/api/last-fetched')
            .then(r => r.json())
            .then(d => setLastFetched(d.fetched_at))
            .catch(() => {})
        }
      }).catch(() => {})
    }, 5000)
    return () => clearInterval(id)
  }, [isFetching])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  useEffect(() => {
    if (!modelDropdownOpen) return
    function handleClickOutside(e: globalThis.MouseEvent) {
      if (modelDropdownRef.current && !modelDropdownRef.current.contains(e.target as Node)) {
        setModelDropdownOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [modelDropdownOpen])

  useEffect(() => {
    if (!reasoningDropdownOpen) return
    function handleClickOutside(e: globalThis.MouseEvent) {
      if (reasoningDropdownRef.current && !reasoningDropdownRef.current.contains(e.target as Node)) {
        setReasoningDropdownOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [reasoningDropdownOpen])

  async function sendMessage() {
    const text = input.trim()
    if (!text || isLoading) return

    setInput('')
    setIsLoading(true)

    setMessages(prev => [
      ...prev,
      { role: 'user', content: text },
      { role: 'assistant', content: '', streaming: true },
    ])

    try {
      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, session_id: sessionId, model, reasoning_effort: reasoningEffort }),
      })

      const reader = response.body!.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop()!

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          const payload = JSON.parse(line.slice(6))

          if (payload.delta) {
            setMessages(prev => {
              const updated = [...prev]
              const last = updated[updated.length - 1]
              updated[updated.length - 1] = { ...last, content: last.content + payload.delta }
              return updated
            })
          }

          if (payload.done) {
            setMessages(prev => {
              const updated = [...prev]
              updated[updated.length - 1] = { ...updated[updated.length - 1], streaming: false }
              return updated
            })
          }

          if (payload.error) {
            setMessages(prev => {
              const updated = [...prev]
              updated[updated.length - 1] = {
                ...updated[updated.length - 1],
                content: `Error: ${payload.error}`,
                streaming: false,
                error: true,
              }
              return updated
            })
          }
        }
      }
    } catch (err) {
      setMessages(prev => {
        const updated = [...prev]
        updated[updated.length - 1] = {
          ...updated[updated.length - 1],
          content: `Error: ${(err as Error).message}`,
          streaming: false,
          error: true,
        }
        return updated
      })
    } finally {
      setIsLoading(false)
      setTimeout(() => inputRef.current?.focus(), 0)
    }
  }

  const canRefresh = !isFetching && (!nextAllowedAt || Date.now() >= new Date(nextAllowedAt).getTime())

  async function refreshData() {
    const d = await fetch('/api/fetch', { method: 'POST' }).then(r => r.json())
    if (d.status === 'started' || d.status === 'running') {
      setIsFetching(true)
    }
    if (d.next_allowed_at) setNextAllowedAt(d.next_allowed_at)
  }

  async function clearChat() {
    await fetch(`/api/session/${sessionId}`, { method: 'DELETE' })
    setMessages([])
  }

  function handleModelChange(value: string, e: MouseEvent) {
    e.stopPropagation()
    setModel(value)
    setModelDropdownOpen(false)
    localStorage.setItem('lorekeeper_model', value)
    const defaultReasoning = models.find(m => m.id === value)?.default_reasoning ?? 'medium'
    setReasoningEffort(defaultReasoning)
    localStorage.setItem('lorekeeper_reasoning_effort', defaultReasoning)
  }

  function handleReasoningChange(value: string, e: MouseEvent) {
    e.stopPropagation()
    setReasoningEffort(value)
    setReasoningDropdownOpen(false)
    localStorage.setItem('lorekeeper_reasoning_effort', value)
  }

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendMessage()
    }
  }

  return (
    <div className="app">
      <header className="header">
        <h1>⚔️ LoreKeeper</h1>
        {lastFetched && (
          <span className="last-fetched">
            Last data update: {new Date(lastFetched).toLocaleString('en-GB', { hour12: true })}
          </span>
        )}
        <button className="refresh-btn" onClick={() => setShowConfirm(true)} disabled={!canRefresh}>
          {isFetching ? 'Refreshing...' : 'Refresh Data'}
        </button>
        {showConfirm && (
          <div className="confirm-overlay">
            <div className="confirm-dialog">
              <p>⚠️ This will delete all of LoreKeeper's stored data and recreate it from the sources. This process takes a few minutes. Are you sure you want to proceed?</p>
              <div className="confirm-actions">
                <button className="confirm-yes" onClick={() => { setShowConfirm(false); refreshData() }}>Yes, refresh</button>
                <button className="confirm-cancel" onClick={() => setShowConfirm(false)}>Cancel</button>
              </div>
            </div>
          </div>
        )}
        <button className="clear-btn" onClick={clearChat} disabled={isLoading}>
          Clear Chat
        </button>
      </header>

      <div className="messages">
        {messages.length === 0 && (
          <div className="empty-state">Ask about your campaign lore...</div>
        )}
        {messages.map((msg, i) => (
          <div key={i} className={`message ${msg.role} ${msg.error ? 'error' : ''}`}>
            <div className="bubble">
              {msg.role === 'assistant'
                ? <ReactMarkdown remarkPlugins={[remarkGfm]} components={{ a: ({href, children}) => <a href={href} target="_blank" rel="noopener noreferrer">{children}</a> }}>{msg.content}</ReactMarkdown>
                : linkify(msg.content)
              }
              {msg.streaming && <span className="cursor">▋</span>}
            </div>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      <div className="input-area">
        <div className="selector-stack">
          <div className="model-select" ref={modelDropdownRef}>
            <button
              className={`model-trigger${modelDropdownOpen ? ' open' : ''}`}
              style={{ backgroundColor: models.find(m => m.id === model)?.color }}
              onClick={() => setModelDropdownOpen(o => !o)}
            >
              <span className="model-name-sizer">
                {models.map(m => (
                  <span key={m.id} style={{ visibility: m.id === model ? 'visible' : 'hidden' }}>
                    {m.name}
                  </span>
                ))}
              </span>
              <span className="model-caret">▾</span>
            </button>
            {modelDropdownOpen && (
              <div className="model-options">
                {models.map(m => (
                  <div
                    key={m.id}
                    className={`model-option${m.id === model ? ' selected' : ''}`}
                    onClick={e => handleModelChange(m.id, e)}
                  >
                    <span className="model-option-name">{m.name}</span>
                    <span className="model-option-desc">{m.description}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
          <div className="reasoning-select" ref={reasoningDropdownRef}>
            <button
              className={`reasoning-trigger${reasoningDropdownOpen ? ' open' : ''}`}
              onClick={() => setReasoningDropdownOpen(o => !o)}
            >
              <span className="reasoning-name-sizer">
                {reasoningLevels.map(r => (
                  <span key={r.id} style={{ visibility: r.id === reasoningEffort ? 'visible' : 'hidden' }}>
                    {r.name}
                  </span>
                ))}
              </span>
              <span className="reasoning-caret">▾</span>
            </button>
            {reasoningDropdownOpen && (
              <div className="reasoning-options">
                {reasoningLevels.map(r => (
                  <div
                    key={r.id}
                    className={`reasoning-option${r.id === reasoningEffort ? ' selected' : ''}`}
                    onClick={e => handleReasoningChange(r.id, e)}
                  >
                    <span className="reasoning-option-name">{r.name}</span>
                    <span className="reasoning-option-desc">{r.description}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
        <textarea
          ref={inputRef}
          value={input}
          onChange={(e: ChangeEvent<HTMLTextAreaElement>) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Ask about the campaign lore... (Enter to send)"
          disabled={isLoading}
          rows={2}
        />
        <button onClick={sendMessage} disabled={isLoading || !input.trim()}>
          {isLoading ? '...' : 'Send'}
        </button>
      </div>
    </div>
  )
}
