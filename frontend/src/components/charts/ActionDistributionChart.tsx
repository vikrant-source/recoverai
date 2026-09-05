import React from 'react';
import {
  PieChart,
  Pie,
  Cell,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts';
import type { ActionDistribution } from '../../api/types';
import { LoadingSpinner } from '../common/LoadingSpinner';
import { ErrorState } from '../common/ErrorState';

interface Props {
  data: ActionDistribution | undefined;
  isLoading: boolean;
  isError: boolean;
}

const ACTION_COLORS: Record<string, string> = {
  SILENT_RETRY: '#6366f1',       // indigo
  SEND_PAYMENT_LINK: '#06b6d4',  // cyan
  ESCALATE: '#f59e0b',           // amber
  DO_NOTHING: '#6b7280',         // gray
};

const ACTION_LABELS: Record<string, string> = {
  SILENT_RETRY: 'Silent Retry',
  SEND_PAYMENT_LINK: 'Payment Link',
  ESCALATE: 'Escalate',
  DO_NOTHING: 'Do Nothing',
};

const CustomTooltip = ({
  active,
  payload,
}: {
  active?: boolean;
  payload?: Array<{ name: string; value: number; payload: { action: string } }>;
}) => {
  if (active && payload && payload.length) {
    const action = payload[0].payload.action;
    return (
      <div className="bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-sm shadow-xl">
        <p className="text-gray-300 font-medium">{ACTION_LABELS[action] ?? action}</p>
        <p className="text-white font-bold">{payload[0].value} interventions</p>
      </div>
    );
  }
  return null;
};

export const ActionDistributionChart: React.FC<Props> = ({ data, isLoading, isError }) => {
  if (isLoading) return <LoadingSpinner className="h-48" />;
  if (isError || !data) return <ErrorState message="Could not load action data." />;

  const chartData = data.filter((d) => d.count > 0);

  if (chartData.length === 0) {
    return (
      <div className="flex items-center justify-center h-48 text-gray-600 text-sm">
        No interventions recorded yet.
      </div>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={200}>
      <PieChart>
        <Pie
          data={chartData}
          dataKey="count"
          nameKey="action"
          cx="50%"
          cy="50%"
          outerRadius={72}
          innerRadius={38}
          paddingAngle={2}
        >
          {chartData.map((entry) => (
            <Cell
              key={entry.action}
              fill={ACTION_COLORS[entry.action] ?? '#9ca3af'}
              stroke="transparent"
            />
          ))}
        </Pie>
        <Tooltip content={<CustomTooltip />} />
        <Legend
          formatter={(value: string) => (
            <span style={{ color: '#9ca3af', fontSize: '11px' }}>
              {ACTION_LABELS[value] ?? value}
            </span>
          )}
          iconType="circle"
          iconSize={8}
        />
      </PieChart>
    </ResponsiveContainer>
  );
};
