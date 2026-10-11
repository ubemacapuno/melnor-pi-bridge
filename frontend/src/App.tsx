import { useEffect, useState } from "react";
import * as api from "./api";
import {
  errorMessage,
  type Health,
  type Schedule,
  type ScheduleInput,
  type DeviceState,
} from "./api";
import HealthPill from "./components/HealthPill";
import StatusCard, { type StatusSource } from "./components/StatusCard";
import ManualWatering from "./components/ManualWatering";
import ScheduleList from "./components/ScheduleList";
import AddScheduleForm from "./components/AddScheduleForm";

type Notice = {
  type: "error" | "info";
  text: string;
  at: Date;
};

// a start needs a moment to populate its countdown register,
// so use set timeout before re-reading it
const delay = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));
const DEVICE_SETTLE_MS = 3000;

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [schedules, setSchedules] = useState<Schedule[]>([]);
  const [deviceState, setDeviceState] = useState<DeviceState | null>(null);
  const [statusUpdatedAt, setStatusUpdatedAt] = useState<Date | null>(null);
  // "cached" = loaded from the server's last-known snapshot on page open;
  // "live" = read from the timer during this session
  const [statusSource, setStatusSource] = useState<StatusSource | null>(null);
  const [isBleBusy, setIsBleBusy] = useState(false);
  const [notice, setNotice] = useState<Notice | null>(null);

  useEffect(() => {
    loadHealth();
    loadSchedules();
    loadCachedState();
  }, []);

  // show a notice with the current time
  function notify(type: Notice["type"], text: string) {
    setNotice({
      type,
      text,
      at: new Date(),
    });
  }

  function loadHealth() {
    api
      .getHealth()
      .then(setHealth)
      .catch(() => setHealth(null));
  }

  // the server remembers the last timer read in data/last_state.json, so
  // every client (phone, laptop, a fresh tab) opens with the latest known
  // status and countdown instead of a blank card; no Bluetooth involved
  async function loadCachedState() {
    try {
      const cached = await api.getCachedState();
      if (cached.state && cached.read_at) {
        setDeviceState(cached.state);
        setStatusUpdatedAt(new Date(cached.read_at));
        setStatusSource("cached");
      }
    } catch (err) {
      console.warn("cached state load failed:", err);
    }
  }

  async function loadSchedules() {
    try {
      setSchedules(await api.getSchedules());
    } catch (err) {
      notify("error", `Couldn't load schedules: ${errorMessage(err)}`);
    }
  }

  // wrapper for slow Bluetooth actions
  async function runBle<T>(
    action: () => Promise<T>,
    onSuccess?: (result: T) => void,
  ) {
    setIsBleBusy(true);
    setNotice(null);
    try {
      const result = await action();
      if (onSuccess) onSuccess(result);
    } catch (err) {
      notify("error", errorMessage(err));
    } finally {
      setIsBleBusy(false);
    }
  }

  // store a fresh device read into the status cards
  function applyState(state: DeviceState) {
    setDeviceState(state);
    setStatusUpdatedAt(new Date());
    setStatusSource("live");
  }

  async function readStatus() {
    try {
      applyState(await api.getState());
    } catch (err) {
      console.warn("post-command status read failed:", err);
    }
  }

  function refreshStatus() {
    runBle(api.getState, applyState);
  }

  function startZone(zone: number, minutes: number) {
    runBle(async () => {
      await api.waterZone(zone, minutes);
      notify("info", `Zone ${zone} watering for ${minutes} min.`);
      await delay(DEVICE_SETTLE_MS); // let the countdown register fill first
      await readStatus();
    });
  }

  function stopZone(zone: number) {
    runBle(async () => {
      await api.offZone(zone);
      notify("info", `Zone ${zone} turned off.`);
      await readStatus();
    });
  }

  // add/deleteSchedule doesn't require bluetooth
  async function addSchedule(body: ScheduleInput): Promise<Schedule> {
    const created = await api.addSchedule(body);
    await loadSchedules();
    loadHealth(); // armed jobs count changed
    return created;
  }

  async function deleteSchedule(id: string) {
    try {
      await api.deleteSchedule(id);
      await loadSchedules();
      loadHealth();
    } catch (err) {
      notify("error", `Delete failed: ${errorMessage(err)}`);
    }
  }

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <div className="mx-auto max-w-xl px-4 py-6 space-y-5">
        <header className="flex items-center justify-between">
          <h1 className="text-xl font-bold">Melnor Timer</h1>
          <HealthPill health={health} />
        </header>

        {/* BLE errors, action confirmations, etc. */}
        {notice && (
          <div
            className={
              "flex items-center justify-between gap-3 rounded-lg px-3 py-2 text-sm " +
              (notice.type === "error"
                ? "bg-red-950 text-red-200 border border-red-900"
                : "bg-sky-950 text-sky-200 border border-sky-900")
            }
          >
            <span>{notice.text}</span>
            <span className="shrink-0 text-xs opacity-70">
              {notice.at.toLocaleTimeString()}
            </span>
          </div>
        )}

        <StatusCard
          state={deviceState}
          updatedAt={statusUpdatedAt}
          source={statusSource}
          isBusy={isBleBusy}
          onRefresh={refreshStatus}
        />

        <ManualWatering isBusy={isBleBusy} onStart={startZone} onStop={stopZone} />

        <section className="rounded-xl border border-slate-800 bg-slate-900 p-4 space-y-4">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-400">
            Schedules
          </h2>
          <ScheduleList schedules={schedules} onDelete={deleteSchedule} />
          <AddScheduleForm onAdd={addSchedule} />
        </section>
      </div>
    </div>
  );
}
