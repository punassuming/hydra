import { useMemo, useState } from "react";
import { Layout, Typography, Space, Menu, Switch as AntSwitch } from "antd";
import { Routes, Route, Link, useLocation } from "react-router-dom";
import { ConfigProvider, theme } from "antd";
import { HomePage } from "./pages/Home";
import { BrowsePage } from "./pages/Browse";
import { ComingSoon } from "./pages/ComingSoon";
import { JobDetailPage } from "./pages/JobDetail";
import { HistoryPage } from "./pages/History";
import { StatusPage } from "./pages/Status";
import { WorkersPage } from "./pages/Workers";
import { AdminPage } from "./pages/Admin";
import { HydraLogo } from "./components/HydraLogo";
import { DomainSelector } from "./components/DomainSelector";
import { AuthPrompt } from "./components/AuthPrompt";
import { hasAnyToken } from "./api/client";

function App() {
  const location = useLocation();
  const [darkMode, setDarkMode] = useState(false);
  const [authOpen, setAuthOpen] = useState(!hasAnyToken());
  const { Header, Content } = Layout;
  const menuItems = useMemo(
    () => [
      { label: <Link to="/">Home</Link>, key: "home" },
      { label: <Link to="/status">Status</Link>, key: "status" },
      { label: <Link to="/history">History</Link>, key: "history" },
      { label: <Link to="/browse">Jobs</Link>, key: "browse" },
      { label: <Link to="/workers">Workers</Link>, key: "workers" },
      { label: <Link to="/admin">Admin</Link>, key: "admin" },
    ],
    [],
  );

  const currentKey = useMemo(() => {
    if (location.pathname.startsWith("/status")) return "status";
    if (location.pathname.startsWith("/history")) return "history";
    if (location.pathname.startsWith("/browse")) return "browse";
    if (location.pathname.startsWith("/workers")) return "workers";
    if (location.pathname.startsWith("/admin")) return "admin";
    return "home";
  }, [location.pathname]);

  return (
    <ConfigProvider
      theme={{
        algorithm: darkMode ? theme.darkAlgorithm : theme.defaultAlgorithm,
        token: {
          colorPrimary: "#2563eb",
          borderRadius: 6,
        },
      }}
    >
      <Layout>
        <Header
          style={{
            padding: "12px 24px",
            minHeight: 72,
            lineHeight: "normal",
            position: "sticky",
            top: 0,
            zIndex: 1000,
            width: "100%",
            background: darkMode ? "#050b18" : "#0f172a",
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              flexWrap: "wrap",
            }}
          >
            <Space align="center">
              <HydraLogo size={40} color="#38bdf8" />
              <Space size={20} align="baseline">
                <Typography.Title
                  level={3}
                  style={{ color: "#fff", margin: 0 }}
                >
                  Hydra Scheduler
                </Typography.Title>
                <Typography.Text style={{ color: "#cbd5f5" }}>
                  Jobs, tasks, and insights at a glance
                </Typography.Text>
              </Space>
            </Space>
            <Space align="center" size="large" style={{ flexWrap: "wrap" }}>
              <Menu
                theme="dark"
                mode="horizontal"
                selectedKeys={[currentKey]}
                items={menuItems}
                style={{ background: "transparent", borderBottom: "none" }}
              />
              <DomainSelector />
              <Space>
                <Typography.Text style={{ color: "#cbd5f5" }}>
                  Dark Mode
                </Typography.Text>
                <AntSwitch checked={darkMode} onChange={setDarkMode} />
              </Space>
            </Space>
          </div>
        </Header>
        <Content
          style={{ padding: 24, background: darkMode ? "#0f172a" : "#f5f7fb" }}
        >
          <Routes>
            <Route path="/" element={<HomePage />} />
            <Route path="/status" element={<StatusPage />} />
            <Route path="/history" element={<HistoryPage />} />
            <Route
              path="/browse"
              element={<BrowsePage />}
            />
            <Route path="/workers" element={<WorkersPage />} />
            <Route
              path="/admin"
              element={<AdminPage />}
            />
            <Route path="/jobs/:jobId" element={<JobDetailPage />} />
          </Routes>
        </Content>
        <AuthPrompt open={authOpen} onClose={() => setAuthOpen(false)} onSuccess={() => setAuthOpen(false)} />
      </Layout>
    </ConfigProvider>
  );
}

export default App;
