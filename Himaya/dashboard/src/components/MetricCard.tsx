import { IconType } from 'lucide-react';

type MetricCardProps = {
  label: string;
  value: string | number;
  icon: IconType;
  color: string;
  bg: string;
  border: string;
  suffix?: string;
};

export default function MetricCard({ label, value, icon: Icon, color, bg, border, suffix }: MetricCardProps) {
  return (
    <div className="metric-card">
      <div className={`icon ${bg} ${border}`}>
        <Icon size={20} style={{ color }} />
      </div>
      <div>
        <div className="value">{value}{suffix}</div>
        <div className="label">{label}</div>
      </div>
    </div>
  );
}
