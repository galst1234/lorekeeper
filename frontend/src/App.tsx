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
type ToolResponseBlock = { kind: 'tool_response'; tool_name: string; call_index: number; content: string }
type TextBlock = { kind: 'text'; content: string }
type Block = ThinkingBlock | ToolCallBlock | ToolResponseBlock | TextBlock

interface Message {
  role: 'user' | 'assistant'
  content: string        // user messages and error text
  blocks?: Block[]       // assistant messages only
  streaming?: boolean
  error?: boolean
}

interface SkillOption {
  id: string
  description: string
}

const SHOW_SKILL_HINT = true

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

function OrphanedToolResponse({ block }: { block: ToolResponseBlock }) {
  const [expanded, setExpanded] = useState(false)
  return (
    <div className="op-block tool-block">
      <button className="op-block-header" onClick={() => setExpanded(e => !e)}>
        <span className="op-block-icon">🔧</span>
        <span className="op-block-title">{block.tool_name} (response)</span>
        <span className={`op-block-caret${expanded ? ' open' : ''}`}>▸</span>
      </button>
      {expanded && (
        <div className="op-block-body">
          <pre className="op-block-pre">{block.content}</pre>
        </div>
      )}
    </div>
  )
}

function isActionBlockDone(block: Block, allBlocks: Block[]): boolean {
  if (block.kind === 'tool_response') return true
  if (block.kind === 'thinking') return block.done
  if (block.kind === 'tool_call') {
    if (!block.done) return false
    return allBlocks.some(b => b.kind === 'tool_response' && b.call_index === block.id)
  }
  return true
}

function ActionsWrapper({ blocks, streaming }: { blocks: Block[]; streaming: boolean }) {
  const [expanded, setExpanded] = useState(false)

  const responseByCallIndex = new Map<number, ToolResponseBlock>()
  for (const b of blocks) {
    if (b.kind === 'tool_response') responseByCallIndex.set(b.call_index, b)
  }

  const actionCount = blocks.filter(
    b => (b.kind === 'thinking' && !(b.done && !b.content)) || b.kind === 'tool_call'
  ).length
  if (actionCount === 0) return null

  return (
    <div className="op-block actions-summary">
      <button className="op-block-header" onClick={() => setExpanded(e => !e)}>
        <span className="op-block-icon">⚙️</span>
        <span className="op-block-title">
          {`Performed ${actionCount} action${actionCount !== 1 ? 's' : ''}${streaming ? '…' : ''}`}
        </span>
        <span className={`op-block-caret${expanded ? ' open' : ''}`}>▸</span>
      </button>
      {expanded && (
        <div className="op-block-body actions-body">
          {blocks.map(block => {
            if (block.kind === 'thinking') {
              if (block.done && !block.content) return null
              return <ThinkingBlock key={`t-${block.id}`} block={block} />
            }
            if (block.kind === 'tool_call') {
              return <ToolCallBlock key={`c-${block.id}`} call={block} response={responseByCallIndex.get(block.id)} />
            }
            if (block.kind === 'tool_response') {
              const isPaired = block.call_index !== -1 && blocks.some(b => b.kind === 'tool_call' && b.id === block.call_index)
              if (!isPaired) return <OrphanedToolResponse key={`tr-${block.call_index}-${block.tool_name}`} block={block} />
            }
            return null
          })}
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
  const actionBlocks = blocks.filter(b => b.kind !== 'text')
  const doneBlocks = actionBlocks.filter(b => isActionBlockDone(b, blocks))
  const activeBlock = actionBlocks.find(b => !isActionBlockDone(b, blocks)) ?? null
  const textBlocks = blocks.filter((b): b is TextBlock => b.kind === 'text')
  const hasText = textBlocks.length > 0

  // Response map needed for the edge case: tool_call is done but response not yet arrived
  const responseByCallIndex = new Map<number, ToolResponseBlock>()
  for (const b of blocks) {
    if (b.kind === 'tool_response') responseByCallIndex.set(b.call_index, b)
  }

  return (
    <>
      {doneBlocks.length > 0 && (
        <ActionsWrapper blocks={doneBlocks} streaming={msg.streaming ?? false} />
      )}
      {activeBlock && (
        activeBlock.kind === 'thinking'
          ? <ThinkingBlock key={`t-${activeBlock.id}`} block={activeBlock} />
          : activeBlock.kind === 'tool_call'
            ? <ToolCallBlock key={`c-${activeBlock.id}`} call={activeBlock} response={responseByCallIndex.get(activeBlock.id)} />
            : null
      )}
      {textBlocks.map((block, i) => (
        <div key={`tx-${i}`} className="bubble">
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={{ a: ({ href, children }) => <a href={href} target="_blank" rel="noopener noreferrer">{children}</a> }}
          >
            {block.content}
          </ReactMarkdown>
          {msg.streaming && i === textBlocks.length - 1 && <span className="cursor">▋</span>}
        </div>
      ))}
      {msg.streaming && !hasText && (
        <div className="bubble"><span className="cursor">▋</span></div>
      )}
    </>
  )
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
  const [skills, setSkills] = useState<SkillOption[]>([])
  const [slashMenuOpen, setSlashMenuOpen] = useState(false)
  const [slashFilter, setSlashFilter] = useState('')
  const [slashIndex, setSlashIndex] = useState(0)
  const slashMenuRef = useRef<HTMLDivElement>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  const filteredSkills = skills.filter(s => s.id.startsWith(slashFilter))

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
    fetch('/api/skills')
      .then(r => r.json())
      .then(d => setSkills(d))
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

  useEffect(() => {
    if (!slashMenuOpen) return
    function handleClickOutside(e: globalThis.MouseEvent) {
      if (slashMenuRef.current && !slashMenuRef.current.contains(e.target as Node)) {
        setSlashMenuOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [slashMenuOpen])

  async function sendMessage() {
    const text = input.trim()
    if (!text || isLoading) return

    setInput('')
    setIsLoading(true)

    setMessages(prev => [
      ...prev,
      { role: 'user', content: text },
      { role: 'assistant', content: '', blocks: [], streaming: true },
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

          const { type } = payload

          if (type === 'thinking_start') {
            setMessages(prev => {
              const msgs = [...prev]
              const last = { ...msgs[msgs.length - 1] }
              last.blocks = [...(last.blocks ?? []), { kind: 'thinking' as const, id: payload.index, content: '', done: false }]
              msgs[msgs.length - 1] = last
              return msgs
            })
          }

          if (type === 'thinking_delta') {
            setMessages(prev => {
              const msgs = [...prev]
              const last = { ...msgs[msgs.length - 1] }
              last.blocks = (last.blocks ?? []).map(b =>
                b.kind === 'thinking' && b.id === payload.index ? { ...b, content: b.content + payload.delta } : b
              )
              msgs[msgs.length - 1] = last
              return msgs
            })
          }

          if (type === 'thinking_end') {
            setMessages(prev => {
              const msgs = [...prev]
              const last = { ...msgs[msgs.length - 1] }
              last.blocks = (last.blocks ?? []).map(b =>
                b.kind === 'thinking' && b.id === payload.index ? { ...b, done: true } : b
              )
              msgs[msgs.length - 1] = last
              return msgs
            })
          }

          if (type === 'tool_call_start') {
            setMessages(prev => {
              const msgs = [...prev]
              const last = { ...msgs[msgs.length - 1] }
              last.blocks = [
                ...(last.blocks ?? []),
                { kind: 'tool_call' as const, id: payload.index, tool_name: payload.tool_name, args: '', done: false },
              ]
              msgs[msgs.length - 1] = last
              return msgs
            })
          }

          if (type === 'tool_call_args_delta') {
            setMessages(prev => {
              const msgs = [...prev]
              const last = { ...msgs[msgs.length - 1] }
              last.blocks = (last.blocks ?? []).map(b =>
                b.kind === 'tool_call' && b.id === payload.index ? { ...b, args: b.args + (payload.delta ?? '') } : b
              )
              msgs[msgs.length - 1] = last
              return msgs
            })
          }

          if (type === 'tool_call_end') {
            setMessages(prev => {
              const msgs = [...prev]
              const last = { ...msgs[msgs.length - 1] }
              last.blocks = (last.blocks ?? []).map(b =>
                b.kind === 'tool_call' && b.id === payload.index
                  ? { ...b, done: true, args: payload.complete_args || b.args || '' }
                  : b
              )
              msgs[msgs.length - 1] = last
              return msgs
            })
          }

          if (type === 'tool_response') {
            setMessages(prev => {
              const msgs = [...prev]
              const last = { ...msgs[msgs.length - 1] }
              last.blocks = [
                ...(last.blocks ?? []),
                { kind: 'tool_response' as const, tool_name: payload.tool_name, call_index: payload.call_index, content: payload.content },
              ]
              msgs[msgs.length - 1] = last
              return msgs
            })
          }

          if (type === 'text_delta') {
            setMessages(prev => {
              const msgs = [...prev]
              const last = { ...msgs[msgs.length - 1] }
              const blocks = last.blocks ?? []
              const lastBlock = blocks[blocks.length - 1]
              if (lastBlock?.kind === 'text') {
                last.blocks = [...blocks.slice(0, -1), { ...lastBlock, content: lastBlock.content + payload.delta }]
              } else {
                last.blocks = [...blocks, { kind: 'text' as const, content: payload.delta as string }]
              }
              msgs[msgs.length - 1] = last
              return msgs
            })
          }

          if (type === 'done') {
            setMessages(prev => {
              const msgs = [...prev]
              msgs[msgs.length - 1] = { ...msgs[msgs.length - 1], streaming: false }
              return msgs
            })
          }

          if (type === 'error') {
            setMessages(prev => {
              const msgs = [...prev]
              msgs[msgs.length - 1] = {
                ...msgs[msgs.length - 1],
                content: `Error: ${payload.error}`,
                streaming: false,
                error: true,
              }
              return msgs
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

  function selectSkill(skill: SkillOption) {
    const cursor = inputRef.current?.selectionStart ?? input.length
    const textBeforeCursor = input.slice(0, cursor)
    const lastSlash = textBeforeCursor.lastIndexOf('/')
    if (lastSlash === -1) {
      setSlashMenuOpen(false)
      return
    }
    const textAfterCursor = input.slice(cursor)
    const newInput = input.slice(0, lastSlash) + '/' + skill.id + ' ' + textAfterCursor
    setInput(newInput)
    setSlashMenuOpen(false)
    setTimeout(() => {
      if (inputRef.current) {
        const newCursor = lastSlash + skill.id.length + 2
        inputRef.current.focus()
        inputRef.current.setSelectionRange(newCursor, newCursor)
      }
    }, 0)
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

  function handleInputChange(e: ChangeEvent<HTMLTextAreaElement>) {
    const val = e.target.value
    setInput(val)
    const cursor = e.target.selectionStart ?? val.length
    const textBeforeCursor = val.slice(0, cursor)
    const lastSlash = textBeforeCursor.lastIndexOf('/')
    if (lastSlash !== -1) {
      const charBefore = lastSlash > 0 ? textBeforeCursor[lastSlash - 1] : null
      const isWordBoundary = charBefore === null || /\s/.test(charBefore)
      if (isWordBoundary) {
        const fragment = textBeforeCursor.slice(lastSlash + 1)
        if (!fragment.includes(' ')) {
          const filtered = skills.filter(s => s.id.startsWith(fragment))
          if (filtered.length > 0) {
            setSlashFilter(fragment)
            setSlashMenuOpen(true)
            setSlashIndex(0)
            return
          }
        }
      }
    }
    setSlashMenuOpen(false)
  }

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (slashMenuOpen) {
      if (e.key === 'ArrowDown') {
        e.preventDefault()
        setSlashIndex(i => (i + 1) % filteredSkills.length)
        return
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault()
        setSlashIndex(i => (i - 1 + filteredSkills.length) % filteredSkills.length)
        return
      }
      if (e.key === 'Enter' || e.key === 'Tab') {
        e.preventDefault()
        if (filteredSkills[slashIndex]) selectSkill(filteredSkills[slashIndex])
        return
      }
      if (e.key === 'Escape') {
        setSlashMenuOpen(false)
        return
      }
    }
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
            {msg.role === 'assistant'
              ? <AssistantMessage msg={msg} />
              : <div className="bubble">{linkify(msg.content)}</div>
            }
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
        <div className="input-row">
          {slashMenuOpen && filteredSkills.length > 0 && (
            <div className="slash-menu" ref={slashMenuRef}>
              <div className="slash-menu-items">
                {filteredSkills.map((skill, i) => (
                  <div
                    key={skill.id}
                    className={`slash-menu-item${i === slashIndex ? ' selected' : ''}`}
                    onMouseEnter={() => setSlashIndex(i)}
                    onMouseDown={e => { e.preventDefault(); selectSkill(skill) }}
                  >
                    <span className="slash-menu-item-name">/{skill.id}</span>
                    <span className="slash-menu-item-desc">{skill.description}</span>
                  </div>
                ))}
              </div>
              {SHOW_SKILL_HINT && (
                <div className="slash-menu-footer">↵ to select</div>
              )}
            </div>
          )}
          <textarea
            ref={inputRef}
            value={input}
            onChange={handleInputChange}
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
    </div>
  )
}
