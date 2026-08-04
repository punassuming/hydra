import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Alert, Button, Card, Drawer, Empty, Space, Spin, Table, Typography } from "antd";
import {
  ArrowLeftOutlined,
  FireOutlined,
  HourglassOutlined,
  BranchesOutlined,
  StopOutlined,
  SearchOutlined,
  ReloadOutlined,
} from "@ant-design/icons";
import { fetchInvestigationCatalog, runInvestigation, InvestigationResultRow } from "../api/investigations";

interface InvestigateDrawerProps {
  open: boolean;
  onClose: () => void;
}

const ICONS: Record<string, JSX.Element> = {
  failed_recent: <FireOutlined />,
  long_running_outliers: <HourglassOutlined />,
  flaky_jobs: <BranchesOutlined />,
  never_succeeded: <StopOutlined />,
};

/** Canned, LLM-free investigations — click a card, get a straight answer
 * pulled directly from job/run history. No natural-language parsing: every
 * query here is a fixed, whitelisted server-side check (see
 * scheduler/api/investigations.py), so results are instant and don't
 * require an AI provider key to be configured. */
export function InvestigateDrawer({ open, onClose }: InvestigateDrawerProps) {
  const [selectedKey, setSelectedKey] = useState<string | null>(null);

  const catalogQuery = useQuery({
    queryKey: ["investigation-catalog"],
    queryFn: fetchInvestigationCatalog,
    enabled: open,
  });

  const resultQuery = useQuery({
    queryKey: ["investigation", selectedKey],
    queryFn: () => runInvestigation(selectedKey as string),
    enabled: open && !!selectedKey,
  });

  const handleClose = () => {
    setSelectedKey(null);
    onClose();
  };

  const columns = [
    {
      title: "Job",
      key: "job",
      render: (_: unknown, row: InvestigationResultRow) => (
        <Space direction="vertical" size={0}>
          <Typography.Text strong>{row.job_name}</Typography.Text>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {row.job_id}
          </Typography.Text>
        </Space>
      ),
    },
    { title: "Domain", dataIndex: "domain", key: "domain", width: 100 },
    {
      title: "Metric",
      key: "metric",
      render: (_: unknown, row: InvestigationResultRow) => (
        <span>
          <Typography.Text strong>{row.metric_value}</Typography.Text>{" "}
          <Typography.Text type="secondary">{row.metric_label}</Typography.Text>
        </span>
      ),
    },
    {
      title: "Last Run",
      key: "last_run",
      render: (_: unknown, row: InvestigationResultRow) => (
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {row.last_run_at ? new Date(row.last_run_at).toLocaleString() : "-"}
        </Typography.Text>
      ),
    },
  ];

  return (
    <Drawer
      title={
        <Space>
          <SearchOutlined />
          Investigate
        </Space>
      }
      placement="right"
      width={640}
      open={open}
      onClose={handleClose}
    >
      {!selectedKey && (
        <Space direction="vertical" size={12} style={{ width: "100%" }}>
          <Typography.Text type="secondary">
            Pick a canned check to sweep every job for something that needs attention. These run instantly — no AI
            provider required.
          </Typography.Text>
          {catalogQuery.isLoading && <Spin />}
          {catalogQuery.isError && <Alert type="error" showIcon message="Failed to load investigations." />}
          {catalogQuery.data?.map((item) => (
            <Card
              key={item.key}
              hoverable
              size="small"
              onClick={() => setSelectedKey(item.key)}
              styles={{ body: { display: "flex", alignItems: "center", gap: 12 } }}
            >
              <span style={{ fontSize: 20 }}>{ICONS[item.key] ?? <SearchOutlined />}</span>
              <div>
                <Typography.Text strong>{item.label}</Typography.Text>
                <div>
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    {item.description}
                  </Typography.Text>
                </div>
              </div>
            </Card>
          ))}
        </Space>
      )}

      {selectedKey && (
        <Space direction="vertical" size={12} style={{ width: "100%" }}>
          <Space>
            <Button icon={<ArrowLeftOutlined />} onClick={() => setSelectedKey(null)}>
              Back to investigations
            </Button>
            <Button icon={<ReloadOutlined />} onClick={() => resultQuery.refetch()} loading={resultQuery.isFetching}>
              Refresh
            </Button>
          </Space>
          {resultQuery.isLoading && <Spin />}
          {resultQuery.isError && <Alert type="error" showIcon message="Failed to run this investigation." />}
          {resultQuery.data && (
            <>
              <Typography.Title level={5} style={{ margin: 0 }}>
                {resultQuery.data.label}
              </Typography.Title>
              {resultQuery.data.results.length === 0 ? (
                <Empty description="Nothing here — looks healthy." />
              ) : (
                <Table
                  size="small"
                  rowKey={(row) => `${row.job_id}-${row.last_run_id ?? ""}`}
                  columns={columns}
                  dataSource={resultQuery.data.results}
                  pagination={{ pageSize: 10 }}
                />
              )}
            </>
          )}
        </Space>
      )}
    </Drawer>
  );
}
