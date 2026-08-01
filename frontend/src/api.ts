export interface Health {
  status: string;
  scheduler: { running: boolean; jobs: number };
}

export interface Schedule {
  id: string;
  zone: number;
  days: string[];
  time: string;
  minutes: number;
  enabled: boolean;
}

export type ScheduleInput = Omit<Schedule, "id" | "enabled"> & {
  enabled?: boolean;
};

export interface ZoneState {
  watering: boolean;
  watering_source?: string;
  remaining_minutes?: number;
  schedule: { enabled: boolean; next_run?: string };
}

export interface DeviceState {
  name: string;
  battery: number;
  zones: Record<string, ZoneState>;
}

export interface ApiError extends Error {
  status: number;
}

export function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(path, options);

  let body: any = null;
  try {
    body = await res.json(); // every endpoint returns json
  } catch {
    // leave body as null
  }

  if (!res.ok) {
    const detail = body && body.detail;
    const message =
      typeof detail === "string"
        ? detail // detail is a plain string (our own 409/422/503)
        : Array.isArray(detail)
          ? detail.map((d) => d?.msg ?? String(d)).join("; ") // Pydantic errors: pull out the human-readable msg
          : res.statusText || "Request failed"; // no detail, generic fallback
    const err = new Error(message) as ApiError;
    err.status = res.status;
    throw err;
  }

  return body as T;
}

// endpoints that don't use bluetooth
export const getHealth = () => request<Health>("/api/health");

export const getSchedules = () => request<Schedule[]>("/api/schedules");

export const addSchedule = (body: ScheduleInput) =>
  request<Schedule>("/api/schedules", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

export const deleteSchedule = (id: string) =>
  request<void>(`/api/schedules/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });

// slow bluetooth endpoints
export const getState = () => request<DeviceState>("/api/state");

export const waterZone = (zone: number, minutes: number) =>
  request<unknown>(`/api/zones/${zone}/on?minutes=${minutes}`, {
    method: "POST",
  });

export const offZone = (zone: number) =>
  request<unknown>(`/api/zones/${zone}/off`, { method: "POST" });
