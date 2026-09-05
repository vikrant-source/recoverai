import React, { useState, useCallback, useEffect } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import {
  Zap,
  TrendingUp,
  AlertTriangle,
  DollarSign,
} from 'lucide-react';

import { Layout } from '../components/layout/Layout';
import { KpiCard } from '../components/kpi/KpiCard';
import { RecoveryPerformanceChart } from '../components/charts/RecoveryPerformanceChart';
import { ActionDistributionChart } from '../components/charts/ActionDistributionChart';
import { InterventionsFilters } from '../components/table/InterventionsFilters';
import { InterventionsTable } from '../components/table/InterventionsTable';
import { TablePagination } from '../components/table/TablePagination';
import { DecisionTraceModal } from '../components/detail/DecisionTraceModal';

import {
  useMetrics,
  useActionDistribution,
  useInterventions,
  useInterventionDetail,
} from '../api/hooks';
import type { InterventionFilters } from '../api/types';
import { formatPaise, formatBps } from '../utils/format';

const DEFAULT_FILTERS: InterventionFilters = {
  final_action: '',
  execution_status: '',
  search: '',
  page: 1,
  page_size: 20,
};

const Dashboard: React.FC = () => {
  const queryClient = useQueryClient();

  // ── Filter state ────────────────────────────────────────────────────────
  const [filters, setFilters] = useState<InterventionFilters>(DEFAULT_FILTERS);
  const [selectedTxnId, setSelectedTxnId] = useState<string | null>(null);

  // Reset to page 1 when any filter changes (not page itself)
  const updateFilter = useCallback(
    (key: keyof InterventionFilters, value: string) => {
      setFilters((prev) => ({ ...prev, [key]: value, page: 1 }));
    },
    []
  );

  // ── Data hooks ──────────────────────────────────────────────────────────
  const metrics = useMetrics();
  const actionDist = useActionDistribution();
  const interventions = useInterventions(filters);
  const detail = useInterventionDetail(selectedTxnId);

  // ── Keyboard: close modal on Escape ─────────────────────────────────────
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setSelectedTxnId(null);
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, []);

  // ── Refresh all dashboard queries ────────────────────────────────────────
  const handleRefresh = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ['metrics'] });
    queryClient.invalidateQueries({ queryKey: ['action-distribution'] });
    queryClient.invalidateQueries({ queryKey: ['interventions'] });
  }, [queryClient]);

  const m = metrics.data;

  return (
    <Layout>
      {/* ── Hero tagline ────────────────────────────────────────────────── */}
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-white">Recover revenue. Safely.</h1>
        <p className="text-gray-500 text-sm mt-1">
          AI recommends → deterministic Policy Brakes decide → executor acts.
        </p>
      </div>

      {/* ── KPI Cards ───────────────────────────────────────────────────── */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        <KpiCard
          label="Revenue at Risk"
          value={m ? formatPaise(m.revenue_at_risk_paise) : '—'}
          sub={m ? `${m.total_interventions} interventions processed` : undefined}
          icon={AlertTriangle}
          accentColor="red"
          isLoading={metrics.isLoading}
        />
        <KpiCard
          label="Revenue Recovered"
          value={m ? formatPaise(m.revenue_recovered_paise) : '—'}
          sub={m ? `${m.successful_txns} transactions recovered` : undefined}
          icon={DollarSign}
          accentColor="green"
          isLoading={metrics.isLoading}
        />
        <KpiCard
          label="Recovery Rate"
          value={m ? formatBps(m.recovery_rate_bps) : '—'}
          sub={m ? `${m.failed_txns} transactions still failed` : undefined}
          icon={TrendingUp}
          accentColor="blue"
          isLoading={metrics.isLoading}
        />
        <KpiCard
          label="Escalated Cases"
          value={m ? String(m.escalated_count) : '—'}
          sub="Require human review"
          icon={Zap}
          accentColor="amber"
          isLoading={metrics.isLoading}
        />
      </div>

      {/* ── Charts row ──────────────────────────────────────────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-8">
        <div className="rounded-xl border border-gray-800 bg-gray-900/60 p-5">
          <h2 className="text-gray-200 font-semibold text-sm mb-1">Recovery Performance</h2>
          <p className="text-gray-600 text-xs mb-4">Revenue at risk vs. recovered (integer paise)</p>
          <RecoveryPerformanceChart
            metrics={metrics.data}
            isLoading={metrics.isLoading}
            isError={metrics.isError}
          />
        </div>
        <div className="rounded-xl border border-gray-800 bg-gray-900/60 p-5">
          <h2 className="text-gray-200 font-semibold text-sm mb-1">Action Distribution</h2>
          <p className="text-gray-600 text-xs mb-4">Final actions taken across all interventions</p>
          <ActionDistributionChart
            data={actionDist.data}
            isLoading={actionDist.isLoading}
            isError={actionDist.isError}
          />
        </div>
      </div>

      {/* ── Recovery Events Table ────────────────────────────────────────── */}
      <div className="rounded-xl border border-gray-800 bg-gray-900/60 p-5">
        <div className="flex items-center justify-between mb-4 flex-wrap gap-3">
          <div>
            <h2 className="text-gray-200 font-semibold text-sm">Recovery Events</h2>
            <p className="text-gray-600 text-xs mt-0.5">
              Click any row to view the full AI → Policy Brakes → Executor trace
            </p>
          </div>
          {interventions.data && (
            <span className="text-gray-600 text-xs">
              {interventions.data.total} total
            </span>
          )}
        </div>

        <div className="mb-4">
          <InterventionsFilters
            finalAction={filters.final_action}
            executionStatus={filters.execution_status}
            search={filters.search}
            isRefreshing={interventions.isFetching}
            onFinalActionChange={(v) => updateFilter('final_action', v)}
            onExecutionStatusChange={(v) => updateFilter('execution_status', v)}
            onSearchChange={(v) => updateFilter('search', v)}
            onRefresh={handleRefresh}
          />
        </div>

        <InterventionsTable
          items={interventions.data?.items ?? []}
          total={interventions.data?.total ?? 0}
          isLoading={interventions.isLoading}
          isError={interventions.isError}
          isFetching={interventions.isFetching}
          onRowClick={setSelectedTxnId}
          onRetry={() => queryClient.invalidateQueries({ queryKey: ['interventions'] })}
        />

        {interventions.data && (
          <TablePagination
            total={interventions.data.total}
            page={filters.page}
            pageSize={filters.page_size}
            onPageChange={(p) => setFilters((prev) => ({ ...prev, page: p }))}
          />
        )}
      </div>

      {/* ── Decision Trace Modal ─────────────────────────────────────────── */}
      <DecisionTraceModal
        txnId={selectedTxnId}
        detail={detail.data}
        isLoading={detail.isLoading}
        isError={detail.isError}
        onClose={() => setSelectedTxnId(null)}
      />
    </Layout>
  );
};

export default Dashboard;
