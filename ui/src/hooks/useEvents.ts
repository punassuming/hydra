import { useEffect, useState } from "react";
import { SchedulerEvent } from "../types";
import { streamUrl } from "../api/client";

export function useSchedulerEvents(limit = 50) {
  const [events, setEvents] = useState<SchedulerEvent[]>([]);

  useEffect(() => {
    const source = new EventSource(streamUrl);
    source.onmessage = (evt) => {
      try {
        const parsed = JSON.parse(evt.data) as SchedulerEvent;
        setEvents((prev) => {
          const next = [parsed, ...prev];
          return next.slice(0, limit);
        });
      } catch (err) {
        console.error("failed to parse event", err);
      }
    };
    source.onerror = () => {
      source.close();
    };
    return () => {
      source.close();
    };
  }, [limit]);

  return events;
}
