import { SchedulerEvent } from "../types";

interface Props {
  events: SchedulerEvent[];
}

export function EventsFeed({ events }: Props) {
  return (
    <div className="panel">
      <h2>Scheduler Events</h2>
      <div className="events-feed">
        {events.map((evt) => (
          <div key={`${evt.ts}-${evt.type}`}>
            <strong>{evt.type}</strong> · {new Date(evt.ts * 1000).toLocaleTimeString()} ·{" "}
            <code>{JSON.stringify(evt.payload)}</code>
          </div>
        ))}
        {events.length === 0 && <p>No recent events.</p>}
      </div>
    </div>
  );
}
