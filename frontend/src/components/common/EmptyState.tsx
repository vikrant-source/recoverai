import React from 'react';
import { SearchX } from 'lucide-react';

interface EmptyStateProps {
  message?: string;
  sub?: string;
}

export const EmptyState: React.FC<EmptyStateProps> = ({
  message = 'No results found',
  sub = 'Try adjusting your filters or search query.',
}) => (
  <div className="flex flex-col items-center justify-center py-16 text-center gap-3">
    <div className="rounded-full bg-gray-800/60 p-4 border border-gray-700/40">
      <SearchX className="h-8 w-8 text-gray-500" />
    </div>
    <div>
      <p className="text-gray-400 font-medium">{message}</p>
      <p className="text-gray-600 text-sm mt-1">{sub}</p>
    </div>
  </div>
);
