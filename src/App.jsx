import { useState, useCallback } from 'react'
import './App.css'

function calculateWinner(squares) {
  const lines = [
    [0, 1, 2], [3, 4, 5], [6, 7, 8],
    [0, 3, 6], [1, 4, 7], [2, 5, 8],
    [0, 4, 8], [2, 4, 6],
  ]
  for (const [a, b, c] of lines) {
    if (squares[a] && squares[a] === squares[b] && squares[a] === squares[c]) {
      return { winner: squares[a], line: [a, b, c] }
    }
  }
  return null
}

function Square({ value, onClick, highlight }) {
  return (
    <button
      className={`square ${value ? 'filled' : ''} ${highlight ? 'winning' : ''}`}
      onClick={onClick}
    >
      {value && <span className={`mark ${value}`}>{value}</span>}
    </button>
  )
}

function App() {
  const [history, setHistory] = useState([Array(9).fill(null)])
  const [stepNumber, setStepNumber] = useState(0)
  const [xIsNext, setXIsNext] = useState(true)
  const [scores, setScores] = useState({ X: 0, O: 0, draws: 0 })

  const current = history[stepNumber]
  const result = calculateWinner(current)
  const winner = result?.winner
  const winningLine = result?.line || []
  const isDraw = !winner && current.every(Boolean)

  const handleClick = useCallback((i) => {
    if (current[i] || winner) return
    const next = current.slice()
    next[i] = xIsNext ? 'X' : 'O'
    const newHistory = history.slice(0, stepNumber + 1).concat([next])
    setHistory(newHistory)
    setStepNumber(newHistory.length - 1)
    setXIsNext(!xIsNext)

    const newResult = calculateWinner(next)
    if (newResult?.winner) {
      setScores(prev => ({ ...prev, [newResult.winner]: prev[newResult.winner] + 1 }))
    } else if (next.every(Boolean)) {
      setScores(prev => ({ ...prev, draws: prev.draws + 1 }))
    }
  }, [current, winner, xIsNext, history, stepNumber])

  const handleReset = useCallback(() => {
    setHistory([Array(9).fill(null)])
    setStepNumber(0)
    setXIsNext(true)
  }, [])

  const handleNewGame = useCallback(() => {
    setHistory([Array(9).fill(null)])
    setStepNumber(0)
    setXIsNext(true)
    setScores({ X: 0, O: 0, draws: 0 })
  }, [])

  const handleUndo = useCallback(() => {
    if (stepNumber > 0) {
      setStepNumber(stepNumber - 1)
      setXIsNext(stepNumber % 2 === 0 ? false : true)
    }
  }, [stepNumber])

  let status
  if (winner) {
    status = <span>Winner: <span className={`mark ${winner}`}>{winner}</span></span>
  } else if (isDraw) {
    status = "It's a draw!"
  } else {
    status = <span>Next: <span className={`mark ${xIsNext ? 'X' : 'O'}`}>{xIsNext ? 'X' : 'O'}</span></span>
  }

  return (
    <div className="app">
      <div className="game-container">
        <h1 className="title">Tic Tac Toe</h1>

        <div className="scoreboard">
          <div className="score-item">
            <span className="mark X">X</span>
            <span className="score-value">{scores.X}</span>
          </div>
          <div className="score-item">
            <span className="score-label">Draw</span>
            <span className="score-value">{scores.draws}</span>
          </div>
          <div className="score-item">
            <span className="mark O">O</span>
            <span className="score-value">{scores.O}</span>
          </div>
        </div>

        <div className={`status ${winner ? 'winner' : ''} ${isDraw ? 'draw' : ''}`}>
          {status}
        </div>

        <div className="board">
          {current.map((value, i) => (
            <Square
              key={i}
              value={value}
              onClick={() => handleClick(i)}
              highlight={winningLine.includes(i)}
            />
          ))}
        </div>

        <div className="controls">
          <button className="control-btn" onClick={handleUndo} disabled={stepNumber === 0}>
            Undo
          </button>
          <button className="control-btn primary" onClick={handleReset}>
            Restart
          </button>
          <button className="control-btn" onClick={handleNewGame}>
            New Game
          </button>
        </div>
      </div>
    </div>
  )
}

export default App
