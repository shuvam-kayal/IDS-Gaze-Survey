/** P4 analytics client for the shared researcher console; uses frozen AnalysisRequest/Result v1. */
export type ModalityPolicy = "best_available" | "gaze_only" | "non_gaze_only";
export type AnalysisType = "descriptive" | "correlation" | "group_comparison" | "classification" | "regression" | "clustering";
export type AnalysisStatus = "queued" | "running" | "succeeded" | "failed" | "insufficient_data";

export interface AnalysisRequestV1 {
  schema_version: "1.0.0";
  analysis_request_id: string;
  study_id: string;
  feature_set_version: string;
  modality_policy: ModalityPolicy;
  analysis_types: AnalysisType[];
  parameters: Record<string, unknown>;
  requested_at?: string | null;
}

export interface AnalysisResultV1 {
  schema_version: "1.0.0";
  analysis_id: string;
  analysis_request_id: string;
  study_id: string;
  feature_set_version: string;
  model_version: string | null;
  modality: "gaze_and_non_gaze" | "non_gaze_only";
  status: AnalysisStatus;
  sample_size: number;
  results: Record<string, unknown>;
  limitations: string[];
  created_at: string | null;
}

export interface AnalysisResultPage {
  results: AnalysisResultV1[];
  next_cursor: string | null;
  limit: number;
}

export interface ModelRegistry {
  registry_version: string;
  models: Record<string, unknown>;
}

export type Fetcher = typeof fetch;

export function createAnalyticsClient(baseUrl = "/v1/analytics", fetcher: Fetcher = fetch) {
  async function request<T>(path: string, init?: RequestInit): Promise<T> {
    const response = await fetcher(`${baseUrl}${path}`, {
      ...init,
      credentials: "same-origin",
      headers: { Accept: "application/json", ...init?.headers },
    });
    if (!response.ok) {
      const body: unknown = await response.json().catch(() => null);
      const detail = typeof body === "object" && body !== null && "detail" in body ? (body as { detail: unknown }).detail : body;
      throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail ?? `Analytics request failed (${response.status})`));
    }
    return response.json() as Promise<T>;
  }

  return {
    analyze(payload: AnalysisRequestV1) {
      return request<AnalysisResultV1>("/analyze", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    },
    listModels() {
      return request<ModelRegistry>("/models");
    },
    startJob(payload: AnalysisRequestV1) {
      return request<AnalysisResultV1>("/jobs", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    },
    getJob(analysisId: string) {
      return request<AnalysisResultV1>(`/jobs/${encodeURIComponent(analysisId)}`);
    },
    async waitForJob(analysisId: string, options: { pollIntervalMs?: number; timeoutMs?: number } = {}) {
      const pollIntervalMs = Math.max(100, options.pollIntervalMs ?? 500);
      const timeoutMs = Math.max(pollIntervalMs, options.timeoutMs ?? 120_000);
      const deadline = Date.now() + timeoutMs;
      let result = await this.getJob(analysisId);
      while (result.status === "queued" || result.status === "running") {
        if (Date.now() >= deadline) throw new Error(`Analytics job ${analysisId} timed out while waiting for a result`);
        await new Promise((resolve) => setTimeout(resolve, pollIntervalMs));
        result = await this.getJob(analysisId);
      }
      return result;
    },
    getResult(analysisId: string) {
      return request<AnalysisResultV1>(`/results/${encodeURIComponent(analysisId)}`);
    },
    listResults(studyId: string, options: { limit?: number; cursor?: string } = {}) {
      const query = new URLSearchParams({ study_id: studyId, limit: String(options.limit ?? 50) });
      if (options.cursor) query.set("cursor", options.cursor);
      return request<AnalysisResultPage>(`/results?${query}`);
    },
    compare(leftId: string, rightId: string) {
      const query = new URLSearchParams({ left_id: leftId, right_id: rightId });
      return request<Record<string, unknown>>(`/compare?${query}`);
    },
    async exportCsv(analysisId: string): Promise<Blob> {
      const response = await fetcher(`${baseUrl}/results/${encodeURIComponent(analysisId)}/csv`, { credentials: "same-origin", headers: { Accept: "text/csv" } });
      if (!response.ok) throw new Error(`CSV export failed (${response.status})`);
      return response.blob();
    },
  };
}
