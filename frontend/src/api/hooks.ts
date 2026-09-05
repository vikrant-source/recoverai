import { useQuery } from '@tanstack/react-query';
import client from './client';
import type {
  MetricsResponse,
  ActionDistribution,
  InterventionsResponse,
  InterventionDetail,
  InterventionFilters,
  HealthResponse,
} from './types';

// ─── Health ──────────────────────────────────────────────────────────────────

export function useHealth() {
  return useQuery<HealthResponse>({
    queryKey: ['health'],
    queryFn: async () => {
      const res = await client.get<HealthResponse>('/health');
      return res.data;
    },
    refetchInterval: 15000, // poll every 15s to keep health indicator live
    retry: 1,
  });
}

// ─── Metrics ─────────────────────────────────────────────────────────────────

export function useMetrics() {
  return useQuery<MetricsResponse>({
    queryKey: ['metrics'],
    queryFn: async () => {
      const res = await client.get<MetricsResponse>('/api/metrics');
      return res.data;
    },
    staleTime: 30_000,
  });
}

// ─── Action Distribution ─────────────────────────────────────────────────────

export function useActionDistribution() {
  return useQuery<ActionDistribution>({
    queryKey: ['action-distribution'],
    queryFn: async () => {
      const res = await client.get<ActionDistribution>('/api/action-distribution');
      return res.data;
    },
    staleTime: 30_000,
  });
}

// ─── Interventions List ───────────────────────────────────────────────────────

export function useInterventions(filters: InterventionFilters) {
  const params: Record<string, string | number> = {
    page: filters.page,
    page_size: filters.page_size,
  };
  if (filters.final_action) params.final_action = filters.final_action;
  if (filters.execution_status) params.execution_status = filters.execution_status;
  if (filters.search) params.search = filters.search;

  return useQuery<InterventionsResponse>({
    queryKey: ['interventions', filters],
    queryFn: async () => {
      const res = await client.get<InterventionsResponse>('/api/interventions', { params });
      return res.data;
    },
    staleTime: 15_000,
    placeholderData: (prev) => prev, // keep previous data while new page loads
  });
}

// ─── Intervention Detail ──────────────────────────────────────────────────────

export function useInterventionDetail(txnId: string | null) {
  return useQuery<InterventionDetail>({
    queryKey: ['intervention-detail', txnId],
    queryFn: async () => {
      const res = await client.get<InterventionDetail>(`/api/interventions/${txnId}`);
      return res.data;
    },
    enabled: txnId !== null,
    staleTime: 60_000,
  });
}
