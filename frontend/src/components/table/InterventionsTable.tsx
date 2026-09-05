import React from 'react';
import type { InterventionRow } from '../../api/types';
import { Badge } from '../common/Badge';
import { LoadingSpinner } from '../common/LoadingSpinner';
import { ErrorState } from '../common/ErrorState';
import { EmptyState } from '../common/EmptyState';
import { formatPaise, formatConfidence, cleanDescription } from '../../utils/format';
import { ChevronRight } from 'lucide-react';

interface Props {
  items: InterventionRow[];
  total: number;
  isLoading: boolean;
  isError: boolean;
  isFetching: boolean;
  onRowClick: (txnId: string) => void;
  onRetry: () => void;
}

export const InterventionsTable: React.FC<Props> = ({
  items,
  isLoading,
  isError,
  isFetching,
  onRowClick,
  onRetry,
}) => {
  if (isLoading) return <LoadingSpinner className="h-64" />;
  if (isError) return <ErrorState message="Could not load recovery events." onRetry={onRetry} />;
  if (!isLoading && items.length === 0) return <EmptyState />;

  return (
    <div className={`relative transition-opacity ${isFetching ? 'opacity-70' : 'opacity-100'}`}>
      {isFetching && (
        <div className="absolute top-2 right-2 z-10">
          <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-blue-500" />
        </div>
      )}
      <div className="overflow-x-auto rounded-xl border border-gray-800">
        <table className="w-full text-sm min-w-[900px]">
          <thead>
            <tr className="border-b border-gray-800 bg-gray-900/60">
              <th className="text-left px-4 py-3 text-gray-500 font-medium text-xs uppercase tracking-wider">
                Txn ID
              </th>
              <th className="text-right px-4 py-3 text-gray-500 font-medium text-xs uppercase tracking-wider">
                Amount
              </th>
              <th className="text-left px-4 py-3 text-gray-500 font-medium text-xs uppercase tracking-wider">
                Failure
              </th>
              <th className="text-left px-4 py-3 text-gray-500 font-medium text-xs uppercase tracking-wider">
                AI Rec.
              </th>
              <th className="text-center px-4 py-3 text-gray-500 font-medium text-xs uppercase tracking-wider">
                Confidence
              </th>
              <th className="text-left px-4 py-3 text-gray-500 font-medium text-xs uppercase tracking-wider">
                Policy
              </th>
              <th className="text-left px-4 py-3 text-gray-500 font-medium text-xs uppercase tracking-wider">
                Final Action
              </th>
              <th className="text-left px-4 py-3 text-gray-500 font-medium text-xs uppercase tracking-wider">
                Outcome
              </th>
              <th className="text-right px-4 py-3 text-gray-500 font-medium text-xs uppercase tracking-wider">
                Recovered
              </th>
              <th className="px-2 py-3" />
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-800/60">
            {items.map((row) => (
              <tr
                key={row.intervention_id}
                onClick={() => onRowClick(row.txn_id)}
                className="hover:bg-gray-800/40 cursor-pointer transition-colors group"
              >
                <td className="px-4 py-3">
                  <span className="font-txn text-blue-400 group-hover:text-blue-300 transition-colors">
                    {row.txn_id}
                  </span>
                </td>
                <td className="px-4 py-3 text-right tabular-nums text-gray-300 whitespace-nowrap">
                  {formatPaise(row.amount_paise)}
                </td>
                <td className="px-4 py-3 max-w-[140px]">
                  {row.failure_code ? (
                    <span className="text-gray-400 text-xs truncate block" title={cleanDescription(row.failure_description) ?? ''}>
                      {row.failure_code.replace(/_/g, ' ')}
                    </span>
                  ) : (
                    <span className="text-gray-600">—</span>
                  )}
                </td>
                <td className="px-4 py-3">
                  <Badge value={row.ai_recommendation} type="ai" />
                </td>
                <td className="px-4 py-3 text-center">
                  <div className="flex flex-col items-center gap-1">
                    <span className="text-gray-300 text-xs font-medium tabular-nums">
                      {formatConfidence(row.ai_confidence)}
                    </span>
                    <div className="w-12 h-1 rounded-full bg-gray-800 overflow-hidden">
                      <div
                        className="h-full rounded-full bg-blue-500"
                        style={{ width: `${Math.round(row.ai_confidence * 100)}%` }}
                      />
                    </div>
                  </div>
                </td>
                <td className="px-4 py-3">
                  <Badge value={row.policy_decision} type="policy" />
                </td>
                <td className="px-4 py-3">
                  <Badge value={row.final_action} type="action" />
                </td>
                <td className="px-4 py-3">
                  <Badge value={row.execution_status} type="status" />
                </td>
                <td className="px-4 py-3 text-right tabular-nums whitespace-nowrap">
                  {row.recovered_amount_paise > 0 ? (
                    <span className="text-green-400 font-medium">
                      {formatPaise(row.recovered_amount_paise)}
                    </span>
                  ) : (
                    <span className="text-gray-600">—</span>
                  )}
                </td>
                <td className="px-2 py-3">
                  <ChevronRight className="w-4 h-4 text-gray-600 group-hover:text-gray-400 transition-colors" />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};
