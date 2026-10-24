import { Lock, LockOpen, Pause, Play } from 'lucide-react'
import { useState } from 'react'
import { lastSeenText, PLATFORM_LABEL } from '../lib/describe'
import { routeHref } from '../lib/hooks'
import { useHub, useRunAction } from '../lib/store'
import type { Device } from '../lib/types'
import { DeviceIcon } from './DeviceIcon'
import { IconButton, StateChip } from './ui'

export function DeviceRow({ device, now, selected, quickActions }: { device: Device; now: number; selected?: boolean; quickActions?: boolean }) {
  const { beats } = useHub()
  const run = useRunAction()
  const [busy, setBusy] = useState('')
  const offlineNote = device.status === 'offline' ? ' It will take effect when the device is back online.' : ''

  async function act(key: string, action: 'lock' | 'unlock' | 'pause' | 'unpause', text: string) {
    setBusy(key)
    await run(device.device_id, action, {}, text + offlineNote)
    setBusy('')
  }

  return (
    <li className={`row ${selected ? 'is-selected' : ''}`} data-state={device.state}>
      <a className="row__main" href={routeHref({ view: 'devices', deviceId: device.device_id })} aria-current={selected ? 'true' : undefined}>
        <span className="row__icon">
          <DeviceIcon device={device} />
          {device.status === 'online' && beats[device.device_id] && <span key={beats[device.device_id]} className="pulse" aria-hidden="true" />}
        </span>
        <span className="row__text">
          <span className="row__name">{device.name}</span>
          <span className="row__sub">{lastSeenText(device, now)}</span>
          <span className="row__sub row__sub--faint">
            {PLATFORM_LABEL[device.platform]}
            {device.owner_type === 'adult' ? ', adult' : ''}
          </span>
        </span>
        <StateChip device={device} />
      </a>
      {quickActions && (
        <div className="row__actions">
          <IconButton
            label={device.locked ? `Unlock ${device.name}` : `Lock ${device.name}`}
            active={device.locked}
            busy={busy === 'lock'}
            onClick={() => act('lock', device.locked ? 'unlock' : 'lock', device.locked ? `${device.name} unlocked.` : `${device.name} locked.`)}
          >
            {device.locked ? <LockOpen size={18} aria-hidden="true" /> : <Lock size={18} aria-hidden="true" />}
          </IconButton>
          <IconButton
            label={device.paused ? `Resume internet on ${device.name}` : `Pause internet on ${device.name}`}
            active={device.paused}
            busy={busy === 'pause'}
            onClick={() => act('pause', device.paused ? 'unpause' : 'pause', device.paused ? `Internet resumed on ${device.name}.` : `Internet paused on ${device.name}.`)}
          >
            {device.paused ? <Play size={18} aria-hidden="true" /> : <Pause size={18} aria-hidden="true" />}
          </IconButton>
        </div>
      )}
    </li>
  )
}
