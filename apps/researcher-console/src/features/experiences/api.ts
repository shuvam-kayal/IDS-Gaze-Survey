export type ResearcherRole = "admin" | "researcher" | "analyst" | "viewer";
export type ExperienceStatus = "draft" | "published" | "archived";
export interface ResearcherSession {
  user_id: string;
  username: string;
  display_name: string;
  role: ResearcherRole;
  permissions: string[];
  csrf_token: string;
  expires_in_seconds: number;
}
export interface ExperienceRecord {
  experience_id: string;
  name: string;
  allowed_origins: string[];
  status: ExperienceStatus;
  created_by: string;
  updated_by: string;
  created_at: string;
  updated_at: string;
  published_at: string | null;
  archived_at: string | null;
}
export interface StudyRecord {
  study_id: string; experience_id: string; name: string; status: "draft" | "published" | "archived";
  priority: number; eligibility_rules: Record<string, unknown>; config_version: string | null;
  config: Record<string, unknown>; created_at: string; updated_at: string;
  published_at: string | null; archived_at: string | null;
}
export interface StudyInput {
  experience_id: string; name: string; priority: number; eligibility_rules: Record<string, unknown>;
  timing_rules: Record<string, unknown>; survey_policy: { timing: string; consolidation: string };
  aois: Array<Record<string, unknown>>; questions: Array<Record<string, unknown>>;
}

export class ResearcherApi {
  private csrfToken: string | null = null;
  constructor(private readonly baseUrl = "http://localhost:8000", private readonly fetchImpl: typeof fetch = fetch) {}

  private async request<T>(path: string, init: RequestInit = {}, csrf = false): Promise<T> {
    const headers = new Headers(init.headers);
    headers.set("Accept", "application/json");
    if (init.body) headers.set("Content-Type", "application/json");
    if (csrf && this.csrfToken) headers.set("X-CSRF-Token", this.csrfToken);
    const response = await this.fetchImpl(`${this.baseUrl}/v1/control${path}`, {
      ...init, headers, credentials: "include", mode: "cors",
    });
    if (!response.ok) {
      const problem = await response.json().catch(() => ({}));
      throw new Error(problem.detail || `Request failed (${response.status})`);
    }
    if (response.status === 204) return undefined as T;
    return response.json() as Promise<T>;
  }

  async session(): Promise<ResearcherSession> {
    const session = await this.request<ResearcherSession>("/auth/session");
    this.csrfToken = session.csrf_token;
    return session;
  }

  async signIn(username: string, password: string): Promise<ResearcherSession> {
    const session = await this.request<ResearcherSession>("/auth/session", {
      method: "POST", body: JSON.stringify({ username, password }),
    });
    this.csrfToken = session.csrf_token;
    return session;
  }

  async signOut(): Promise<void> {
    await this.request<void>("/auth/session", { method: "DELETE" }, true);
    this.csrfToken = null;
  }

  async experiences(): Promise<ExperienceRecord[]> {
    const result = await this.request<{ experiences: ExperienceRecord[] }>("/experiences");
    return result.experiences;
  }

  createExperience(input: { name: string; allowed_origins: string[] }): Promise<ExperienceRecord> {
    return this.request<ExperienceRecord>("/experiences", { method: "POST", body: JSON.stringify(input) }, true);
  }

  updateExperience(id: string, input: { name: string; allowed_origins: string[] }): Promise<ExperienceRecord> {
    return this.request<ExperienceRecord>(`/experiences/${encodeURIComponent(id)}`, { method: "PUT", body: JSON.stringify(input) }, true);
  }

  publishExperience(id: string): Promise<ExperienceRecord> {
    return this.request<ExperienceRecord>(`/experiences/${encodeURIComponent(id)}/publish`, { method: "POST", body: "{}" }, true);
  }

  archiveExperience(id: string): Promise<ExperienceRecord> {
    return this.request<ExperienceRecord>(`/experiences/${encodeURIComponent(id)}/archive`, { method: "POST", body: "{}" }, true);
  }

  async studies(experienceId: string): Promise<StudyRecord[]> {
    const result = await this.request<{ studies: StudyRecord[] }>(`/experiences/${encodeURIComponent(experienceId)}/studies`);
    return result.studies;
  }
  createStudy(experienceId: string, input: StudyInput): Promise<StudyRecord> {
    return this.request<StudyRecord>(`/experiences/${encodeURIComponent(experienceId)}/studies`, { method: "POST", body: JSON.stringify(input) }, true);
  }
  updateStudy(id: string, input: StudyInput): Promise<StudyRecord> {
    return this.request<StudyRecord>(`/studies/${encodeURIComponent(id)}`, { method: "PUT", body: JSON.stringify(input) }, true);
  }
  publishStudy(id: string): Promise<StudyRecord> {
    return this.request<StudyRecord>(`/studies/${encodeURIComponent(id)}/publish`, { method: "POST", body: "{}" }, true);
  }
  archiveStudy(id: string): Promise<StudyRecord> {
    return this.request<StudyRecord>(`/studies/${encodeURIComponent(id)}/archive`, { method: "POST", body: "{}" }, true);
  }
}
