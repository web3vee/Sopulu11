import { useState, useCallback } from 'react'
import './TicTacToe.css'

const WINNING_LINES = [
  [0, 1, 2], [3, 4, 5], [6, 7, 8],
  [0, 3, 6], [1, 4, 7], [2, 5, 8],
  [0, 4, 8], [2, 4, 6],
]

function checkWinner(board) {
  for (const [a, b, c] of WINNING_LINES) {
    if (board[a] && board[a] === board[b] && board[a] === board[c]) {
      return { winner: board[a], line: [a, b, c] }
    }
  }
  return null
}

function getComputerMove(board) {
  // Try to win
  for (const [a, b, c] of WINNING_LINES) {
    const cells = [board[a], board[b], board[c]]
    if (cells.filter((v) => v === 'O').length === 2 && cells.includes(null)) {
      return [a, b, c][cells.indexOf(null)]
    }
  }
  // Block player
  for (const [a, b, c] of WINNING_LINES) {
    const cells = [board[a], board[b], board[c]]
    if (cells.filter((v) => v === 'X').length === 2 && cells.includes(null)) {
      return [a, b, c][cells.indexOf(null)]
    }
  }
  // Take center
  if (board[4] === null) return 4
  // Take a corner
  const corners = [0, 2, 6, 8].filter((i) => board[i] === null)
  if (corners.length > 0) return corners[Math.floor(Math.random() * corners.length)]
  // Take any open
  const open = board.map((v, i) => (v === null ? i : null)).filter((v) => v !== null)
  return open[Math.floor(Math.random() * open.length)]
}

function TicTacToe({ onBack }) {
  const [board, setBoard] = useState(Array(9).fill(null))
  const [isPlayerTurn, setIsPlayerTurn] = useState(true)
  const [scores, setScores] = useState({ player: 0, computer: 0, draws: 0 })
  const [gameOver, setGameOver] = useState(false)
  const [statusMessage, setStatusMessage] = useState('Your turn! You are X')
  const [winLine, setWinLine] = useState(null)

  const resetGame = useCallback(() => {
    setBoard(Array(9).fill(null))
    setIsPlayerTurn(true)
    setGameOver(false)
    setStatusMessage('Your turn! You are X')
    setWinLine(null)
  }, [])

  const handleClick = useCallback(
    (index) => {
      if (board[index] || gameOver || !isPlayerTurn) return

      const newBoard = [...board]
      newBoard[index] = 'X'

      const result = checkWinner(newBoard)
      if (result) {
        setBoard(newBoard)
        setWinLine(result.line)
        setScores((s) => ({ ...s, player: s.player + 1 }))
        setStatusMessage('You win!')
        setGameOver(true)
        return
      }

      if (newBoard.every((cell) => cell !== null)) {
        setBoard(newBoard)
        setScores((s) => ({ ...s, draws: s.draws + 1 }))
        setStatusMessage("It's a draw!")
        setGameOver(true)
        return
      }

      setBoard(newBoard)
      setIsPlayerTurn(false)
      setStatusMessage('Computer is thinking...')

      setTimeout(() => {
        const move = getComputerMove(newBoard)
        const afterComputer = [...newBoard]
        afterComputer[move] = 'O'

        const compResult = checkWinner(afterComputer)
        if (compResult) {
          setBoard(afterComputer)
          setWinLine(compResult.line)
          setScores((s) => ({ ...s, computer: s.computer + 1 }))
          setStatusMessage('Computer wins!')
          setGameOver(true)
          return
        }

        if (afterComputer.every((cell) => cell !== null)) {
          setBoard(afterComputer)
          setScores((s) => ({ ...s, draws: s.draws + 1 }))
          setStatusMessage("It's a draw!")
          setGameOver(true)
          return
        }

        setBoard(afterComputer)
        setIsPlayerTurn(true)
        setStatusMessage('Your turn!')
      }, 400)
    },
    [board, gameOver, isPlayerTurn]
  )

  return (
    <div className="ttt-container">
      <div className="ttt-card">
        <div className="ttt-header">
          <button className="ttt-back-btn" onClick={onBack} title="Back to chat">
            &#8592; Back
          </button>
          <h1 className="ttt-title">Tic Tac Toe</h1>
        </div>

        <div className="ttt-scoreboard">
          <div className="ttt-score ttt-score-player">
            <span className="ttt-score-label">You (X)</span>
            <span className="ttt-score-value">{scores.player}</span>
          </div>
          <div className="ttt-score ttt-score-draw">
            <span className="ttt-score-label">Draws</span>
            <span className="ttt-score-value">{scores.draws}</span>
          </div>
          <div className="ttt-score ttt-score-computer">
            <span className="ttt-score-label">CPU (O)</span>
            <span className="ttt-score-value">{scores.computer}</span>
          </div>
        </div>

        <div className="ttt-status">{statusMessage}</div>

        <div className="ttt-board">
          {board.map((cell, i) => (
            <button
              key={i}
              className={`ttt-cell${cell ? ` ttt-cell-${cell}` : ''}${winLine?.includes(i) ? ' ttt-cell-win' : ''}${!cell && isPlayerTurn && !gameOver ? ' ttt-cell-hover' : ''}`}
              onClick={() => handleClick(i)}
              disabled={!!cell || gameOver || !isPlayerTurn}
            >
              {cell}
            </button>
          ))}
        </div>

        {gameOver && (
          <button className="ttt-play-again" onClick={resetGame}>
            Play Again
          </button>
        )}
      </div>
    </div>
  )
}

export default TicTacToe
