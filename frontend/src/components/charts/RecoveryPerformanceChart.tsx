import React from 'react';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from 'recharts';
import type { MetricsResponse } from '../../api/types';
import { formatPaise } from '../../utils/format';
import { LoadingSpinner } from '../common/LoadingSpinner';
import { ErrorState } from '../common/ErrorState';

interface Props {
  metrics: MetricsResponse | undefined;
  isLoading: boolean;
  isError: boolean;
}

const CustomTooltip = ({ active, payload }: { active?: boolean; payload?: Array<{ name: string; value: number }> }) => {
  if (active && payload && payload.length) {
    return (
      <div className="bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-sm shadow-xl">
        <p className="text-gray-300 font-medium">{payload[0].name}</p>
        <p className="text-white font-bold">{formatPaise(payload[0].value)}</p>
      </div>
    );
  }
  return null;
};

export const RecoveryPerformanceChart: React.FC<Props> = ({ metrics, isLoading, isError }) => {
  if (isLoading) return <LoadingSpinner className="h-48" />;
  if (isError || !metrics) return <ErrorState message="Could not load performance data." />;

  const data = [
    {
      name: 'Revenue at Risk',
      value: metrics.revenue_at_risk_paise,
      fill: '#ef4444',
    },
    {
      name: 'Revenue Recovered',
      value: metrics.revenue_recovered_paise,
      fill: '#22c55e',
    },
  ];

  return (
    <ResponsiveContainer width="100%" height={200}>
      <BarChart data={data} barSize={56} margin={{ top: 8, right: 8, left: 8, bottom: 8 }}>
        <XAxis
          dataKey="name"
          tick={{ fill: '#9ca3af', fontSize: 12 }}
          axisLine={false}
          tickLine={false}
        />
        <YAxis
          tickFormatter={(v: number) => formatPaise(v)}
          tick={{ fill: '#6b7280', fontSize: 10 }}
          axisLine={false}
          tickLine={false}
          width={90}
        />
        <Tooltip content={<CustomTooltip />} cursor={{ fill: 'rgba(255,255,255,0.03)' }} />
        <Bar dataKey="value" radius={[6, 6, 0, 0]}>
          {data.map((entry, index) => (
            <Cell key={index} fill={entry.fill} fillOpacity={0.85} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
};
