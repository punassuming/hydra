import { useMemo, useState } from "react";
import { Layout, Typography, Space, Menu, Switch as AntSwitch, Tag } from "antd";
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
import { hasAnyToken, getActiveDomain } from "./api/client";
import { WorkerDetailPage } from "./pages/WorkerDetail";

function App() {
  const location = useLocation();
  const [darkMode, setDarkMode] = useState(false);
  const [authOpen, setAuthOpen] = useState(!hasAnyToken());
  const [activeDomain, setActiveDomain] = useState(getActiveDomain());
  const { Header, Content } = Layout;
  const menuItems = useMemo(
    () => [
      {
        label: "Operate",
        key: "operate",
        children: [
          { label: <Link to="/">Jobs</Link>, key: "operate-home" },
          { label: <Link to="/browse">Job Browser</Link>, key: "operate-browse" },
          { label: <Link to="/workers">Workers</Link>, key: "operate-workers" },
        ],
      },
      {
        label: "Observe",
        key: "observe",
        children: [
          { label: <Link to="/status">Status</Link>, key: "observe-status" },
          { label: <Link to="/history">History</Link>, key: "observe-history" },
        ],
      },
      { label: <Link to="/admin">Admin</Link>, key: "admin" },
    ],
    [],
  );

  const currentKey = useMemo(() => {
    if (location.pathname.startsWith("/status")) return "observe-status";
    if (location.pathname.startsWith("/history")) return "observe-history";
    if (location.pathname.startsWith("/browse")) return "operate-browse";
    if (location.pathname.startsWith("/workers")) return "operate-workers";
    if (location.pathname.startsWith("/admin")) return "admin";
    return "operate-home";
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
              <Space size={12} align="center">
                <Tag color="cyan" style={{ marginRight: 0 }}>
                  Domain: {activeDomain}
                </Tag>
                <DomainSelector onChange={setActiveDomain} />
              </Space>
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
            <Route path="/workers/:workerId" element={<WorkerDetailPage />} />
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
