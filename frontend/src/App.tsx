import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import type { KeyboardEvent, ChangeEvent } from 'react'

interface Message {
  role: 'user' | 'assistant'
  content: string
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

function getOrCreateSessionId() {
  let id = localStorage.getItem('lorekeeper_session_id')
  if (!id) {
    id = crypto.randomUUID()
    localStorage.setItem('lorekeeper_session_id', id)
  }
  return id
}

export default function App() {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [sessionId] = useState(getOrCreateSessionId)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

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
        body: JSON.stringify({ message: text, session_id: sessionId }),
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
    }
  }

  async function clearChat() {
    await fetch(`/api/session/${sessionId}`, { method: 'DELETE' })
    setMessages([])
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
              {linkify(msg.content)}
              {msg.streaming && <span className="cursor">▋</span>}
            </div>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      <div className="input-area">
        <textarea
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
