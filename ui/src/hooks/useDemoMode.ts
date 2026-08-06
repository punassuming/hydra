import { useQuery } from "@tanstack/react-query";
import { fetchHealth } from "../api/health";

/** Whether demo/test UI affordances should render — a UI-declutter switch
 * only (HYDRA_DEMO_MODE on the scheduler), not an authorization boundary.
 * See scheduler/api/health.py::demo_mode_enabled for the full rationale. */
export function useDemoMode(): boolean {
  const { data } = useQuery({
    queryKey: ["health-demo-mode"],
    queryFn: fetchHealth,
    staleTime: 60_000,
    retry: false,
  });
  return Boolean(data?.demo_mode);
}
