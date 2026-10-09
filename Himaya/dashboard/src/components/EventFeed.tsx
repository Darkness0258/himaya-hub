import { ChevronRight, Wrench, AlertTriangle, Clock, Power } from 'lucide-react';

type Event = {
  id: number;
  device_id: string;
  type: string;
  data: Record<string, unknown>;
  timestamp: string;
};

type Props = {
  events: Event[];
};

function eventTypeIcon(type: string) {
  switch (type) {
    case 'heartbeat':
      return <Activity size={14} />;
    case 'vpn_attempt':
      return <Wrench size={14} />;
    case 'dns_block':
      return <AlertTriangle size={14} />;
    case 'device_locked':
      return <Lock size={14} />;
    case 'device_went_dark':
      return <Power size={14} />;
    case 'policy_sync':
      return <Shield size={14} />;
    case 'screenshot':
      return <Clock size={14} />;
    default:
      return <Activity size={14} />;
  }
}

function eventTypeLabel(type: string) {
  const map: Record<string, string> = {
    heartbeat: 'Heartbeat',
    vpn_attempt: 'VPN Attempt',
    dns_block: 'DNS Blocked',
    device_locked: 'Device Locked',
    device_went_dark: 'Device Offline',
    policy_sync: 'Policy Sync',
    screenshot: 'Screenshot',
  };
  return map[type] || type;
}

export default function EventFeed({ events }: Props) {
  return (
    <div className="card">
      <div className="card-header">
        <h3>Event Feed</h3>
      </div>
      <div className="card-body">
        <div className="event-list">
          {[...events].reverse().map((evt) => (
            <div key={evt.id} className="event-item">
              <div className="evt-icon" style={{ backgroundColor: 'rgba(59,130,246,0.15)', color: '#3b82f6' }}>
                {eventTypeIcon(evt.type)}
              </div>
              <div>
                <div className="evt-meta">{eventTypeLabel(evt.type)}</div>
                <div className="evt-time">{new Date(evt.timestamp).toLocaleString()}</div>
              </div>
            </div>
          ))}
          {events.length === 0 && <p style={{ color: '#64748b', fontStyle: 'italic' }}>No events yet</p>}
        </div>
      </div>
    </div>
  );
}
