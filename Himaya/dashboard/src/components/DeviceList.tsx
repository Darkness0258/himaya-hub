import { useState } from 'react';
import { Monitor, Cpu, Mobile, Key, Wifi, Lock, Shield } from 'lucide-react';

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
  devices: Device[];
  selectedDevice: string | null;
  onSelect: (id: string) => void;
  expandedDevice: string | null;
  onToggleExpand: (id: string) => void;
};

const platformIcons: Record<string, typeof Monitor> = {
  android: Mobile,
  windows: Monitor,
  ios: Iphone,
  macos: Monitor,
};

function PlatformIcon({ platform }: { platform: string }) {
  const Icon = platformIcons[platform] || Monitor;
  return <Icon size={18} />;
}

export default function DeviceList({ devices, selectedDevice, onSelect, expandedDevice, onToggleExpand }: Props) {
  return (
    <div className="card">
      <div className="card-header">
        <h3>Devices</h3>
      </div>
      <div className="card-body">
        <div className="device-list">
          {devices.map((dev) => {
            const Icon = platformIcons[dev.platform] || Monitor;
            const isActive = dev.device_id === selectedDevice;
            const isExpanded = dev.device_id === expandedDevice;
            return (
              <div
                key={dev.device_id}
                className={`device-item ${isActive ? 'active' : ''}`}
                onClick={() => {
                  onSelect(dev.device_id);
                  onToggleExpand(dev.device_id);
                }}
              >
                <div className={`device-icon ${isExpanded ? 'device-icon-large' : ''}`}>
                  <Icon size={18} />
                </div>
                <div className="device-info">
                  <div className="device-name">{dev.name}</div>
                  <div className="device-meta">
                    {dev.device_id} · {dev.platform} · {dev.owner_type}
                  </div>
                </div>
                <div className="device-status" style={{ color: dev.status === 'online' ? '#22c55e' : '#ef4444' }}>
                  {dev.status}
                </div>
                <div className="device-actions">
                  <button title="Details">
                    <ChevronRight size={14} />
                  </button>
                </div>
              </div>
            );
          })}
          {devices.length === 0 && <p style={{ color: '#64748b', fontStyle: 'italic' }}>No devices registered</p>}
        </div>
      </div>
    </div>
  );
}
