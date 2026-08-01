import { useState, type FormEvent } from "react";
import { errorMessage, type Schedule, type ScheduleInput } from "../api";

const MAX_MINUTES = 240; // matches the backend _MAX_SCHEDULE_MINUTES in main.py

const DAYS: [string, string][] = [
  ["sun", "Su"],
  ["mon", "Mo"],
  ["tue", "Tu"],
  ["wed", "We"],
  ["thu", "Th"],
  ["fri", "Fr"],
  ["sat", "Sa"],
];
const DAY_ORDER = DAYS.map(([value]) => value);

export default function AddScheduleForm({
  onAdd,
}: {
  onAdd: (body: ScheduleInput) => Promise<Schedule>;
}) {
  const [zone, setZone] = useState(1);
  const [days, setDays] = useState<string[]>([]); // e.g. ["mon", "wed"]
  const [time, setTime] = useState("21:00");
  const [minutes, setMinutes] = useState(20);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  function toggleDay(value: string) {
    setDays((prev) =>
      prev.includes(value) ? prev.filter((d) => d !== value) : [...prev, value],
    );
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);

    if (!days.length) {
      setError("Pick at least one day.");
      return;
    }

    if (!time) {
      setError("Pick a start time.");
      return;
    }

    if (!Number.isInteger(minutes) || minutes < 1 || minutes > MAX_MINUTES) {
      setError(`Minutes must be a whole number from 1 to ${MAX_MINUTES}.`);
      return;
    }

    const orderedDays = DAY_ORDER.filter((d) => days.includes(d));

    setSubmitting(true);
    try {
      await onAdd({ zone, days: orderedDays, time, minutes });
      setDays([]);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="space-y-3 border-t border-slate-800 pt-4"
    >
      <div className="text-sm font-medium text-slate-300">Add a schedule</div>

      {/* Zone */}
      <div className="flex items-center gap-2">
        <label className="w-14 text-sm text-slate-400">Zone</label>
        <select
          value={zone}
          onChange={(e) => setZone(Number(e.target.value))}
          className="rounded-lg border border-slate-700 bg-slate-950 px-2 py-1.5 text-sm"
        >
          <option value={1}>1</option>
          <option value={2}>2</option>
        </select>
      </div>

      {/* Days */}
      <div className="flex items-center gap-2">
        <label className="w-14 text-sm text-slate-400">Days</label>
        <div className="flex flex-wrap gap-1">
          {DAYS.map(([value, label]) => {
            const on = days.includes(value);
            return (
              <button
                type="button"
                key={value}
                onClick={() => toggleDay(value)}
                className={
                  "cursor-pointer h-8 w-9 rounded-md text-xs font-medium " +
                  (on
                    ? "bg-emerald-600 text-white"
                    : "bg-slate-800 text-slate-300 hover:bg-slate-700")
                }
              >
                {label}
              </button>
            );
          })}
        </div>
      </div>

      {/* Time (in minutes) */}
      <div className="flex items-center gap-2">
        <label className="w-14 text-sm text-slate-400">Time</label>
        <input
          type="time"
          value={time}
          onChange={(e) => setTime(e.target.value)}
          className="rounded-lg border border-slate-700 bg-slate-950 px-2 py-1.5 text-sm"
        />
        <input
          type="number"
          min={1}
          max={MAX_MINUTES}
          value={minutes}
          onChange={(e) => setMinutes(Number(e.target.value))}
          className="w-20 rounded-lg border border-slate-700 bg-slate-950 px-2 py-1.5 text-sm"
        />
        <span className="text-sm text-slate-400">min</span>
      </div>

      {error && <p className="text-sm text-red-400">{error}</p>}

      <div className="flex items-center justify-between">
        <p className="text-xs text-slate-500">
          Max {MAX_MINUTES} min · no overlaps, even across zones.
        </p>
        <button
          type="submit"
          disabled={submitting}
          className="cursor-pointer rounded-lg bg-emerald-600 px-4 py-1.5 text-sm font-medium hover:bg-emerald-500 disabled:opacity-40"
        >
          {submitting ? "Adding…" : "Add"}
        </button>
      </div>
    </form>
  );
}
