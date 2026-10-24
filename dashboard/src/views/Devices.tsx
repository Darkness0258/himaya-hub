import { Plus, Smartphone } from 'lucide-react'
import { useEffect } from 'react'
import { DeviceRow } from '../components/DeviceRow'
import { EmptyState, LinkButton, Skeleton } from '../components/ui'
import { routeHref, useMedia, useNow, useRoute } from '../lib/hooks'
import { useHub } from '../lib/store'
import { DeviceDetail } from './DeviceDetail'

export function Devices() {
  const route = useRoute()
  const { devices, loaded } = useHub()
  const wide = useMedia('(min-width: 960px)')
  const now = useNow(30_000)
  const selected = devices.find((d) => d.device_id === route.deviceId)

  // On wide screens always show a device next to the list.
  useEffect(() => {
    if (wide && loaded && !route.deviceId && devices[0]) window.location.replace(routeHref({ view: 'devices', deviceId: devices[0].device_id }))
  }, [wide, loaded, route.deviceId, devices])

  const showList = wide || !route.deviceId
  const showDetail = wide || Boolean(route.deviceId)

  return (
    <div className={`page split ${route.deviceId ? 'split--detail' : ''}`}>
      {showList && (
        <section className="split__list" aria-labelledby="devices-title">
          <header className="page__head">
            <div>
              <h1 id="devices-title" className="page__title">
                Devices
              </h1>
              <p className="muted">{loaded ? (devices.length === 1 ? '1 device' : `${devices.length} devices`) : 'Loading'}</p>
            </div>
            <LinkButton href={routeHref({ view: 'enroll' })} variant="primary" size="sm" icon={<Plus size={16} aria-hidden="true" />}>
              Add a device
            </LinkButton>
          </header>
          {!loaded ? (
            <Skeleton lines={4} />
          ) : devices.length === 0 ? (
            <EmptyState icon={<Smartphone size={26} />} title="No devices yet" action={<LinkButton href={routeHref({ view: 'enroll' })} variant="primary" icon={<Plus size={18} aria-hidden="true" />}>Add a device</LinkButton>}>
              Nothing is being watched yet. Adding a device takes about two minutes.
            </EmptyState>
          ) : (
            <ul className="rows panel panel--flush">
              {devices.map((device) => (
                <DeviceRow key={device.device_id} device={device} now={now} selected={device.device_id === route.deviceId} />
              ))}
            </ul>
          )}
        </section>
      )}

      {showDetail && (
        <section className="split__detail">
          {selected ? (
            <DeviceDetail device={selected} />
          ) : loaded && route.deviceId ? (
            <EmptyState icon={<Smartphone size={26} />} title="That device isn't on your list" action={<LinkButton href={routeHref({ view: 'devices' })}>Back to devices</LinkButton>}>
              It may have been removed.
            </EmptyState>
          ) : !loaded ? (
            <Skeleton lines={5} />
          ) : null}
        </section>
      )}
    </div>
  )
}
