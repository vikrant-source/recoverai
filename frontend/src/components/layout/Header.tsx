import React from 'react';
import { Brain, ShieldAlert } from 'lucide-react';
import { useHealth } from '../../api/hooks';
import { InlineSpinner } from '../common/LoadingSpinner';

export const Header: React.FC = () => {
  const { data: health, isLoading, isError } = useHealth();

  const isHealthy = !isLoading && !isError && health?.status === 'ok';
  const isUnhealthy = !isLoading && (isError || health?.status !== 'ok');

  return (
    <header className="border-b border-gray-800 bg-navy-900/80 backdrop-blur-sm sticky top-0 z-40">
      <div className="max-w-screen-2xl mx-auto px-6 py-4 flex items-center justify-between">
        {/* Left: Branding */}
        <div className="flex items-center gap-3">
          <div className="flex items-center justify-center w-9 h-9 rounded-lg bg-blue-600/20 border border-blue-600/40">
            <Brain className="w-5 h-5 text-blue-400" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="text-white font-bold text-lg tracking-tight">RecoverAI</span>
            </div>
            <p className="text-gray-500 text-xs leading-none">AI Revenue Recovery Agent</p>
          </div>
        </div>

        {/* Right: Status badges */}
        <div className="flex items-center gap-3">
          {/* Synthetic Mode indicator */}
          <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-amber-900/30 border border-amber-700/40">
            <ShieldAlert className="w-3.5 h-3.5 text-amber-400" />
            <span className="text-amber-300 text-xs font-medium">Synthetic / Test Mode</span>
          </div>

          {/* API Health indicator */}
          <div
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full border text-xs font-medium transition-colors ${
              isLoading
                ? 'bg-gray-800/60 border-gray-700/40 text-gray-500'
                : isHealthy
                ? 'bg-green-900/30 border-green-700/40 text-green-400'
                : 'bg-red-900/30 border-red-700/40 text-red-400'
            }`}
          >
            {isLoading ? (
              <InlineSpinner />
            ) : (
              <span
                className={`inline-block w-2 h-2 rounded-full ${
                  isHealthy ? 'bg-green-400' : isUnhealthy ? 'bg-red-400' : 'bg-gray-500'
                }`}
              />
            )}
            {isLoading ? 'Connecting…' : isHealthy ? 'API Online' : 'API Offline'}
          </div>
        </div>
      </div>
    </header>
  );
};
