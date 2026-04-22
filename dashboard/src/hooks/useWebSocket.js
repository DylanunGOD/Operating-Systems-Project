import { useEffect, useState, useCallback, useRef } from 'react'

export function useWebSocket(url, onMessage) {
  const [isConnected, setIsConnected] = useState(false)
  const [lastMessage, setLastMessage] = useState(null)
  const ws = useRef(null)
  const reconnectAttempts = useRef(0)
  const maxReconnectAttempts = 5
  const reconnectDelay = useRef(1000)

  const connect = useCallback(() => {
    try {
      ws.current = new WebSocket(url)

      ws.current.onopen = () => {
        console.log('WebSocket connected')
        setIsConnected(true)
        reconnectAttempts.current = 0
        reconnectDelay.current = 1000
      }

      ws.current.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data)
          setLastMessage(message)
          if (onMessage) {
            onMessage(message)
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
        console.log('WebSocket disconnected')
        setIsConnected(false)

        if (reconnectAttempts.current < maxReconnectAttempts) {
          reconnectAttempts.current++
          console.log(
            `Reconnecting... Attempt ${reconnectAttempts.current}/${maxReconnectAttempts}`
          )
          setTimeout(() => {
            reconnectDelay.current = Math.min(reconnectDelay.current * 2, 30000)
            connect()
          }, reconnectDelay.current)
        }
      }
    } catch (error) {
      console.error('WebSocket connection failed:', error)
      setIsConnected(false)
    }
  }, [url, onMessage])

  useEffect(() => {
    connect()

    return () => {
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
