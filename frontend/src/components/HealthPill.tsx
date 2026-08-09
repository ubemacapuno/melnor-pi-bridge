import { type Health } from "../api";

// status dot and text in the header
// data from /api/health (not a bluetooth endpoint)
// green = API up and we can see the scheduler;
// red = couldn't reach the API
export default function HealthPill({ health }: { health: Health | null }) {
  const ok = health && health.status === "ok";
  const scheduler = health && health.scheduler;
  const jobs = scheduler ? scheduler.jobs : 0;
  const running = scheduler ? scheduler.running : false;

  return (
    <div className="flex items-center gap-2 text-xs">
      <span
        className={
          "h-2.5 w-2.5 rounded-full " + (ok ? "bg-emerald-500" : "bg-red-500")
        }
      />
      <span className="text-slate-400">
        {ok
          ? `scheduler ${running ? "on" : "off"} · ${jobs} job${jobs === 1 ? "" : "s"}`
          : "API unreachable"}
      </span>
    </div>
  );
}
