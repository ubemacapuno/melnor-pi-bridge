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
import StatusCard from "./components/StatusCard";
import ManualWatering from "./components/ManualWatering";
import ScheduleList from "./components/ScheduleList";
import AddScheduleForm from "./components/AddScheduleForm";

type Notice = { type: "error" | "info"; text: string };

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [schedules, setSchedules] = useState<Schedule[]>([]);
  const [deviceState, setDeviceState] = useState<DeviceState | null>(null);
  const [statusUpdatedAt, setStatusUpdatedAt] = useState<Date | null>(null);
  const [bleBusy, setBleBusy] = useState(false);
  const [notice, setNotice] = useState<Notice | null>(null);

  useEffect(() => {
    loadHealth();
    loadSchedules();
  }, []);

  function loadHealth() {
    api
      .getHealth()
      .then(setHealth)
      .catch(() => setHealth(null));
  }

  async function loadSchedules() {
    try {
      setSchedules(await api.getSchedules());
    } catch (err) {
      setNotice({
        type: "error",
        text: `Couldn't load schedules: ${errorMessage(err)}`,
      });
    }
  }

  // wrapper for slow Bluetooth actions
  async function runBle<T>(
    action: () => Promise<T>,
    onSuccess?: (result: T) => void,
  ) {
    setBleBusy(true);
    setNotice(null);
    try {
      const result = await action();
      if (onSuccess) onSuccess(result);
    } catch (err) {
      setNotice({ type: "error", text: errorMessage(err) });
    } finally {
      setBleBusy(false);
    }
  }

  function refreshStatus() {
    runBle(api.getState, (state) => {
      setDeviceState(state);
      setStatusUpdatedAt(new Date());
    });
  }

  function startZone(zone: number, minutes: number) {
    runBle(
      () => api.waterZone(zone, minutes),
      () =>
        setNotice({
          type: "info",
          text: `Zone ${zone} watering for ${minutes} min. Press Refresh to confirm.`,
        }),
    );
  }

  function stopZone(zone: number) {
    runBle(
      () => api.offZone(zone),
      () => setNotice({ type: "info", text: `Zone ${zone} turned off.` }),
    );
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
      setNotice({ type: "error", text: `Delete failed: ${errorMessage(err)}` });
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
              "rounded-lg px-3 py-2 text-sm " +
              (notice.type === "error"
                ? "bg-red-950 text-red-200 border border-red-900"
                : "bg-sky-950 text-sky-200 border border-sky-900")
            }
          >
            {notice.text}
          </div>
        )}

        <StatusCard
          state={deviceState}
          updatedAt={statusUpdatedAt}
          busy={bleBusy}
          onRefresh={refreshStatus}
        />

        <ManualWatering busy={bleBusy} onStart={startZone} onStop={stopZone} />

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
