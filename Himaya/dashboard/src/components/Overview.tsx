import { Monitor, Activity, TrendingUp } from 'lucide-react';
import MetricCard from './MetricCard';

type Snapshot = {
  devices: Array<{ id: number; device_id: string; name: string; status: string; last_seen: string | null }>;
  events: Array<{ id: number; type: string; timestamp: string }>;
};

type Props = {
  snapshot: Snapshot | null;
};

export default function Overview({ snapshot }: Props) {
  const onlineCount = snapshot?.devices?.filter((d) => d.status === 'online').length ?? 0;
  const totalCount = snapshot?.devices?.length ?? 0;
  const recentEvents = snapshot?.events?.slice(0, 5) ?? [];

  return (
    <div className="content-grid">
      <div className="metrics">
        <MetricCard
          label="Online Devices"
          value={onlineCount}
          icon={Monitor}
          color="#22c55e"
          bg="bg-emerald-500/10"
          border="border-emerald-500/20"
        />
        <MetricCard
          label="Total Devices"
          value={totalCount}
          icon={Activity}
          color="#3b82f6"
          bg="bg-blue-500/10"
          border="border-blue-500/20"
        />
        <MetricCard
          label="Recent Events"
          value={recentEvents.length}
          icon={TrendingUp}
          color="#a855f7"
          bg="bg-violet-500/10"
          border="border-violet-500/20"
        />
        <MetricCard
          label="Connected"
          value={snapshot ? 'Live' : '—'}
          icon={Activity}
          color="#22c55e"
          bg="bg-emerald-500/10"
          border="border-emerald-500/20"
        />
      </div>

      <div className="card">
        <div className="card-header">
          <h3>Recent Events</h3>
        </div>
        <div className="card-body">
          <div className="event-list">
            {recentEvents.map((evt) => (
              <div key={evt.id} className="event-item">
                <div className="evt-icon">
                  <Activity size={14} />
                </div>
                <div>
                  <div className="evt-meta">{evt.type}</div>
                  <div className="evt-time">{new Date(evt.timestamp).toLocaleString()}</div>
                </div>
              </div>
            ))}
            {recentEvents.length === 0 && <p className="empty-state">No events yet</p>}
          </div>
        </div>
      </div>
    </div>
  );
}
