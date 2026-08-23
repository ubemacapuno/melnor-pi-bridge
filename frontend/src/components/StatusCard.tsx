import { type DeviceState, type ZoneState } from "../api";

// Device status: battery + per-zone watering state. Reading this is a SLOW
// (~15s) Bluetooth call, so it only happens when the user presses Refresh.

// One zone's live status box. `zone` is the per-zone object from /api/state.
function ZoneStatus({ n, zone }: { n: number; zone: ZoneState | undefined }) {
  const watering = zone?.watering;
  const schedule = zone?.schedule;

  return (
    <div className="rounded-lg border border-slate-800 bg-slate-950 p-3">
      <div className="text-xs font-medium text-slate-400">Zone {n}</div>
      {watering ? (
        <div className="flex flex-col gap-1 mt-1 text-emerald-400">
          💧 Watering
          {zone?.watering_source ? ` (${zone.watering_source})` : ""}
          {typeof zone?.remaining_minutes === "number"
            ? ` · ${zone.remaining_minutes}m left`
            : ""}
          {zone?.ends_at && (
            <div className="text-xs text-slate-500">
              Ends at {new Date(zone.ends_at).toLocaleTimeString()}
            </div>
          )}
        </div>
      ) : (
        <div className="mt-1 text-slate-300">Idle</div>
      )}
      {/* This is the timer's OWN on-device schedule (separate from the Pi-side
          schedules below). Shown only if the device has one enabled. */}
      {schedule?.enabled && schedule.next_run && (
        <div className="mt-1 text-xs text-slate-500">
          on-device schedule: next {schedule.next_run}
        </div>
      )}
    </div>
  );
}

export default function StatusCard({
  state,
  updatedAt,
  busy,
  onRefresh,
}: {
  state: DeviceState | null;
  updatedAt: Date | null;
  busy: boolean;
  onRefresh: () => void;
}) {
  return (
    <section className="rounded-xl border border-slate-800 bg-slate-900 p-4 space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-400">
          Device status
        </h2>
        <button
          onClick={onRefresh}
          disabled={busy}
          className="cursor-pointer rounded-lg bg-slate-700 px-3 py-1.5 text-sm font-medium hover:bg-slate-600 disabled:opacity-40"
        >
          {busy ? "Reading…" : "Refresh"}
        </button>
      </div>

      {busy && (
        <p className="text-sm text-slate-400">
          Talking to the timer… this can take up to ~75s if it’s asleep.
        </p>
      )}

      {!busy && !state && (
        <p className="text-sm text-slate-400">
          Press Refresh to read the timer (takes ~15s).
        </p>
      )}

      {state && (
        <>
          <div className="text-sm text-slate-300">
            {state.name} · 🔋 {state.battery}%
            {updatedAt && (
              <span className="text-slate-500">
                {" "}
                · updated {updatedAt.toLocaleTimeString()}
              </span>
            )}
          </div>
          <div className="grid grid-cols-2 gap-3">
            <ZoneStatus n={1} zone={state.zones["1"]} />
            <ZoneStatus n={2} zone={state.zones["2"]} />
          </div>
        </>
      )}
    </section>
  );
}
