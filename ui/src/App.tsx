import { useMemo, useState } from "react";
import { Layout, Typography, Space, Menu, Switch as AntSwitch } from "antd";
import { Routes, Route, Link, useLocation } from "react-router-dom";
import { ConfigProvider, theme } from "antd";
import { HomePage } from "./pages/Home";
import { ComingSoon } from "./pages/ComingSoon";
import { JobDetailPage } from "./pages/JobDetail";
import { HydraLogo } from "./components/HydraLogo";

function App() {
  const location = useLocation();
  const [darkMode, setDarkMode] = useState(false);
  const { Header, Content } = Layout;
  const menuItems = useMemo(
    () => [
      { label: <Link to="/">Home</Link>, key: "home" },
      { label: <Link to="/browse">Browse</Link>, key: "browse" },
      { label: <Link to="/admin">Admin</Link>, key: "admin" },
    ],
    [],
  );

  const currentKey = useMemo(() => {
    if (location.pathname.startsWith("/browse")) return "browse";
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
      <Layout style={{ minHeight: "100vh" }}>
        <Header
          style={{
            padding: "0 24px",
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
              gap: 16,
            }}
          >
            <Space align="center">
              <HydraLogo size={40} color="#38bdf8" />
              <Space direction="vertical" size={0}>
                <Typography.Title level={3} style={{ color: "#fff", margin: 0 }}>
                  Hydra Scheduler
                </Typography.Title>
                <Typography.Text style={{ color: "#cbd5f5" }}>Jobs, tasks, and insights at a glance</Typography.Text>
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
              <Space>
                <Typography.Text style={{ color: "#cbd5f5" }}>Dark Mode</Typography.Text>
                <AntSwitch checked={darkMode} onChange={setDarkMode} />
              </Space>
            </Space>
          </div>
        </Header>
        <Content style={{ padding: 24, background: darkMode ? "#0f172a" : "#f5f7fb" }}>
          <Routes>
            <Route path="/" element={<HomePage />} />
            <Route path="/browse" element={<ComingSoon title="Browse" description="Global browsing utilities will appear here." />} />
            <Route path="/admin" element={<ComingSoon title="Admin" description="Administration pages are under construction." />} />
            <Route path="/jobs/:jobId" element={<JobDetailPage />} />
          </Routes>
        </Content>
      </Layout>
    </ConfigProvider>
  );
}

export default App;
