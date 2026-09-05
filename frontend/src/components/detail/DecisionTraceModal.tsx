import React from 'react';
import type { InterventionDetail } from '../../api/types';
import { Badge } from '../common/Badge';
import { formatPaise, formatConfidence, cleanDescription } from '../../utils/format';
import {
  CreditCard,
  Brain,
  Shield,
  Zap,
  ArrowDown,
  X,
  User,
} from 'lucide-react';

interface Props {
  detail: InterventionDetail;
}

const SectionCard: React.FC<{
  title: string;
  icon: React.ReactNode;
  children: React.ReactNode;
  colorClass: string;
  borderClass: string;
}> = ({ title, icon, children, colorClass, borderClass }) => (
  <div className={`rounded-xl border p-5 ${colorClass} ${borderClass}`}>
    <div className="flex items-center gap-2 mb-4">
      <div className="flex-shrink-0">{icon}</div>
      <h3 className="font-semibold text-sm tracking-wide">{title}</h3>
    </div>
    <div className="space-y-3 text-sm">{children}</div>
  </div>
);

const Field: React.FC<{ label: string; children: React.ReactNode }> = ({ label, children }) => (
  <div className="flex items-start justify-between gap-4">
    <span className="text-gray-500 text-xs shrink-0 pt-0.5">{label}</span>
    <div className="text-right">{children}</div>
  </div>
);

const Connector: React.FC = () => (
  <div className="flex flex-col items-center gap-0.5 py-1">
    <div className="w-px h-3 bg-gray-700" />
    <ArrowDown className="w-4 h-4 text-gray-600" />
    <div className="w-px h-3 bg-gray-700" />
  </div>
);

export const DecisionTrace: React.FC<Props> = ({ detail }) => {
  const { intervention: iv } = detail;
  const executorSuccess = iv.execution_status === 'SUCCESS';
  const executorFailed = iv.execution_status === 'FAILED';

  return (
    <div className="space-y-0">
      {/* ── Step 1: Payment Failed ─────────────────────────────────────────── */}
      <SectionCard
        title="Payment Event"
        icon={<CreditCard className="w-4 h-4 text-gray-400" />}
        colorClass="bg-gray-900/80"
        borderClass="border-gray-700/60"
      >
        <Field label="Transaction ID">
          <span className="font-txn text-blue-400">{detail.txn_id}</span>
        </Field>
        <Field label="Amount">
          <span className="text-white font-medium tabular-nums">
            {formatPaise(detail.amount_paise)} {detail.currency}
          </span>
        </Field>
        <Field label="Status">
          <Badge value={detail.status} type="status" />
        </Field>
        {detail.failure_code && (
          <Field label="Failure Code">
            <span className="text-red-400 text-xs font-medium">{detail.failure_code}</span>
          </Field>
        )}
        {detail.failure_description && (
          <Field label="Description">
            <span className="text-gray-400 text-xs text-right max-w-[240px] block">
              {cleanDescription(detail.failure_description)}
            </span>
          </Field>
        )}
        <Field label="Attempt #">
          <span className="text-gray-300">{detail.attempt_count}</span>
        </Field>
        <div className="pt-2 border-t border-gray-800 mt-2">
          <div className="flex items-center gap-2 text-xs text-gray-500">
            <User className="w-3.5 h-3.5" />
            <span>{detail.customer_id}</span>
            <span className="text-gray-700">·</span>
            <span>LTV: <span className="text-gray-300">{detail.ltv_tier}</span></span>
            <span className="text-gray-700">·</span>
            <span>Fraud: <span className="text-gray-300">{(detail.fraud_score * 100).toFixed(0)}%</span></span>
          </div>
        </div>
      </SectionCard>

      <Connector />

      {/* ── Step 2: AI Brain ───────────────────────────────────────────────── */}
      <SectionCard
        title="AI Brain  ·  Recommendation Only"
        icon={<Brain className="w-4 h-4 text-blue-400" />}
        colorClass="bg-blue-950/40"
        borderClass="border-blue-700/40"
      >
        <Field label="Recommended Action">
          <Badge value={iv.ai_recommendation} type="ai" />
        </Field>
        <Field label="Confidence">
          <div className="flex items-center gap-2 justify-end">
            <span className="text-white font-medium tabular-nums">
              {formatConfidence(iv.ai_confidence)}
            </span>
            <div className="w-16 h-1.5 rounded-full bg-gray-800 overflow-hidden">
              <div
                className="h-full rounded-full bg-blue-500"
                style={{ width: `${Math.round(iv.ai_confidence * 100)}%` }}
              />
            </div>
          </div>
        </Field>
        {iv.ai_failure_classification && (
          <Field label="Failure Classification">
            <span className="text-blue-300 text-xs">{iv.ai_failure_classification}</span>
          </Field>
        )}
        {iv.ai_reasoning && (
          <Field label="Reasoning">
            <span className="text-gray-400 text-xs italic text-right max-w-[240px] block">
              &ldquo;{iv.ai_reasoning}&rdquo;
            </span>
          </Field>
        )}
        <div className="pt-2 mt-2 border-t border-blue-900/40">
          <p className="text-blue-500 text-xs opacity-70">
            AI recommendation only — Policy Brakes have final authority.
          </p>
        </div>
      </SectionCard>

      <Connector />

      {/* ── Step 3: Policy Brakes ─────────────────────────────────────────── */}
      <SectionCard
        title="Policy Brakes  ·  Deterministic Authority"
        icon={<Shield className="w-4 h-4 text-amber-400" />}
        colorClass="bg-amber-950/30"
        borderClass="border-amber-700/40"
      >
        <Field label="Decision">
          <div className="flex items-center gap-2 justify-end">
            <Badge value={iv.policy_decision} type="policy" />
            {iv.policy_decision === 'ALLOW' && (
              <span className="text-green-400 text-xs">✓ Approved</span>
            )}
            {iv.policy_decision === 'BLOCK' && (
              <span className="text-red-400 text-xs">✗ Blocked</span>
            )}
            {iv.policy_decision === 'ESCALATE' && (
              <span className="text-amber-400 text-xs">↑ Escalated</span>
            )}
          </div>
        </Field>
        <Field label="Reason">
          <span className="text-gray-400 text-xs text-right max-w-[240px] block">
            {iv.policy_reason}
          </span>
        </Field>
        <Field label="Approved Action">
          <Badge value={iv.final_action} type="action" />
        </Field>
        {iv.ai_recommendation !== iv.final_action && (
          <div className="pt-2 mt-2 border-t border-amber-900/40">
            <p className="text-amber-500 text-xs">
              ⚠ Policy overrode AI recommendation ({iv.ai_recommendation} → {iv.final_action})
            </p>
          </div>
        )}
      </SectionCard>

      <Connector />

      <SectionCard
        title="Recovery Executor  ·  Final Action"
        icon={
          <Zap
            className={`w-4 h-4 ${
              executorSuccess ? 'text-green-400' : executorFailed ? 'text-red-400' : 'text-amber-400'
            }`}
          />
        }
        colorClass={
          executorSuccess
            ? 'bg-green-950/30'
            : executorFailed
            ? 'bg-red-950/30'
            : 'bg-amber-950/20'
        }
        borderClass={
          executorSuccess
            ? 'border-green-700/40'
            : executorFailed
            ? 'border-red-700/40'
            : 'border-amber-700/30'
        }
      >
        <Field label="Action Taken">
          <Badge value={iv.final_action} type="action" />
        </Field>
        <Field label="Execution Status">
          <Badge value={iv.execution_status} type="status" />
        </Field>

        {/* Recovery Outcome explicitly distinct from Action Execution */}
        <div className="pt-2 mt-2 border-t border-gray-800">
          <Field label="Recovery Outcome">
            <span className={`text-xs font-semibold ${
              detail.status === 'SUCCESS' ? 'text-green-400' :
              detail.status === 'AWAITING_PAYMENT' ? 'text-amber-400' :
              'text-gray-400'
            }`}>
              {detail.status === 'SUCCESS' ? 'RECOVERED' : detail.status}
            </span>
          </Field>
          <Field label="Recovered">
            {detail.status === 'SUCCESS' && iv.recovered_amount_paise > 0 ? (
              <span className="text-green-400 font-bold tabular-nums">
                {formatPaise(iv.recovered_amount_paise)}
              </span>
            ) : (
              <span className="text-gray-500 font-bold tabular-nums">₹0</span>
            )}
          </Field>
        </div>
      </SectionCard>
    </div>
  );
};

// ─── Modal Wrapper ────────────────────────────────────────────────────────────

interface ModalProps {
  txnId: string | null;
  detail: InterventionDetail | undefined;
  isLoading: boolean;
  isError: boolean;
  onClose: () => void;
}

export const DecisionTraceModal: React.FC<ModalProps> = ({
  txnId,
  detail,
  isLoading,
  isError,
  onClose,
}) => {
  if (!txnId) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-end"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />

      {/* Panel */}
      <div className="relative z-10 h-full w-full max-w-xl bg-gray-950 border-l border-gray-800 shadow-2xl flex flex-col overflow-hidden">
        {/* Panel header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-800 bg-gray-900/80 flex-shrink-0">
          <div>
            <h2 className="text-white font-semibold">Decision Trace</h2>
            <p className="text-gray-500 text-xs mt-0.5 font-txn">{txnId}</p>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-gray-500 hover:text-gray-300 hover:bg-gray-800 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Panel body */}
        <div className="flex-1 overflow-y-auto px-6 py-6">
          {isLoading && (
            <div className="flex items-center justify-center h-64">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500" />
            </div>
          )}
          {isError && (
            <ErrorStateInline message="Could not load decision trace." />
          )}
          {!isLoading && !isError && detail && <DecisionTrace detail={detail} />}
        </div>
      </div>
    </div>
  );
};

const ErrorStateInline: React.FC<{ message: string }> = ({ message }) => (
  <div className="flex flex-col items-center justify-center h-64 gap-3 text-center">
    <span className="text-red-400 text-sm">{message}</span>
  </div>
);
