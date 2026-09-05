import React from 'react';
import type { LucideIcon } from 'lucide-react';

interface KpiCardProps {
  label: string;
  value: string;
  sub?: string;
  icon: LucideIcon;
  accentColor?: 'blue' | 'green' | 'amber' | 'red';
  isLoading?: boolean;
}

const ACCENT: Record<string, string> = {
  blue: 'border-blue-700/40 bg-blue-600/10',
  green: 'border-green-700/40 bg-green-600/10',
  amber: 'border-amber-700/40 bg-amber-600/10',
  red: 'border-red-700/40 bg-red-600/10',
};

const ICON_ACCENT: Record<string, string> = {
  blue: 'text-blue-400 bg-blue-900/40 border-blue-700/40',
  green: 'text-green-400 bg-green-900/40 border-green-700/40',
  amber: 'text-amber-400 bg-amber-900/40 border-amber-700/40',
  red: 'text-red-400 bg-red-900/40 border-red-700/40',
};

export const KpiCard: React.FC<KpiCardProps> = ({
  label,
  value,
  sub,
  icon: Icon,
  accentColor = 'blue',
  isLoading = false,
}) => {
  const accentClass = ACCENT[accentColor] ?? ACCENT.blue;
  const iconClass = ICON_ACCENT[accentColor] ?? ICON_ACCENT.blue;

  return (
    <div
      className={`rounded-xl border p-5 flex items-start gap-4 transition-all ${accentClass} bg-gray-900/80`}
    >
      <div className={`flex-shrink-0 rounded-lg border p-2.5 ${iconClass}`}>
        <Icon className="w-5 h-5" />
      </div>
      <div className="min-w-0">
        <p className="text-gray-400 text-xs font-medium uppercase tracking-widest truncate">{label}</p>
        {isLoading ? (
          <div className="mt-2 h-7 w-28 rounded bg-gray-700/60 animate-pulse" />
        ) : (
          <p className="text-white text-2xl font-bold mt-0.5 tabular-nums">{value}</p>
        )}
        {sub && !isLoading && (
          <p className="text-gray-500 text-xs mt-1">{sub}</p>
        )}
      </div>
    </div>
  );
};
