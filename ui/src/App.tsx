import { useEffect, useMemo, useState } from "react";
import { Layout, Segmented, Button } from "antd";
import { Routes, Route, useLocation, useNavigate } from "react-router-dom";
import { ConfigProvider, theme } from "antd";
import { HomePage } from "./pages/Home";
import { JobDetailPage } from "./pages/JobDetail";
import { ObservePage } from "./pages/Observe";
import { WorkersPage } from "./pages/Workers";
import { AdminPage } from "./pages/Admin";
import { HydraLogo } from "./components/HydraLogo";
import { HeaderSettings } from "./components/HeaderSettings";
import { AuthPrompt } from "./components/AuthPrompt";
import { AUTH_REQUIRED_EVENT, hasAnyToken } from "./api/client";
import { WorkerDetailPage } from "./pages/WorkerDetail";
import { ActiveDomainProvider, useActiveDomain } from "./context/ActiveDomainContext";
import { ThemeProvider, useTheme } from "./theme";

const THEME_PREF_KEY = "hydra_theme_preference";
type ThemePreference = "system" | "light" | "dark";

function getSystemDarkMode(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return false;
  }
  return window.matchMedia("(prefers-color-scheme: dark)").matches;
}

function getInitialThemePreference(): ThemePreference {
  try {
    const pref = localStorage.getItem(THEME_PREF_KEY);
    if (pref === "light" || pref === "dark" || pref === "system") {
      return pref;
    }
    // Backward compatibility with older binary setting.
    const legacy = localStorage.getItem("hydra_theme");
    if (legacy === "light" || legacy === "dark") {
      return legacy;
    }
  } catch {
    // ignore storage errors
  }
  return "system";
}

function AppShell({ darkMode, setDarkMode }: { darkMode: boolean; setDarkMode: (dark: boolean) => void }) {
  const location = useLocation();
  const navigate = useNavigate();
  const { domain: activeDomain } = useActiveDomain();
  const [authOpen, setAuthOpen] = useState(!hasAnyToken());
  const { colors } = useTheme();
  const { Header, Content } = Layout;

  useEffect(() => {
    setAuthOpen(!hasAnyToken());
  }, [activeDomain]);

  useEffect(() => {
    const onAuthRequired = () => setAuthOpen(true);
    window.addEventListener(AUTH_REQUIRED_EVENT, onAuthRequired);
    return () => window.removeEventListener(AUTH_REQUIRED_EVENT, onAuthRequired);
  }, []);
  const navItems = useMemo(
    () => {
      const items = [
        { value: "operate", label: "Operate", path: "/" },
        { value: "observe", label: "Observe", path: "/observe" },
        { value: "workers", label: "Workers", path: "/workers" },
      ];
      return items;
    },
    [],
  );
  const currentNav = useMemo(() => {
    if (location.pathname.startsWith("/observe")) return "observe";
    if (location.pathname.startsWith("/workers")) return "workers";
    if (location.pathname.startsWith("/admin")) return undefined;
    return "operate";
  }, [location.pathname]);

  if (authOpen) {
    return (
      <ConfigProvider
        theme={{
          algorithm: darkMode ? theme.darkAlgorithm : theme.defaultAlgorithm,
          token: darkMode
            ? { colorPrimary: "#38bdf8", colorBgContainer: "#131c2e", colorBgLayout: "#0c1220", fontFamily: "'IBM Plex Sans', -apple-system, system-ui, sans-serif" }
            : { colorPrimary: "#2563eb", fontFamily: "'IBM Plex Sans', -apple-system, system-ui, sans-serif" },
        }}
      >
        <Layout style={{ minHeight: "100vh", background: darkMode ? "#06090f" : colors.bgSecondary }}>
          <Content style={{ display: "flex", alignItems: "center", justifyContent: "center" }}>
            <AuthPrompt
              open
              onClose={() => {}}
              onSuccess={() => {
                setAuthOpen(!hasAnyToken());
              }}
            />
          </Content>
        </Layout>
      </ConfigProvider>
    );
  }

  return (
    <ConfigProvider
      theme={{
        algorithm: darkMode ? theme.darkAlgorithm : theme.defaultAlgorithm,
        token: darkMode
          ? {
              colorPrimary: "#38bdf8",
              colorBgContainer: "#131c2e",
              colorBgLayout: "#0c1220",
              colorBgElevated: "#1c2940",
              colorBorder: "rgba(148,163,184,0.15)",
              colorBorderSecondary: "rgba(148,163,184,0.08)",
              colorText: "#f1f5f9",
              colorTextSecondary: "#94a3b8",
              colorSuccess: "#34d399",
              colorError: "#f87171",
              colorWarning: "#fbbf24",
              colorInfo: "#60a5fa",
              fontFamily: "'IBM Plex Sans', -apple-system, system-ui, sans-serif",
            }
          : {
              colorPrimary: "#2563eb",
              fontFamily: "'IBM Plex Sans', -apple-system, system-ui, sans-serif",
            },
      }}
    >
      <Layout>
        <Header
          style={{
            padding: "0 24px",
            height: 56,
            lineHeight: "normal",
            position: "sticky",
            top: 0,
            zIndex: 1000,
            width: "100%",
            background: darkMode
              ? "linear-gradient(180deg, #0c1220 0%, #0f1729 100%)"
              : "linear-gradient(180deg, #ffffff 0%, #f8fafc 100%)",
            borderBottom: `1px solid ${darkMode ? "rgba(148,163,184,0.10)" : "rgba(15,23,42,0.08)"}`,
            backdropFilter: "blur(12px)",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
            <div
              style={{ display: "flex", alignItems: "center", gap: 10, cursor: "pointer" }}
              onClick={() => navigate("/")}
            >
              <HydraLogo size={28} color={colors.primary} />
              <span
                style={{
                  fontSize: 15,
                  fontWeight: 600,
                  color: darkMode ? "#f1f5f9" : "#0f172a",
                  letterSpacing: "-0.01em",
                  fontFamily: "'IBM Plex Sans', system-ui, sans-serif",
                }}
              >
                Hydra
              </span>
            </div>
            <Segmented
              className="header-nav-tabs v2-nav-pill"
              value={currentNav}
              options={navItems.map((item) => ({ label: item.label, value: item.value }))}
              onChange={(value) => {
                const next = navItems.find((item) => item.value === value);
                if (next) navigate(next.path);
              }}
            />
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <button
              className="v2-theme-btn"
              onClick={() => setDarkMode(!darkMode)}
              title="Toggle theme"
            >
              {darkMode ? "☀" : "☽"}
            </button>
            <Button
              type={location.pathname.startsWith("/admin") ? "primary" : "default"}
              onClick={() => navigate("/admin")}
            >
              Admin
            </Button>
            <HeaderSettings />
          </div>
        </Header>
        <Content
          style={{
            background: darkMode ? "#0c1220" : colors.bgSecondary,
            minHeight: "calc(100vh - 56px)"
          }}
          className="main-content"
        >
          <Routes>
            <Route path="/" element={<HomePage />} />
            <Route path="/observe" element={<ObservePage />} />
            <Route path="/workers" element={<WorkersPage />} />
            <Route path="/workers/:workerId" element={<WorkerDetailPage />} />
            <Route
              path="/admin"
              element={<AdminPage />}
            />
            <Route path="/jobs/:jobId" element={<JobDetailPage />} />
          </Routes>
        </Content>
      </Layout>
    </ConfigProvider>
  );
}

export default function App() {
  const [themePreference, setThemePreference] = useState<ThemePreference>(() => getInitialThemePreference());
  const [darkMode, setDarkMode] = useState<boolean>(() => {
    const pref = getInitialThemePreference();
    return pref === "system" ? getSystemDarkMode() : pref === "dark";
  });

  useEffect(() => {
    if (themePreference !== "system") return;
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const apply = () => setDarkMode(media.matches);
    apply();
    media.addEventListener?.("change", apply);
    return () => media.removeEventListener?.("change", apply);
  }, [themePreference]);

  useEffect(() => {
    if (themePreference === "system") {
      setDarkMode(getSystemDarkMode());
    } else {
      setDarkMode(themePreference === "dark");
    }
  }, [themePreference]);

  useEffect(() => {
    localStorage.setItem(THEME_PREF_KEY, themePreference);
    // Keep legacy key synchronized for older code paths.
    localStorage.setItem("hydra_theme", darkMode ? "dark" : "light");
  }, [darkMode, themePreference]);

  useEffect(() => {
    document.documentElement.setAttribute("data-hydra-theme", darkMode ? "dark" : "light");
  }, [darkMode]);
  
  return (
    <ActiveDomainProvider>
      <ThemeProvider isDarkMode={darkMode}>
        <AppShellWrapper
          darkMode={darkMode}
          setDarkMode={(dark) => {
            setThemePreference(dark ? "dark" : "light");
            setDarkMode(dark);
          }}
        />
      </ThemeProvider>
    </ActiveDomainProvider>
  );
}

function AppShellWrapper({ darkMode, setDarkMode }: { darkMode: boolean; setDarkMode: (dark: boolean) => void }) {
  return <AppShell darkMode={darkMode} setDarkMode={setDarkMode} />;
}
