import { useEffect, useState, useCallback, useRef } from 'react'

const MAX_RECONNECT_ATTEMPTS = 5
const INITIAL_RECONNECT_DELAY_MS = 1000
const MAX_RECONNECT_DELAY_MS = 30000

export function useWebSocket(url, onMessage) {
  const [isConnected, setIsConnected] = useState(false)
  const [lastMessage, setLastMessage] = useState(null)
  const ws = useRef(null)
  const reconnectAttempts = useRef(0)
  const reconnectDelay = useRef(INITIAL_RECONNECT_DELAY_MS)
  const reconnectTimer = useRef(null)
  const onMessageRef = useRef(onMessage)
  const manuallyClosed = useRef(false)

  useEffect(() => {
    onMessageRef.current = onMessage
  }, [onMessage])

  const connect = useCallback(() => {
    try {
      ws.current = new WebSocket(url)

      ws.current.onopen = () => {
        setIsConnected(true)
        reconnectAttempts.current = 0
        reconnectDelay.current = INITIAL_RECONNECT_DELAY_MS
      }

      ws.current.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data)
          setLastMessage(message)
          if (onMessageRef.current) {
            onMessageRef.current(message)
          }
        } catch (error) {
          console.error('Failed to parse WebSocket message:', error)
        }
      }

      ws.current.onerror = (error) => {
        console.error('WebSocket error:', error)
        setIsConnected(false)
      }

      ws.current.onclose = () => {
        setIsConnected(false)
        if (manuallyClosed.current) return

        if (reconnectAttempts.current < MAX_RECONNECT_ATTEMPTS) {
          reconnectAttempts.current += 1
          reconnectTimer.current = setTimeout(() => {
            reconnectDelay.current = Math.min(
              reconnectDelay.current * 2,
              MAX_RECONNECT_DELAY_MS
            )
            connect()
          }, reconnectDelay.current)
        }
      }
    } catch (error) {
      console.error('WebSocket connection failed:', error)
      setIsConnected(false)
    }
  }, [url])

  useEffect(() => {
    manuallyClosed.current = false
    connect()

    return () => {
      manuallyClosed.current = true
      if (reconnectTimer.current) {
        clearTimeout(reconnectTimer.current)
        reconnectTimer.current = null
      }
      if (ws.current) {
        ws.current.close()
      }
    }
  }, [connect])

  const send = useCallback((message) => {
    if (ws.current && ws.current.readyState === WebSocket.OPEN) {
      ws.current.send(JSON.stringify(message))
    }
  }, [])

  return { isConnected, lastMessage, send }
}
