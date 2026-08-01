import { type Schedule } from "../api";

const DAY_LABELS: Record<string, string> = {
  sun: "Sun",
  mon: "Mon",
  tue: "Tue",
  wed: "Wed",
  thu: "Thu",
  fri: "Fri",
  sat: "Sat",
};

const WEEK_ORDER = Object.keys(DAY_LABELS);

// order by EARLIEST day (a Mon+Fri schedule sorts as Monday).
const earliestDay = (s: Schedule) =>
  Math.min(...s.days.map((d) => WEEK_ORDER.indexOf(d)));

type ScheduleListProps = {
  schedules: Schedule[];
  onDelete: (id: string) => void;
};

export default function ScheduleList({
  schedules,
  onDelete,
}: ScheduleListProps) {
  if (!schedules.length) {
    return <p className="text-sm text-slate-500">No schedules yet.</p>;
  }

  const ordered = [...schedules].sort(
    (a, b) => earliestDay(a) - earliestDay(b) || a.time.localeCompare(b.time),
  );

  function handleDelete(s: Schedule) {
    const label = `Zone ${s.zone} at ${s.time}`;
    if (window.confirm(`Delete this schedule? (${label})`)) {
      onDelete(s.id);
    }
  }

  return (
    <ul className="space-y-2">
      {ordered.map((s) => (
        <li
          key={s.id}
          className="flex items-center justify-between rounded-lg border border-slate-800 bg-slate-950 px-3 py-2"
        >
          <span className="text-sm">
            <span className="font-medium">Zone {s.zone}</span>
            <span className="text-slate-400">
              {" · "}
              {s.days.map((d) => DAY_LABELS[d] || d).join(" ")}
              {" · "}
              {s.time} · {s.minutes}m
            </span>
            {!s.enabled && (
              <span className="ml-2 text-xs text-amber-400">(paused)</span>
            )}
          </span>
          <button
            onClick={() => handleDelete(s)}
            aria-label="Delete schedule"
            className="cursor-pointer rounded-md px-2 py-1 text-slate-400 hover:bg-slate-800 hover:text-red-400"
          >
            🗑
          </button>
        </li>
      ))}
    </ul>
  );
}
