// TypeScript types mirroring the backend response schemas.
// All monetary values are integer paise. The frontend converts for display.

export interface MetricsResponse {
  revenue_at_risk_paise: number;
  revenue_recovered_paise: number;
  recovery_rate_bps: number; // e.g. 5198 = 51.98%
  total_interventions: number;
  escalated_count: number;
  successful_txns: number;
  failed_txns: number;
}

export interface ActionDistributionItem {
  action: string;
  count: number;
}

export type ActionDistribution = ActionDistributionItem[];

export interface InterventionRow {
  intervention_id: number;
  txn_id: string;
  amount_paise: number;
  currency: string;
  failure_code: string | null;
  failure_description: string | null;
  ai_recommendation: string;
  ai_confidence: number;
  ai_failure_classification: string | null;
  ai_reasoning: string | null;
  policy_decision: string;
  policy_reason: string;
  final_action: string;
  execution_status: string;
  recovered_amount_paise: number;
  created_at: string | null;
}

export interface InterventionsResponse {
  total: number;
  page: number;
  page_size: number;
  items: InterventionRow[];
}

export interface InterventionDetail {
  // Transaction context
  txn_id: string;
  amount_paise: number;
  currency: string;
  status: string;
  failure_code: string | null;
  failure_description: string | null;
  attempt_count: number;
  revenue_at_risk_paise: number;
  recovered_amount_paise: number;
  // Customer context
  customer_id: string;
  ltv_tier: string;
  fraud_score: number;
  // Full intervention trace
  intervention: {
    id: number;
    ai_recommendation: string;
    ai_confidence: number;
    ai_failure_classification: string | null;
    ai_reasoning: string | null;
    policy_decision: string;
    policy_reason: string;
    final_action: string;
    execution_status: string;
    recovered_amount_paise: number;
    created_at: string | null;
  };
}

export interface HealthResponse {
  status: 'ok' | string;
}

// Filter state for the interventions table
export interface InterventionFilters {
  final_action: string; // '' means ALL
  execution_status: string; // '' means ALL
  search: string;
  page: number;
  page_size: number;
}
