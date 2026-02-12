/**
 * Dev Tools API client
 */

import { SessionStateResponse, AgentLogsResponse } from '../types';

const API_BASE_URL =
  import.meta.env.VITE_API_URL ||
  import.meta.env.VITE_API_BASE_URL ||
  'http://localhost:8000';

async function apiFetch<T>(endpoint: string): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${endpoint}`);

  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({ detail: 'Unknown error' }));
    throw new Error(error.detail || `HTTP ${response.status}`);
  }

  return response.json();
}

export async function getSessionState(
  sessionId: string
): Promise<SessionStateResponse> {
  return apiFetch<SessionStateResponse>(`/sessions/${sessionId}`);
}

export async function getAgentLogs(
  sessionId: string,
  filters?: { turn_id?: string; agent_name?: string; limit?: number }
): Promise<AgentLogsResponse> {
  const params = new URLSearchParams();
  if (filters?.turn_id) params.append('turn_id', filters.turn_id);
  if (filters?.agent_name) params.append('agent_name', filters.agent_name);
  if (filters?.limit) params.append('limit', filters.limit.toString());

  const query = params.toString();
  return apiFetch<AgentLogsResponse>(
    `/sessions/${sessionId}/agent-logs${query ? `?${query}` : ''}`
  );
}
