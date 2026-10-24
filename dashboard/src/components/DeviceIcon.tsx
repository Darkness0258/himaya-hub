import { Laptop, Monitor, Smartphone, Tablet } from 'lucide-react'
import type { Device } from '../lib/types'

export function DeviceIcon({ device, size = 22 }: { device: Pick<Device, 'platform' | 'name'>; size?: number }) {
  const looksLikeTablet = /tab|ipad|pad/i.test(device.name)
  const Icon = device.platform === 'android' ? (looksLikeTablet ? Tablet : Smartphone) : /laptop|book/i.test(device.name) ? Laptop : Monitor
  return (
    <span className="devicetile" aria-hidden="true">
      <Icon size={size} strokeWidth={1.8} />
    </span>
  )
}
