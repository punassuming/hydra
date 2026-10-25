"""Runtime modes (HYDRA_MODE) shared by the full and lite editions."""

MODE_COMBINED = "combined"  # API + orchestration loops in one process (default)
MODE_API = "api"  # API only; orchestration runs in a separate process (full edition only)
VALID_MODES = (MODE_COMBINED, MODE_API)
