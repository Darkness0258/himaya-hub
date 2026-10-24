import {
  Ban,
  BedDouble,
  Camera,
  Eraser,
  Info,
  Lock,
  LockOpen,
  MessageSquareText,
  Pause,
  Play,
  Plus,
  ScrollText,
  ShieldAlert,
  TriangleAlert,
  Wifi,
  WifiOff,
  X,
} from 'lucide-react'
import type { IconKey, Tone } from '../lib/describe'

const ICONS = {
  ban: Ban,
  vpn: ShieldAlert,
  offline: WifiOff,
  online: Wifi,
  lock: Lock,
  unlock: LockOpen,
  pause: Pause,
  play: Play,
  message: MessageSquareText,
  camera: Camera,
  rules: ScrollText,
  plus: Plus,
  alert: TriangleAlert,
  close: X,
  erase: Eraser,
  info: Info,
} as const

export function EventIcon({ icon, tone, size = 18 }: { icon: IconKey; tone: Tone; size?: number }) {
  const Icon = ICONS[icon] ?? Info
  return (
    <span className={`bubble bubble--${tone}`} aria-hidden="true">
      <Icon size={size} strokeWidth={2} />
    </span>
  )
}

export { BedDouble }
