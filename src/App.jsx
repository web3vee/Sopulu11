import { useState, useCallback } from 'react'
import './App.css'

function generateId() {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 7)
}

function createSession() {
  return {
    id: generateId(),
    title: 'New Session',
    messages: [],
    createdAt: new Date().toISOString(),
  }
}

function App() {
  const [sessions, setSessions] = useState(() => {
    const initial = createSession()
    return [initial]
  })
  const [activeSessionId, setActiveSessionId] = useState(() => sessions[0].id)
  const [inputValue, setInputValue] = useState('')
  const [sidebarOpen, setSidebarOpen] = useState(true)

  const activeSession = sessions.find((s) => s.id === activeSessionId)

  const handleNewSession = useCallback(() => {
    const newSession = createSession()
    setSessions((prev) => [newSession, ...prev])
    setActiveSessionId(newSession.id)
    setInputValue('')
  }, [])

  const handleDeleteSession = useCallback(
    (id) => {
      setSessions((prev) => {
        const updated = prev.filter((s) => s.id !== id)
        if (updated.length === 0) {
          const fresh = createSession()
          setActiveSessionId(fresh.id)
          return [fresh]
        }
        if (id === activeSessionId) {
          setActiveSessionId(updated[0].id)
        }
        return updated
      })
    },
    [activeSessionId]
  )

  const handleSendMessage = useCallback(
    (e) => {
      e.preventDefault()
      const text = inputValue.trim()
      if (!text) return

      setSessions((prev) =>
        prev.map((s) => {
          if (s.id !== activeSessionId) return s
          const newMessages = [
            ...s.messages,
            { id: generateId(), text, sender: 'user', timestamp: new Date().toISOString() },
          ]
          return {
            ...s,
            messages: newMessages,
            title: s.messages.length === 0 ? text.slice(0, 30) : s.title,
          }
        })
      )
      setInputValue('')
    },
    [inputValue, activeSessionId]
  )

  return (
    <div className="app">
      <aside className={`sidebar ${sidebarOpen ? 'open' : 'closed'}`}>
        <div className="sidebar-header">
          <h2>Sessions</h2>
          <button className="toggle-btn" onClick={() => setSidebarOpen(false)} title="Close sidebar">
            &times;
          </button>
        </div>

        <button className="new-session-btn" onClick={handleNewSession}>
          <span className="plus-icon">+</span>
          New Session
        </button>

        <div className="session-list">
          {sessions.map((session) => (
            <div
              key={session.id}
              className={`session-item ${session.id === activeSessionId ? 'active' : ''}`}
              onClick={() => setActiveSessionId(session.id)}
            >
              <span className="session-title">{session.title}</span>
              <button
                className="delete-btn"
                onClick={(e) => {
                  e.stopPropagation()
                  handleDeleteSession(session.id)
                }}
                title="Delete session"
              >
                &times;
              </button>
            </div>
          ))}
        </div>
      </aside>

      <main className="main">
        <header className="main-header">
          {!sidebarOpen && (
            <button className="menu-btn" onClick={() => setSidebarOpen(true)} title="Open sidebar">
              &#9776;
            </button>
          )}
          <h1>{activeSession?.title || 'New Session'}</h1>
        </header>

        <div className="messages">
          {activeSession?.messages.length === 0 && (
            <div className="empty-state">
              <div className="empty-icon">&#128172;</div>
              <h3>Start a new conversation</h3>
              <p>Type a message below to get started.</p>
            </div>
          )}
          {activeSession?.messages.map((msg) => (
            <div key={msg.id} className={`message ${msg.sender}`}>
              <div className="message-bubble">{msg.text}</div>
              <span className="message-time">
                {new Date(msg.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
              </span>
            </div>
          ))}
        </div>

        <form className="input-area" onSubmit={handleSendMessage}>
          <input
            type="text"
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            placeholder="Type a message..."
            autoFocus
          />
          <button type="submit" className="send-btn" disabled={!inputValue.trim()}>
            Send
          </button>
        </form>
      </main>
    </div>
  )
}

export default App
