/**
 * Theme colors for Hydra Scheduler UI
 * Provides consistent colors that work in both light and dark modes
 */

export interface ThemeColors {
  // Primary brand colors
  primary: string;
  primaryHover: string;
  
  // Status colors
  success: string;
  error: string;
  warning: string;
  info: string;
  
  // Text colors
  textPrimary: string;
  textSecondary: string;
  textDisabled: string;
  
  // Background colors
  bgPrimary: string;
  bgSecondary: string;
  bgTertiary: string;
  
  // Border colors
  border: string;
  borderLight: string;
  
  // Special purpose colors
  headerBg: string;
  cardHover: string;
  logBg: string;
  logText: string;
  logErrorBg: string;
}

export const lightThemeColors: ThemeColors = {
  // Primary brand colors
  primary: "#2563eb",
  primaryHover: "#1d4ed8",

  // Status colors — v2 design tokens
  success: "#16a34a",
  error: "#dc2626",
  warning: "#d97706",
  info: "#2563eb",

  // Text colors
  textPrimary: "#0f172a",
  textSecondary: "#64748b",
  textDisabled: "#94a3b8",

  // Background colors
  bgPrimary: "#ffffff",
  bgSecondary: "#f8fafc",
  bgTertiary: "#f1f5f9",

  // Border colors
  border: "rgba(15, 23, 42, 0.08)",
  borderLight: "rgba(15, 23, 42, 0.04)",

  // Special purpose colors
  headerBg: "#ffffff",
  cardHover: "rgba(37, 99, 235, 0.04)",
  logBg: "#0a0e14",
  logText: "#e2e8f0",
  logErrorBg: "#0a0e14",
};

export const darkThemeColors: ThemeColors = {
  // Primary brand colors
  primary: "#38bdf8",
  primaryHover: "#0ea5e9",

  // Status colors — v2 design tokens
  success: "#34d399",
  error: "#f87171",
  warning: "#fbbf24",
  info: "#60a5fa",

  // Text colors
  textPrimary: "#f1f5f9",
  textSecondary: "#94a3b8",
  textDisabled: "#64748b",

  // Background colors
  bgPrimary: "#131c2e",
  bgSecondary: "#0c1220",
  bgTertiary: "#1a253a",

  // Border colors
  border: "rgba(148, 163, 184, 0.10)",
  borderLight: "rgba(148, 163, 184, 0.06)",

  // Special purpose colors
  headerBg: "#0c1220",
  cardHover: "rgba(56, 189, 248, 0.06)",
  logBg: "#0a0e14",
  logText: "#e2e8f0",
  logErrorBg: "#0a0e14",
};
