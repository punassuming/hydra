import { useEffect, useRef } from "react";

interface Props {
  onIntersect: () => void;
  enabled?: boolean;
  loading?: boolean;
}

/** Invisible marker that triggers `onIntersect` once whenever it scrolls into view. */
export function InfiniteScrollSentinel({ onIntersect, enabled = true, loading }: Props) {
  const ref = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const node = ref.current;
    if (!node || !enabled) {
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting) {
          onIntersect();
        }
      },
      { rootMargin: "200px" },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [enabled, onIntersect]);

  return (
    <div ref={ref} style={{ height: 1, textAlign: "center", padding: loading ? 12 : 0 }}>
      {loading ? <span style={{ fontSize: 12, opacity: 0.6 }}>Loading more…</span> : null}
    </div>
  );
}
