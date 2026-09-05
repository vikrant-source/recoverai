import React from 'react';
import { AlertTriangle, RefreshCw } from 'lucide-react';

interface ErrorStateProps {
  message?: string;
  onRetry?: () => void;
}

export const ErrorState: React.FC<ErrorStateProps> = ({
  message = 'Failed to load data from the backend.',
  onRetry,
}) => (
  <div className="flex flex-col items-center justify-center py-16 text-center gap-4">
    <div className="rounded-full bg-red-900/30 p-4 border border-red-700/40">
      <AlertTriangle className="h-8 w-8 text-red-400" />
    </div>
    <div>
      <p className="text-red-400 font-medium">API Error</p>
      <p className="text-gray-500 text-sm mt-1 max-w-sm">{message}</p>
    </div>
    {onRetry && (
      <button
        onClick={onRetry}
        className="flex items-center gap-2 px-4 py-2 rounded-lg bg-gray-800 hover:bg-gray-700 text-gray-300 text-sm transition-colors border border-gray-700"
      >
        <RefreshCw className="h-4 w-4" />
        Retry
      </button>
    )}
  </div>
);
