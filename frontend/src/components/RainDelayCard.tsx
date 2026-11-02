import { useEffect, useState } from "react";
import type { RainDelay } from "../api";

// Rain delay pauses every scheduled run for 24 hours. It's enforced on the Pi
// (no Bluetooth), so the buttons are instant and stay usable while a slow
// timer read is in flight. Manual watering is NOT blocked.

const MINUTE_MS = 60_000;

function formatTimeLeft(ms: number): string {
  const totalMinutes = Math.max(1, Math.ceil(ms / MINUTE_MS));
  const h = Math.floor(totalMinutes / 60);
  const m = totalMinutes % 60;
  return h > 0 ? `${h}h ${m}m left` : `${m}m left`;
}

type RainDelayCardProps = {
  rainDelay: RainDelay | null;
  isSaving: boolean;
  onStart: () => void;
  onCancel: () => void;
  onExpire: () => void; // re-fetch once the delay runs out
};

export default function RainDelayCard({
  rainDelay,
  isSaving,
  onStart,
  onCancel,
  onExpire,
}: RainDelayCardProps) {
  const until =
    rainDelay?.is_active && rainDelay.until ? new Date(rainDelay.until) : null;
  const [now, setNow] = useState(() => Date.now());

  // tick once a minute while active, and re-fetch right when it expires so
  // the card flips back to "off" without a page reload
  useEffect(() => {
    if (!until) return;
    setNow(Date.now());
    const tick = setInterval(() => setNow(Date.now()), MINUTE_MS);
    const msLeft = until.getTime() - Date.now();
    const expire = setTimeout(onExpire, Math.max(0, msLeft) + 1000);
    return () => {
      clearInterval(tick);
      clearTimeout(expire);
    };
  }, [rainDelay?.until]); // eslint-disable-line react-hooks/exhaustive-deps

  const isActive = until !== null && until.getTime() > now;

  return (
    <section
      className={
        "rounded-xl border p-4 space-y-3 " +
        (isActive
          ? "border-sky-800 bg-sky-950/60"
          : "border-slate-800 bg-slate-900")
      }
    >
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-400">
          Rain delay
        </h2>
        {isActive ? (
          <button
            onClick={onCancel}
            disabled={isSaving}
            className="cursor-pointer rounded-lg bg-slate-700 px-3 py-1.5 text-sm font-medium hover:bg-slate-600 disabled:opacity-40"
          >
            Cancel
          </button>
        ) : (
          <button
            onClick={onStart}
            disabled={isSaving || rainDelay === null}
            className="cursor-pointer rounded-lg bg-sky-600 px-3 py-1.5 text-sm font-medium hover:bg-sky-500 disabled:opacity-40"
          >
            Delay 24 hours
          </button>
        )}
      </div>
      {isActive && until ? (
        <p className="text-sm text-sky-200">
          Scheduled runs paused until{" "}
          <span className="font-medium">
            {until.toLocaleString([], {
              weekday: "short",
              hour: "numeric",
              minute: "2-digit",
            })}
          </span>{" "}
          <span className="text-sky-300/70">
            ({formatTimeLeft(until.getTime() - now)})
          </span>
        </p>
      ) : (
        <p className="text-sm text-slate-400">
          Off. Schedules run normally. Manual watering always works.
        </p>
      )}
    </section>
  );
}
