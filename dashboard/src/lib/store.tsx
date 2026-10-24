import { createContext, useCallback, useContext, useEffect, useMemo, useReducer, useRef } from 'react'
import type { ReactNode } from 'react'
import { api, getApiKey, setUnauthorizedHandler } from './api'
import { useToast } from './toast'
import type { Category, Device, HubEvent, RemoteAction, Stats, WsMessage } from './types'

export type Connection = 'connecting' | 'live' | 'reconnecting'

interface HubState {
  devices: Device[]
  events: HubEvent[]
  stats: Stats | null
  categories: Category[]
  conn: Connection
  loaded: boolean
  loadError: string | null
  beats: Record<string, number>
}

type Action =
  | { type: 'loaded'; devices: Device[]; events: HubEvent[] }
  | { type: 'devices'; devices: Device[] }
  | { type: 'device'; device: Device }
  | { type: 'device_removed'; deviceId: string }
  | { type: 'events'; events: HubEvent[] }
  | { type: 'event'; event: HubEvent }
  | { type: 'stats'; stats: Stats }
  | { type: 'categories'; categories: Category[] }
  | { type: 'conn'; conn: Connection }
  | { type: 'beat'; deviceId: string }
  | { type: 'loadError'; message: string | null }

const MAX_EVENTS = 400

const initial: HubState = {
  devices: [],
  events: [],
  stats: null,
  categories: [],
  conn: 'connecting',
  loaded: false,
  loadError: null,
  beats: {},
}

/** Newest first, no duplicates (events that have an id), capped. */
function mergeEvents(current: HubEvent[], incoming: HubEvent[]): HubEvent[] {
  const byKey = new Map<string, HubEvent>()
  for (const event of [...incoming, ...current]) {
    const key = event.id !== null ? `id:${event.id}` : `t:${event.timestamp}:${event.device_id}:${event.type}`
    if (!byKey.has(key)) byKey.set(key, event)
  }
  return [...byKey.values()].sort((a, b) => Date.parse(b.timestamp) - Date.parse(a.timestamp) || (b.id ?? 0) - (a.id ?? 0)).slice(0, MAX_EVENTS)
}

function upsertDevice(devices: Device[], device: Device): Device[] {
  const index = devices.findIndex((d) => d.device_id === device.device_id)
  if (index === -1) return [...devices, device]
  const next = devices.slice()
  next[index] = device
  return next
}

function reducer(state: HubState, action: Action): HubState {
  switch (action.type) {
    case 'loaded':
      return { ...state, devices: action.devices, events: mergeEvents(state.events, action.events), loaded: true, loadError: null }
    case 'devices':
      return { ...state, devices: action.devices }
    case 'device':
      return { ...state, devices: upsertDevice(state.devices, action.device) }
    case 'device_removed':
      return { ...state, devices: state.devices.filter((d) => d.device_id !== action.deviceId) }
    case 'events':
      return { ...state, events: mergeEvents(state.events, action.events) }
    case 'event':
      return { ...state, events: mergeEvents(state.events, [action.event]) }
    case 'stats':
      return { ...state, stats: action.stats }
    case 'categories':
      return { ...state, categories: action.categories }
    case 'conn':
      return state.conn === action.conn ? state : { ...state, conn: action.conn }
    case 'beat':
      return { ...state, beats: { ...state.beats, [action.deviceId]: Date.now() } }
    case 'loadError':
      return { ...state, loadError: action.message }
  }
}

interface HubContextValue extends HubState {
  refresh: () => Promise<void>
  refreshStats: () => Promise<void>
  applyDevice: (device: Device) => void
  loadMoreEvents: (filter?: { device_id?: string; type?: string }) => Promise<number>
  categoryLabels: Record<string, string>
}

const HubContext = createContext<HubContextValue | null>(null)

const STATS_EVENT_TYPES = new Set(['dns_block', 'vpn_attempt', 'device_went_dark', 'agent_stopped', 'screenshot', 'enforcement_notice'])

function socketUrl(): string {
  return `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}/ws`
}

export function HubProvider({ children, onSignOut }: { children: ReactNode; onSignOut: () => void }) {
  const [state, dispatch] = useReducer(reducer, initial)
  const toast = useToast()
  const signOutRef = useRef(onSignOut)
  const toastRef = useRef(toast)
  const devicesRef = useRef<Device[]>([])
  useEffect(() => {
    signOutRef.current = onSignOut
    toastRef.current = toast
    devicesRef.current = state.devices
  })

  const refreshStats = useCallback(async () => {
    try {
      dispatch({ type: 'stats', stats: await api.stats() })
    } catch {
      /* the next tick will try again */
    }
  }, [])

  const refresh = useCallback(async () => {
    try {
      const [devices, events] = await Promise.all([api.devices(), api.events({ limit: 100 })])
      dispatch({ type: 'loaded', devices, events })
    } catch (error) {
      dispatch({ type: 'loadError', message: error instanceof Error ? error.message : 'Could not load your devices.' })
    }
  }, [])

  // Initial load, categories, and a slow stats refresh.
  useEffect(() => {
    setUnauthorizedHandler(() => signOutRef.current())
    void refresh()
    void refreshStats()
    api.categories().then((categories) => dispatch({ type: 'categories', categories })).catch(() => undefined)
    const statsTimer = window.setInterval(() => void refreshStats(), 60_000)
    return () => {
      window.clearInterval(statsTimer)
      setUnauthorizedHandler(null)
    }
  }, [refresh, refreshStats])

  // Live feed with automatic reconnect. REST polling keeps the page fresh while it is down.
  useEffect(() => {
    let socket: WebSocket | null = null
    let closed = false
    let attempt = 0
    let reconnectTimer = 0
    let statsTimer = 0

    const scheduleStats = () => {
      window.clearTimeout(statsTimer)
      statsTimer = window.setTimeout(() => void refreshStats(), 1500)
    }

    const handle = (message: WsMessage) => {
      switch (message.type) {
        case 'snapshot':
          attempt = 0
          dispatch({ type: 'devices', devices: message.devices })
          dispatch({ type: 'events', events: message.events })
          dispatch({ type: 'conn', conn: 'live' })
          break
        case 'event': {
          dispatch({ type: 'event', event: message.event })
          if (STATS_EVENT_TYPES.has(message.event.type)) scheduleStats()
          if (message.event.type === 'device_paired') toastRef.current.push(`${String(message.event.data.name ?? 'A device')} was added.`, 'ok')
          const known = devicesRef.current.some((d) => d.device_id === message.event.device_id)
          if (!known && !message.event.device_id.startsWith('network-')) void refresh()
          break
        }
        case 'device':
          dispatch({ type: 'device', device: message.device })
          break
        case 'device_removed':
          dispatch({ type: 'device_removed', deviceId: message.device_id })
          break
        case 'heartbeat':
          dispatch({ type: 'beat', deviceId: message.device_id })
          break
        case 'auth_failed':
          closed = true
          signOutRef.current()
          break
        case 'pong':
          break
      }
    }

    const connect = () => {
      dispatch({ type: 'conn', conn: attempt === 0 ? 'connecting' : 'reconnecting' })
      socket = new WebSocket(socketUrl())
      socket.onopen = () => socket?.send(JSON.stringify({ type: 'auth', key: getApiKey() }))
      socket.onmessage = (message) => {
        try {
          handle(JSON.parse(String(message.data)) as WsMessage)
        } catch {
          /* ignore a malformed frame */
        }
      }
      socket.onclose = (event) => {
        if (closed) return
        if (event.code === 4401) {
          signOutRef.current()
          return
        }
        attempt += 1
        dispatch({ type: 'conn', conn: 'reconnecting' })
        reconnectTimer = window.setTimeout(connect, Math.min(15_000, 1000 * 2 ** Math.min(attempt, 4)))
      }
      socket.onerror = () => socket?.close()
    }

    connect()
    const pingTimer = window.setInterval(() => {
      if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: 'ping' }))
    }, 25_000)
    const pollTimer = window.setInterval(() => {
      if (socket?.readyState !== WebSocket.OPEN) void refresh()
    }, 15_000)

    return () => {
      closed = true
      window.clearTimeout(reconnectTimer)
      window.clearTimeout(statsTimer)
      window.clearInterval(pingTimer)
      window.clearInterval(pollTimer)
      socket?.close()
    }
  }, [refresh, refreshStats])

  const applyDevice = useCallback((device: Device) => dispatch({ type: 'device', device }), [])

  const loadMoreEvents = useCallback(
    async (filter: { device_id?: string; type?: string } = {}): Promise<number> => {
      const oldest = state.events.filter((e) => e.id !== null).reduce<number | null>((min, e) => (min === null || (e.id as number) < min ? (e.id as number) : min), null)
      if (oldest === null) return 0
      const older = await api.events({ limit: 100, before_id: oldest, ...filter })
      dispatch({ type: 'events', events: older })
      return older.length
    },
    [state.events],
  )

  const categoryLabels = useMemo(() => Object.fromEntries(state.categories.map((c) => [c.name, c.label])), [state.categories])
  const value = useMemo<HubContextValue>(
    () => ({ ...state, refresh, refreshStats, applyDevice, loadMoreEvents, categoryLabels }),
    [state, refresh, refreshStats, applyDevice, loadMoreEvents, categoryLabels],
  )
  return <HubContext.Provider value={value}>{children}</HubContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export function useHub(): HubContextValue {
  const value = useContext(HubContext)
  if (!value) throw new Error('useHub must be used inside <HubProvider>')
  return value
}

/** Runs a remote action, updates the device from the reply and reports the outcome. */
// eslint-disable-next-line react-refresh/only-export-components
export function useRunAction() {
  const { applyDevice } = useHub()
  const toast = useToast()
  return useCallback(
    async (deviceId: string, action: RemoteAction, payload: Record<string, unknown> = {}, successText?: string): Promise<boolean> => {
      try {
        const reply = await api.action(deviceId, action, payload)
        applyDevice(reply.device)
        if (successText) toast.push(successText, 'ok')
        return true
      } catch (error) {
        toast.push(error instanceof Error ? error.message : 'That did not work.', 'bad')
        return false
      }
    },
    [applyDevice, toast],
  )
}
