import { useEffect, useState } from "react";
import { type DeviceState, type ZoneState } from "../api";

// Device status: battery + per-zone watering state. Reading this is a SLOW
// (~15s) Bluetooth call, so it only happens when the user presses Refresh.
// The server caches the last read (GET /api/state/cached), so on page open
// the card shows the previous data, and the countdown keeps ticking from the
// zone's `ends_at` rather than the stale `remaining_minutes`.

// re-render once a second so the countdown ticks
function useNow(isActive: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!isActive) return;
    setNow(Date.now());
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [isActive]);
  return now;
}

// seconds left for a watering zone, or null if we can't tell.
// prefers `ends_at` (absolute) so it survives reloads; falls back to
// `remaining_minutes` minus the time elapsed since the read.
function secondsLeft(
  zone: ZoneState | undefined,
  readAt: Date | null,
  now: number,
): number | null {
  if (!zone?.is_watering) return null;
  if (zone.ends_at) {
    const end = new Date(zone.ends_at).getTime();
    if (!Number.isNaN(end)) return Math.max(0, Math.round((end - now) / 1000));
  }
  if (typeof zone.remaining_minutes === "number" && readAt) {
    const elapsed = (now - readAt.getTime()) / 1000;
    return Math.max(0, Math.round(zone.remaining_minutes * 60 - elapsed));
  }
  return null;
}

function formatCountdown(totalSeconds: number): string {
  const h = Math.floor(totalSeconds / 3600);
  const m = Math.floor((totalSeconds % 3600) / 60);
  const s = totalSeconds % 60;
  const mm = String(m).padStart(2, "0");
  const ss = String(s).padStart(2, "0");
  return h > 0 ? `${h}:${mm}:${ss}` : `${m}:${ss}`;
}

// One zone's live status box. `zone` is the per-zone object from /api/state.
function ZoneStatus({
  n,
  zone,
  readAt,
  now,
}: {
  n: number;
  zone: ZoneState | undefined;
  readAt: Date | null;
  now: number;
}) {
  const schedule = zone?.schedule;
  const left = secondsLeft(zone, readAt, now);
  // cached as watering but the countdown has run out: the cycle has most
  // likely finished since the last read, so don't keep showing "Watering"
  const isFinished = zone?.is_watering && left === 0;
  const isWatering = zone?.is_watering && !isFinished;

  return (
    <div className="rounded-lg border border-slate-800 bg-slate-950 p-3">
      <div className="text-xs font-medium text-slate-400">Zone {n}</div>
      {isWatering ? (
        <div className="flex flex-col gap-1 mt-1 text-emerald-400">
          <div>
            💧 Watering
            {zone?.watering_source ? ` (${zone.watering_source})` : ""}
          </div>
          {left !== null && (
            <div className="font-mono text-lg tabular-nums">
              {formatCountdown(left)}
              <span className="ml-1 text-xs font-sans text-emerald-600">
                left
              </span>
            </div>
          )}
          {zone?.ends_at && (
            <div className="text-xs text-slate-500">
              Ends at {new Date(zone.ends_at).toLocaleTimeString()}
            </div>
          )}
        </div>
      ) : isFinished ? (
        <div className="mt-1 text-slate-300">
          Idle
          <div className="text-xs text-slate-500">
            cycle ended · refresh to confirm
          </div>
        </div>
      ) : (
        <div className="mt-1 text-slate-300">Idle</div>
      )}
      {/* This is the timer's OWN on-device schedule (separate from the Pi-side
          schedules below). Shown only if the device has one enabled. */}
      {schedule?.is_enabled && schedule.next_run && (
        <div className="mt-1 text-xs text-slate-500">
          on-device schedule: next {schedule.next_run}
        </div>
      )}
    </div>
  );
}

// "updated 3:04:11 PM" for a recent read; adds the date if it was another day,
// so a stale cached entry from yesterday is obvious
function formatUpdatedAt(updatedAt: Date, now: number): string {
  const isSameDay = new Date(now).toDateString() === updatedAt.toDateString();
  return isSameDay
    ? updatedAt.toLocaleTimeString()
    : `${updatedAt.toLocaleDateString()} ${updatedAt.toLocaleTimeString()}`;
}

// where the displayed state came from: the server's last-known snapshot
// (shown on page open) or a real timer read made during this session
export type StatusSource = "cached" | "live";

function SourceTag({ source }: { source: StatusSource }) {
  const isLive = source === "live";
  return (
    <span
      title={
        isLive
          ? "Read from the timer during this session"
          : "Last known state saved on the Pi; press Refresh to read the timer"
      }
      className={
        "rounded px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide " +
        (isLive
          ? "bg-emerald-950 text-emerald-400 border border-emerald-900"
          : "bg-amber-950 text-amber-400 border border-amber-900")
      }
    >
      {isLive ? "live" : "cached"}
    </span>
  );
}

export default function StatusCard({
  state,
  updatedAt,
  source,
  isBusy,
  onRefresh,
}: {
  state: DeviceState | null;
  updatedAt: Date | null;
  source: StatusSource | null;
  isBusy: boolean;
  onRefresh: () => void;
}) {
  const isAnyWatering =
    !!state && Object.values(state.zones).some((z) => z.is_watering);
  const now = useNow(isAnyWatering);

  return (
    <section className="rounded-xl border border-slate-800 bg-slate-900 p-4 space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-400">
          Device status
        </h2>
        <button
          onClick={onRefresh}
          disabled={isBusy}
          className="cursor-pointer rounded-lg bg-slate-700 px-3 py-1.5 text-sm font-medium hover:bg-slate-600 disabled:opacity-40"
        >
          {isBusy ? "Reading…" : "Refresh"}
        </button>
      </div>

      {isBusy && (
        <p className="text-sm text-slate-400">
          Talking to the timer… this can take up to ~75s if it’s asleep.
        </p>
      )}

      {!isBusy && !state && (
        <p className="text-sm text-slate-400">
          Press Refresh to read the timer (takes ~15s).
        </p>
      )}

      {state && (
        // dim the previous data while a fresh read is in flight, so it's
        // obvious the numbers underneath are from the last read until the
        // new one lands
        <div
          className={
            "space-y-3 transition-opacity " +
            (isBusy ? "opacity-40 pointer-events-none" : "")
          }
          aria-busy={isBusy}
        >
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1.5 text-sm text-slate-300">
            <span>
              {state.name} · 🔋 {state.battery}%
              {updatedAt && (
                <span className="text-slate-500">
                  {" "}
                  · updated {formatUpdatedAt(updatedAt, now)}
                </span>
              )}
            </span>
            {source && <SourceTag source={source} />}
          </div>
          <div className="grid grid-cols-2 gap-3">
            <ZoneStatus n={1} zone={state.zones["1"]} readAt={updatedAt} now={now} />
            <ZoneStatus n={2} zone={state.zones["2"]} readAt={updatedAt} now={now} />
          </div>
        </div>
      )}
    </section>
  );
}
