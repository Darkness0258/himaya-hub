import { useState } from 'react';
import { Lock, Wifi, Activity, Clock, Power, Trash2 } from 'lucide-react';

type Device = {
  id: number;
  device_id: string;
  name: string;
  platform: string;
  ip: string | null;
  status: string;
  owner_type: string;
  last_seen: string | null;
};

type Props = {
  deviceId: string;
  device: Device | undefined;
};

export default function ControlPanel({ deviceId, device }: Props) {
  const [action, setAction] = useState<string>('');
  const [message, setMessage] = useState('');

  const sendAction = (actionType: string) => {
    console.log(`Sending ${actionType} to ${deviceId}`);
  };

  const actionButtons: { label: string; action: string; icon: typeof Lock; danger?: boolean }[] = [
    { label: 'LOCK', action: 'lock', icon: Lock },
    { label: 'BLOCK', action: 'block_internet', icon: Wifi, danger: true },
    { label: 'PAUSE', action: 'pause', icon: Activity },
    { label: 'PUSH', action: 'push_notification', icon: Power },
    { label: 'CLOSE', action: 'force_close_app', icon: Trash2 },
  ];

  return (
    <div className="card">
      <div className="card-header">
        <h3>Control Panel</h3>
      </div>
      <div className="card-body">
        {device && (
          <div className="device-detail-row">
            <span className="label">Device</span>
            <span className="value">{device.name} ({device.device_id})</span>
          </div>
        )}
        <div className="action-btns">
          {actionButtons.map(({ label, action: actionType, icon: Icon, danger }) => (
            <button
              key={actionType}
              className={danger ? 'danger' : ''}
              onClick={() => sendAction(actionType)}
              disabled={!device}
            >
              <Icon size={14} />
              {label}
            </button>
          ))}
        </div>

        <div className="tabs" style={{ marginTop: '1rem' }}>
          <button className="tab active">Send</button>
          <button className="tab">Rules</button>
          <button className="tab">Logs</button>
        </div>

        {action === 'push_notification' && (
          <div style={{ marginTop: '1rem', backgroundColor: 'rgba(59,130,246,0.08)', border: '1px solid #3b82f6', borderRadius: '8px', padding: '0.75rem' }}>
            <label style={{ fontWeight: 600, color: '#e2e8f0', display: 'block', marginBottom: '0.5rem' }}>
              Notification Message
            </label>
            <textarea
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              placeholder="Type a message to your child's device..."
              style={{ width: '100%', minHeight: '80px', background: '#1a2538', color: '#e2e8f0', border: '1px solid #334155', borderRadius: '6px', padding: '0.5rem', fontFamily: 'inherit', resize: 'vertical' }}
            />
            <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.5rem' }}>
              <button onClick={() => { sendAction('push_notification'); setMessage(''); }} style={{ padding: '0.4rem 0.75rem', borderRadius: '6px', border: '1px solid #334155', background: '#3b82f6', color: '#fff', cursor: 'pointer', fontWeight: 600 }}>Send</button>
              <button onClick={() => setMessage('')} style={{ padding: '0.4rem 0.75rem', borderRadius: '6px', border: '1px solid #334155', background: 'transparent', color: '#94a3b8', cursor: 'pointer' }}>Cancel</button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
