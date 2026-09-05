import React from 'react';

type BadgeVariant =
  | 'ai'
  | 'policy-allow'
  | 'policy-block'
  | 'policy-escalate'
  | 'action-retry'
  | 'action-link'
  | 'action-escalate'
  | 'action-nothing'
  | 'status-success'
  | 'status-failed'
  | 'status-escalated'
  | 'status-skipped'
  | 'neutral'
  | 'amber';

const VARIANT_CLASSES: Record<BadgeVariant, string> = {
  'ai': 'bg-blue-900/60 text-blue-300 border border-blue-700/50',
  'policy-allow': 'bg-green-900/60 text-green-300 border border-green-700/50',
  'policy-block': 'bg-red-900/60 text-red-300 border border-red-700/50',
  'policy-escalate': 'bg-amber-900/60 text-amber-300 border border-amber-700/50',
  'action-retry': 'bg-indigo-900/60 text-indigo-300 border border-indigo-700/50',
  'action-link': 'bg-cyan-900/60 text-cyan-300 border border-cyan-700/50',
  'action-escalate': 'bg-amber-900/60 text-amber-300 border border-amber-700/50',
  'action-nothing': 'bg-gray-800/60 text-gray-400 border border-gray-700/50',
  'status-success': 'bg-green-900/60 text-green-300 border border-green-700/50',
  'status-failed': 'bg-red-900/60 text-red-300 border border-red-700/50',
  'status-escalated': 'bg-amber-900/60 text-amber-300 border border-amber-700/50',
  'status-skipped': 'bg-gray-800/60 text-gray-400 border border-gray-700/50',
  'neutral': 'bg-gray-800/60 text-gray-300 border border-gray-700/50',
  'amber': 'bg-amber-900/60 text-amber-300 border border-amber-700/50',
};

function resolveVariant(type: 'action' | 'status' | 'policy' | 'ai', value: string): BadgeVariant {
  if (type === 'action') {
    const v = value.toUpperCase();
    if (v === 'SILENT_RETRY') return 'action-retry';
    if (v === 'SEND_PAYMENT_LINK') return 'action-link';
    if (v === 'ESCALATE') return 'action-escalate';
    if (v === 'DO_NOTHING') return 'action-nothing';
  }
  if (type === 'status') {
    const v = value.toUpperCase();
    if (v === 'SUCCESS') return 'status-success';
    if (v === 'FAILED') return 'status-failed';
    if (v === 'ESCALATED') return 'status-escalated';
    if (v === 'SKIPPED') return 'status-skipped';
  }
  if (type === 'policy') {
    const v = value.toUpperCase();
    if (v === 'ALLOW') return 'policy-allow';
    if (v === 'BLOCK') return 'policy-block';
    if (v === 'ESCALATE') return 'policy-escalate';
  }
  if (type === 'ai') return 'ai';
  return 'neutral';
}

interface BadgeProps {
  value: string;
  type?: 'action' | 'status' | 'policy' | 'ai' | 'raw';
  variant?: BadgeVariant;
  className?: string;
}

export const Badge: React.FC<BadgeProps> = ({ value, type = 'raw', variant, className = '' }) => {
  const resolvedVariant =
    variant ?? (type !== 'raw' ? resolveVariant(type, value) : 'neutral');
  const classes = VARIANT_CLASSES[resolvedVariant] ?? VARIANT_CLASSES.neutral;

  const label = value.replace(/_/g, ' ');

  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium tracking-wide ${classes} ${className}`}
    >
      {label}
    </span>
  );
};
