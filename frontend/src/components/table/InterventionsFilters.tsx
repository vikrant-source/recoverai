import React, { useRef } from 'react';
import { Search, RefreshCw, X } from 'lucide-react';

interface FiltersProps {
  finalAction: string;
  executionStatus: string;
  search: string;
  isRefreshing: boolean;
  onFinalActionChange: (v: string) => void;
  onExecutionStatusChange: (v: string) => void;
  onSearchChange: (v: string) => void;
  onRefresh: () => void;
}

const FINAL_ACTIONS = [
  { value: '', label: 'All Actions' },
  { value: 'SILENT_RETRY', label: 'Silent Retry' },
  { value: 'SEND_PAYMENT_LINK', label: 'Payment Link' },
  { value: 'ESCALATE', label: 'Escalate' },
  { value: 'DO_NOTHING', label: 'Do Nothing' },
];

const EXECUTION_STATUSES = [
  { value: '', label: 'All Outcomes' },
  { value: 'SUCCESS', label: 'Success' },
  { value: 'FAILED', label: 'Failed' },
  { value: 'ESCALATED', label: 'Escalated' },
  { value: 'SKIPPED', label: 'Skipped' },
];

const SELECT_CLASS =
  'bg-gray-900 border border-gray-700 text-gray-300 text-sm rounded-lg px-3 py-2 focus:outline-none focus:border-blue-600 focus:ring-1 focus:ring-blue-600/30 transition-colors';

export const InterventionsFilters: React.FC<FiltersProps> = ({
  finalAction,
  executionStatus,
  search,
  isRefreshing,
  onFinalActionChange,
  onExecutionStatusChange,
  onSearchChange,
  onRefresh,
}) => {
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const handleSearch = (e: React.ChangeEvent<HTMLInputElement>) => {
    const v = e.target.value;
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => onSearchChange(v), 300);
  };

  return (
    <div className="flex flex-wrap items-center gap-3">
      {/* Search */}
      <div className="relative flex-1 min-w-[180px] max-w-xs">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500 pointer-events-none" />
        <input
          type="text"
          placeholder="Search transaction ID…"
          defaultValue={search}
          onChange={handleSearch}
          className="w-full bg-gray-900 border border-gray-700 text-gray-300 text-sm rounded-lg pl-9 pr-8 py-2 focus:outline-none focus:border-blue-600 focus:ring-1 focus:ring-blue-600/30 transition-colors placeholder-gray-600"
        />
        {search && (
          <button
            onClick={() => onSearchChange('')}
            className="absolute right-2.5 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-300 transition-colors"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        )}
      </div>

      {/* Final Action filter */}
      <select
        value={finalAction}
        onChange={(e) => onFinalActionChange(e.target.value)}
        className={SELECT_CLASS}
      >
        {FINAL_ACTIONS.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>

      {/* Outcome filter */}
      <select
        value={executionStatus}
        onChange={(e) => onExecutionStatusChange(e.target.value)}
        className={SELECT_CLASS}
      >
        {EXECUTION_STATUSES.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>

      {/* Refresh */}
      <button
        onClick={onRefresh}
        disabled={isRefreshing}
        className="flex items-center gap-1.5 px-3 py-2 rounded-lg border border-gray-700 text-gray-400 hover:text-gray-200 hover:border-gray-600 text-sm transition-colors disabled:opacity-50"
      >
        <RefreshCw className={`w-3.5 h-3.5 ${isRefreshing ? 'animate-spin' : ''}`} />
        Refresh
      </button>
    </div>
  );
};
