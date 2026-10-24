import { useCallback, useEffect, useState } from 'react'
import { StarMark } from './components/Brand'
import { Shell } from './components/Shell'
import { api, ApiError, loadStoredKey, restoreKey, storeKey } from './lib/api'
import { useRoute, useTheme } from './lib/hooks'
import { HubProvider } from './lib/store'
import { ToastProvider } from './lib/toast'
import { Activity } from './views/Activity'
import { Devices } from './views/Devices'
import { Enroll } from './views/Enroll'
import { Home } from './views/Home'
import { Login } from './views/Login'
import { Screens } from './views/Screens'
import { Settings } from './views/Settings'

const TITLES = { home: 'Home', devices: 'Devices', activity: 'Activity', screens: 'Screens', enroll: 'Add a device', settings: 'Settings' } as const

function Routes({ onSignOut }: { onSignOut: () => void }) {
  const route = useRoute()
  useEffect(() => {
    document.title = `${TITLES[route.view]} - Himaya`
    document.getElementById('main')?.focus({ preventScroll: true })
    window.scrollTo(0, 0)
  }, [route.view])

  switch (route.view) {
    case 'devices':
      return <Devices />
    case 'activity':
      return <Activity />
    case 'screens':
      return <Screens />
    case 'enroll':
      return <Enroll />
    case 'settings':
      return <Settings onSignOut={onSignOut} />
    default:
      return <Home />
  }
}

export default function App() {
  useTheme()
  const [phase, setPhase] = useState<'checking' | 'out' | 'in'>(() => (loadStoredKey() ? 'checking' : 'out'))
  const [notice, setNotice] = useState('')

  useEffect(() => {
    if (phase !== 'checking') return
    const key = restoreKey()
    api
      .checkKey(key)
      .then(() => setPhase('in'))
      .catch((error: unknown) => {
        if (error instanceof ApiError && error.status === 401) {
          storeKey('', false)
          setNotice('Your saved key no longer works. Please sign in again.')
        } else {
          setNotice(error instanceof Error ? error.message : 'Could not reach the hub.')
        }
        setPhase('out')
      })
  }, [phase])

  const signOut = useCallback((message = '') => {
    storeKey('', false)
    setNotice(message)
    setPhase('out')
  }, [])

  return (
    <ToastProvider>
      {phase === 'checking' ? (
        <div className="splash" role="status" aria-label="Loading">
          <StarMark size={64} />
        </div>
      ) : phase === 'out' ? (
        <Login
          notice={notice}
          onSuccess={(key, remember) => {
            storeKey(key, remember)
            setNotice('')
            setPhase('in')
          }}
        />
      ) : (
        <HubProvider onSignOut={() => signOut('You were signed out. Please sign in again.')}>
          <Shell>
            <Routes onSignOut={() => signOut()} />
          </Shell>
        </HubProvider>
      )}
    </ToastProvider>
  )
}
