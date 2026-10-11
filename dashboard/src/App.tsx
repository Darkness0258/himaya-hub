import { useState, useEffect, useRef } from 'react'
import Overview from './components/Overview'
import DeviceList from './components/DeviceList'
import ControlPanel from './components/ControlPanel'
import EventFeed from './components/EventFeed'

type Device = {
  id: number
  device_id: string
  name: string
  platform: string
  ip: string | null
  status: string
  owner_type: string
  last_seen: string | null
}

type Event = {
  id: number
  device_id: string
  type: string
  data: Record<string, unknown>
  timestamp: string
}

type Snapshot = {
  devices: Device[]
  events: Event[]
}

type WSMessage = {
  type: string
  devices?: Device[]
  events?: Event[]
}

function App() {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null)
  const [selectedDevice, setSelectedDevice] = useState<string | null>(null)
  const [expandedDevice, setExpandedDevice] = useState<string | null>(null)
  const wsRef = useRef<WebSocket | null>(null)

  // WebSocket connection — runs once on mount, independent of selectedDevice
  useEffect(() => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const wsUrl = `${protocol}//${window.location.host}/ws`
    const ws = new WebSocket(wsUrl)
    wsRef.current = ws

    ws.onopen = () => console.log('[WS] Connected')
    ws.onclose = () => console.log('[WS] Disconnected')

    ws.onmessage = (event) => {
      try {
        const msg: WSMessage = JSON.parse(event.data)
        if (msg.type === 'snapshot' && msg.devices && msg.events) {
          setSnapshot({ devices: msg.devices, events: msg.events })
        }
      } catch (e) {
        console.error('[WS] Parse error:', e)
      }
    }

    return () => ws.close()
  }, [])

  // Initial REST fetch + periodic refresh
  useEffect(() => {
    const loadSnapshot = async () => {
      const [devicesRes, eventsRes] = await Promise.all([
        fetch('/devices').then(r => r.json()),
        fetch('/events').then(r => r.json())
      ])
      setSnapshot({ devices: devicesRes, events: eventsRes })
      if (devicesRes.length > 0 && !selectedDevice) {
        setSelectedDevice(devicesRes[0].device_id)
      }
    }
    loadSnapshot()

    const interval = setInterval(loadSnapshot, 10000)
    return () => clearInterval(interval)
  }, [selectedDevice])

  
  const handleDeviceSelect = (deviceId: string) => {
    setSelectedDevice(deviceId)
  }

  const handleToggleExpand = (deviceId: string) => {
    setExpandedDevice(expandedDevice === deviceId ? null : deviceId)
  }

  if (!snapshot) {
    return (
      <div className="app-shell">
        <header className="header">
          <h1>Himaya</h1>
          <span className="status connecting">Connecting...</span>
        </header>
        <main className="main">Loading dashboard...</main>
      </div>
    )
  }

  const device = snapshot.devices.find(d => d.device_id === selectedDevice)

  return (
    <div className="app-shell">
      <header className="header">
        <h1>Himaya</h1>
        <div className="header-actions">
          <span className={`status ${snapshot.devices.some(d => d.status === 'online') ? 'online' : 'offline'}`}>
            {snapshot.devices.filter(d => d.status === 'online').length} / {snapshot.devices.length} Online
          </span>
        </div>
      </header>

      <main className="main">
        <Overview snapshot={snapshot} />

        <div className="content-grid">
          <section className="panel devices-panel">
            <DeviceList
              devices={snapshot.devices}
              selectedDevice={selectedDevice}
              onSelect={handleDeviceSelect}
              expandedDevice={expandedDevice}
              onToggleExpand={handleToggleExpand}
            />
          </section>

          <section className="panel control-panel">
            <ControlPanel device={device} />
          </section>
        </div>

        <EventFeed events={snapshot.events} />
      </main>
    </div>
  )
}

export default App