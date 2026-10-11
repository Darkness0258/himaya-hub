import { useState } from 'react';
import { Lock, Wifi, Activity, Power, Trash2 } from 'lucide-react';

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
  device: Device | undefined;
};

export default function ControlPanel({ device }: Props) {
  const [activeAction, setActiveAction] = useState<string>('');
  const [message, setMessage] = useState('');

  const sendAction = async (actionType: string) => {
    if (!device || !device.device_id) return;
    // Strict allowlist validation: alphanumeric, dash, underscore only (1-64 chars)
    if (!/^[a-zA-Z0-9_-]{1,64}$/.test(device.device_id)) {
      console.error('sendAction blocked: invalid device_id format');
      return;
    }
    try {
      // Use relative URL to avoid hardcoded origin (SSRF/CSRF defense)
      await fetch(`/admin/${device.device_id}/action`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: actionType })
      });
      setActiveAction(actionType);
    } catch (e) {
      console.error('Action failed:', e);
    }
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
              onClick={() => { sendAction(actionType); setActiveAction(actionType); }}
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

        {activeAction === 'push_notification' && (
          <div className="notification-form">
            <label style={{ fontWeight: 600, color: '#e2e8f0', display: 'block', marginBottom: '0.5rem' }}>
              Notification Message
            </label>
            <textarea
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              placeholder="Type a message to your child's device..."
            />
            <div className="btn-row">
              <button onClick={() => { sendAction('push_notification'); setMessage(''); }} className="btn-primary">Send</button>
              <button onClick={() => setMessage('')} className="btn-secondary">Cancel</button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
