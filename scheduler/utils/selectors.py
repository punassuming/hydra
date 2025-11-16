from typing import Dict, List, Optional


def select_best_worker(candidates: List[Dict]) -> Optional[Dict]:
    if not candidates:
        return None
    # Select by lowest load (current_running / max_concurrency) then by absolute current_running
    def load_key(w: Dict):
        max_c = max(int(w.get("max_concurrency", 1)), 1)
        cur = int(w.get("current_running", 0))
        return (cur / max_c, cur)

    return sorted(candidates, key=load_key)[0]

