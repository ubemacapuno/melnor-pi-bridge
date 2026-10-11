import { useState } from "react";

// These are SLOW (~15s) Bluetooth calls, so every button is disabled while isBusy is true

const DURATIONS = [5, 10, 15, 30, 60]; // minutes

type ZoneRowProps = {
  zone: number;
  isBusy: boolean;
  onStart: (zone: number, minutes: number) => void;
  onStop: (zone: number) => void;
};

function ZoneRow({ zone, isBusy, onStart, onStop }: ZoneRowProps) {
  const [minutes, setMinutes] = useState(5);

  return (
    <div className="flex items-center gap-2">
      <span className="w-16 text-sm text-slate-300">Zone {zone}</span>
      <select
        value={minutes}
        onChange={(e) => setMinutes(Number(e.target.value))}
        disabled={isBusy}
        className="rounded-lg border border-slate-700 bg-slate-950 px-2 py-1.5 text-sm disabled:opacity-40"
      >
        {DURATIONS.map((m) => (
          <option key={m} value={m}>
            {m} min
          </option>
        ))}
      </select>
      <button
        onClick={() => onStart(zone, minutes)}
        disabled={isBusy}
        className="cursor-pointer rounded-lg bg-emerald-600 px-3 py-1.5 text-sm font-medium hover:bg-emerald-500 disabled:opacity-40"
      >
        Start
      </button>
      <button
        onClick={() => onStop(zone)}
        disabled={isBusy}
        className="cursor-pointer rounded-lg bg-slate-700 px-3 py-1.5 text-sm font-medium hover:bg-slate-600 disabled:opacity-40"
      >
        Stop
      </button>
    </div>
  );
}

type ManualWateringProps = {
  isBusy: boolean;
  onStart: (zone: number, minutes: number) => void;
  onStop: (zone: number) => void;
};

export default function ManualWatering({
  isBusy,
  onStart,
  onStop,
}: ManualWateringProps) {
  return (
    <section className="rounded-xl border border-slate-800 bg-slate-900 p-4 space-y-3">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-400">
        Manual watering
      </h2>
      <ZoneRow zone={1} isBusy={isBusy} onStart={onStart} onStop={onStop} />
      <ZoneRow zone={2} isBusy={isBusy} onStart={onStart} onStop={onStop} />
    </section>
  );
}
