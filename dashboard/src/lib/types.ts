export type Platform = 'android' | 'windows' | 'ios' | 'macos' | 'linux'
export type OwnerType = 'child' | 'adult'
export type DeviceState = 'online' | 'offline' | 'locked' | 'paused'
export type CapValue = string | number | boolean | null

export interface Device {
  id: number
  device_id: string
  name: string
  platform: Platform
  ip: string | null
  owner_type: OwnerType
  status: 'online' | 'offline'
  last_seen: string | null
  created_at: string
  locked: boolean
  paused: boolean
  caps: Record<string, CapValue>
  agent_version: string | null
  state: DeviceState
}

export interface HubEvent {
  id: number | null
  device_id: string
  type: string
  data: Record<string, unknown>
  timestamp: string
}

export interface Rules {
  device_id: string
  blocked_categories: string[]
  blocked_domains: string[]
  allowed_domains: string[]
  bedtime_enabled: boolean
  bedtime_start: string
  bedtime_end: string
  snapshot_interval_s: number
  updated_at: string | null
  bedtime_active: boolean
  paused: boolean
  locked: boolean
  effective_blocked_domains: string[]
}

export type RulesPatch = Partial<
  Pick<
    Rules,
    | 'blocked_categories'
    | 'blocked_domains'
    | 'allowed_domains'
    | 'bedtime_enabled'
    | 'bedtime_start'
    | 'bedtime_end'
    | 'snapshot_interval_s'
  >
>

export interface Category {
  name: string
  label: string
  count: number
}

export interface Snapshot {
  id: number
  device_id: string
  filename: string
  timestamp: string
  url: string
}

export interface HistogramBucket {
  t: string
  dns_block: number
  alerts: number
  screenshots: number
  other: number
}

export interface Stats {
  generated_at: string
  devices: { total: number; online: number; locked: number; paused: number }
  events_24h: { total: number; by_type: Record<string, number> }
  alerts_24h: number
  histogram: HistogramBucket[]
  top_blocked: { host: string; count: number }[]
  snapshots_total: number
}

export interface EnrollUrl {
  kind: 'lan' | 'internet'
  label: string
  url: string
  windows_command: string
  mobile_url: string
  qr_path: string
}

export interface EnrollInfo {
  pin: string
  pin_expires_in: number
  urls: EnrollUrl[]
  is_cloud: boolean
  lan_ip: string
  dns_port: number | null
}

export interface HubSettings {
  version: string
  database: 'sqlite' | 'postgres'
  is_cloud: boolean
  public_url: string | null
  lan_ip: string
  port: number
  timezone: string
  dns: { running: boolean; enabled?: boolean; port?: number; upstream?: string; error?: string | null; queries?: number; blocked?: number }
  discovery: { running: boolean; port: number }
  retention: { events_days: number; snapshots_days: number; snapshots_per_device: number }
  admin_key_source: 'environment' | 'generated'
}

export type RemoteAction =
  | 'lock'
  | 'unlock'
  | 'pause'
  | 'unpause'
  | 'push_notification'
  | 'force_close_app'
  | 'snapshot'
  | 'live_view'
  | 'stop_live_view'
  | 'wipe'

export type WsMessage =
  | { type: 'snapshot'; devices: Device[]; events: HubEvent[] }
  | { type: 'event'; event: HubEvent }
  | { type: 'device'; device: Device }
  | { type: 'device_removed'; device_id: string }
  | { type: 'heartbeat'; device_id: string; timestamp: string }
  | { type: 'auth_failed' }
  | { type: 'pong' }
