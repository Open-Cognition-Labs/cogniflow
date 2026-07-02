// Client for the Cogniflow Playground API (cogniflow-api/main.py).
export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
// Optional bearer token for a secured API (server-side COGNIFLOW_API_TOKENS). Unset -> the API
// runs in open/dev mode and no Authorization header is sent, so local dev is unchanged.
const API_TOKEN = process.env.NEXT_PUBLIC_API_TOKEN;
const authHeaders = (base: Record<string, string> = {}): Record<string, string> =>
  API_TOKEN ? { ...base, Authorization: `Bearer ${API_TOKEN}` } : base;

export type ServedFact = {
  belief_id: string;
  statement: string;
  valid_at: string | null;
  invalid_at: string | null;
  valid_at_source: string;
  valid_at_source_raw: string | null;
  provenance: string[];
  superseded_by: string | null;
  score: number | null;
};

export type ContextResponse = {
  query: string;
  as_of: string | null;
  facts: ServedFact[];
  notes: string[];
};

export type AnswerResponse = {
  answer: string;
  as_of: string | null;
  generator_model: string | null;
  confidence: Record<string, number>;
  facts: ServedFact[];
};

export type Health = {
  status: string;
  falkordb: boolean;
  llm: boolean;
  embedder: string;
};

// ---- audit / replay (the bitemporal ledger) --------------------------------
export type ResolvedName = { uuid: string; name: string | null; display: string; resolved: boolean };

export type AuditBelief = {
  belief_id: string;
  statement: string;
  valid_at: string | null;
  invalid_at: string | null;
  expired_at: string | null;
  created_at: string | null;
  valid_at_source: string;
  valid_at_source_raw: string | null;
  superseded_by: string | null;
  provenance: ResolvedName[];
};

export type ProvenanceTraceResponse = {
  belief_id: string;
  asserted_by: ResolvedName[];
  superseded_by_belief: string | null;
  superseded_by_episode: ResolvedName | null;
  invalid_at: string | null;
  expired_at: string | null;
};

export type TimelineResponse = { belief: AuditBelief; trace: ProvenanceTraceResponse };

export type DemoSeed = {
  session_id: string;
  boston_belief_id: string;
  denver_belief_id: string;
  range: { start: string; end: string; superseded_at: string };
  current: AuditBelief[];
};

async function jpost<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(`${API_URL}${path}`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error((await r.text()) || `${r.status}`);
  return r.json();
}

async function jget<T>(path: string): Promise<T> {
  const r = await fetch(`${API_URL}${path}`, { headers: authHeaders() });
  if (!r.ok) throw new Error((await r.text()) || `${r.status}`);
  return r.json();
}

export const api = {
  health: () => jget<Health>("/api/health"),
  plugins: () =>
    jget<{ embedders: string[]; rerankers: string[]; generators: string[]; backends: string[]; defaults: Record<string, string> }>(
      "/api/plugins",
    ),
  newSession: () => jpost<{ session_id: string }>("/api/session", {}).then((r) => r.session_id),
  setConfig: (
    session_id: string,
    cfg: {
      embedder?: string;
      reranker?: string;
      embedder_model?: string;
      embedder_base_url?: string;
      embedder_api_key?: string;
      reranker_model?: string;
      reranker_base_url?: string;
      reranker_api_key?: string;
      generator?: string;
      generator_model?: string;
      generator_base_url?: string;
      generator_api_key?: string;
    },
  ) => jpost<{ ok: boolean }>("/api/config", { session_id, ...cfg }),
  ingestText: (session_id: string, text: string, title: string, reference_time?: string) =>
    jpost<{ document: string; facts_created: number; facts_superseded: number }>("/api/ingest-text", {
      session_id,
      text,
      title,
      reference_time,
    }),
  ingestFile: async (session_id: string, file: File, reference_time?: string) => {
    const fd = new FormData();
    fd.append("session_id", session_id);
    fd.append("file", file);
    if (reference_time) fd.append("reference_time", reference_time);
    const r = await fetch(`${API_URL}/api/ingest`, { method: "POST", headers: authHeaders(), body: fd });
    if (!r.ok) throw new Error((await r.text()) || `${r.status}`);
    return r.json() as Promise<{
      document: string;
      chunks: number;
      facts_created: number;
      facts_superseded: number;
    }>;
  },
  context: (session_id: string, query: string, as_of: string | null, top_k = 6) =>
    jpost<ContextResponse>("/api/context", { session_id, query, as_of, top_k }),
  answer: (session_id: string, query: string, as_of: string | null, top_k = 6) =>
    jpost<AnswerResponse>("/api/answer", { session_id, query, as_of, top_k }),
  reset: (session_id: string) => jpost<{ ok: boolean }>(`/api/reset?session_id=${session_id}`, {}),

  // audit / replay ledger (read-only; the money shot)
  seedDemo: () => jpost<DemoSeed>("/api/demo/seed", {}),
  getCurrent: (session_id: string) =>
    jget<{ beliefs: AuditBelief[] }>(`/api/audit/current?session_id=${session_id}`),
  getEvent: (session_id: string, as_of: string) =>
    jget<{ as_of: string; beliefs: AuditBelief[] }>(
      `/api/audit/event?session_id=${session_id}&as_of=${encodeURIComponent(as_of)}`,
    ),
  getReplay: (session_id: string, system_time: string) =>
    jget<{ system_time: string; beliefs: AuditBelief[] }>(
      `/api/audit/replay?session_id=${session_id}&system_time=${encodeURIComponent(system_time)}`,
    ),
  getProvenance: (session_id: string, belief_id: string) =>
    jget<ProvenanceTraceResponse>(
      `/api/audit/provenance/${encodeURIComponent(belief_id)}?session_id=${session_id}`,
    ),
  getTimeline: (session_id: string, belief_id: string) =>
    jget<TimelineResponse>(
      `/api/audit/timeline/${encodeURIComponent(belief_id)}?session_id=${session_id}`,
    ),
};

export function confidenceBadgeClass(src: string): string {
  if (src === "authoritative") return "bg-win/12 text-win border-win/30";
  if (src === "derived") return "bg-warn/12 text-warn border-warn/30";
  return "bg-muted text-muted-foreground border-border";
}
