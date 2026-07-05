import { Button, Card, Table, Tag, Space, Segmented, Row, Col, Tooltip, Input, Select, Switch, Popconfirm } from "antd";
import { CopyOutlined, DeleteOutlined, SearchOutlined } from "@ant-design/icons";
import { Link } from "react-router-dom";
import { JobDefinition } from "../types";
import { JobCard } from "./JobCard";
import { useMemo, useState } from "react";
import { AppstoreOutlined, UnorderedListOutlined } from "@ant-design/icons";

interface Props {
  jobs?: JobDefinition[];
  onSelect: (job: JobDefinition) => void;
  selectedId?: string | null;
  loading?: boolean;
  onEdit?: () => void;
  onRun?: (jobId: string) => void;
  onClone?: (job: JobDefinition) => void;
  onToggleEnabled?: (job: JobDefinition, enabled: boolean) => void;
  onDelete?: (job: JobDefinition) => void;
  togglingJobId?: string | null;
}

export function JobList({
  jobs,
  onSelect,
  selectedId,
  loading,
  onEdit,
  onRun,
  onClone,
  onToggleEnabled,
  onDelete,
  togglingJobId,
}: Props) {
  const [viewMode, setViewMode] = useState<"table" | "card">("table");
  const [searchText, setSearchText] = useState("");
  const [tagFilter, setTagFilter] = useState<string[]>([]);

  const availableTags = useMemo(
    () => Array.from(new Set((jobs ?? []).flatMap((j) => j.tags ?? []))).sort(),
    [jobs],
  );

  const filteredJobs = useMemo(() => {
    let result = jobs ?? [];
    const needle = searchText.trim().toLowerCase();
    if (needle) {
      result = result.filter(
        (j) =>
          j.name.toLowerCase().includes(needle) ||
          j._id.toLowerCase().includes(needle) ||
          j.user.toLowerCase().includes(needle) ||
          (j.tags ?? []).some((t) => t.toLowerCase().includes(needle)),
      );
    }
    if (tagFilter.length) {
      result = result.filter((j) => tagFilter.every((t) => (j.tags ?? []).includes(t)));
    }
    return result;
  }, [jobs, searchText, tagFilter]);

  const dataSource = filteredJobs.map((job) => ({ ...job, key: job._id }));
  const columns = [
    {
      title: "Name",
      dataIndex: "name",
      key: "name",
      render: (_: unknown, record: JobDefinition) => (
        <Space direction="vertical" size={0}>
          <Link to={`/jobs/${record._id}`}>{record.name}</Link>
          {(record.tags ?? []).length > 0 && (
            <Space size={2} wrap>
              {(record.tags ?? []).map((t) => (
                <Tag key={t} style={{ fontSize: 11, lineHeight: "16px", marginRight: 0 }}>
                  {t}
                </Tag>
              ))}
            </Space>
          )}
        </Space>
      ),
    },
    { title: "Domain", dataIndex: "domain", key: "domain", render: (value?: string) => value ?? "prod" },
    { title: "User", dataIndex: "user", key: "user" },
    {
      title: "Executor",
      key: "executor",
      render: (_: unknown, record: JobDefinition) => <Tag color="geekblue">{record.executor.type}</Tag>,
    },
    { title: "Priority", dataIndex: "priority", key: "priority" },
    {
      title: "Schedule",
      key: "schedule",
      render: (_: unknown, record: JobDefinition) => (
        <div>
          <strong>{record.schedule.mode === "immediate" ? "manual" : record.schedule.mode}</strong>
          <br />
          <small>
            {!record.schedule.enabled
              ? "paused"
              : record.schedule.next_run_at
                ? new Date(record.schedule.next_run_at).toLocaleString()
                : record.schedule.mode === "immediate"
                  ? "manual"
                  : "pending"}
          </small>
        </div>
      ),
    },
    ...(onToggleEnabled
      ? [
          {
            title: "Enabled",
            key: "enabled",
            width: 80,
            render: (_: unknown, record: JobDefinition) => (
              <Tooltip title={record.schedule.enabled ? "Pause scheduling" : "Resume scheduling"}>
                <Switch
                  size="small"
                  checked={record.schedule.enabled}
                  loading={togglingJobId === record._id}
                  onChange={(checked, e) => {
                    e?.stopPropagation();
                    onToggleEnabled(record, checked);
                  }}
                  onClick={(_checked, e) => e?.stopPropagation()}
                />
              </Tooltip>
            ),
          },
        ]
      : []),
    { title: "Retries", dataIndex: "retries", key: "retries" },
    {
      title: "Updated",
      dataIndex: "updated_at",
      key: "updated_at",
      render: (value: string) => new Date(value).toLocaleString(),
    },
    ...(onClone || onDelete
      ? [
          {
            title: "",
            key: "actions",
            width: 88,
            render: (_: unknown, record: JobDefinition) => (
              <Space size={4}>
                {onClone && (
                  <Tooltip title="Duplicate job">
                    <Button
                      size="small"
                      icon={<CopyOutlined />}
                      onClick={(e) => {
                        e.stopPropagation();
                        onClone(record);
                      }}
                    />
                  </Tooltip>
                )}
                {onDelete && (
                  <Popconfirm
                    title={`Delete job "${record.name}"?`}
                    description="The definition and pending queue entries are removed. Run history is preserved."
                    okText="Delete"
                    okButtonProps={{ danger: true }}
                    onConfirm={(e) => {
                      e?.stopPropagation();
                      onDelete(record);
                    }}
                    onCancel={(e) => e?.stopPropagation()}
                  >
                    <Tooltip title="Delete job">
                      <Button
                        size="small"
                        danger
                        icon={<DeleteOutlined />}
                        onClick={(e) => e.stopPropagation()}
                      />
                    </Tooltip>
                  </Popconfirm>
                )}
              </Space>
            ),
          },
        ]
      : []),
  ];

  return (
    <Card
      title={
        <Space style={{ justifyContent: "space-between", width: "100%", flexWrap: "wrap" }}>
          <span>Jobs</span>
          <Space wrap>
            <Input
              allowClear
              placeholder="Search name, id, user, tag…"
              prefix={<SearchOutlined style={{ opacity: 0.5 }} />}
              value={searchText}
              onChange={(e) => setSearchText(e.target.value)}
              style={{ width: 220 }}
              size="small"
            />
            <Select
              mode="multiple"
              allowClear
              placeholder="Filter tags"
              value={tagFilter}
              onChange={setTagFilter}
              options={availableTags.map((t) => ({ label: t, value: t }))}
              style={{ minWidth: 140 }}
              size="small"
              maxTagCount="responsive"
            />
            <Segmented
              value={viewMode}
              onChange={(value) => setViewMode(value as "table" | "card")}
              options={[
                { label: "Table", value: "table", icon: <UnorderedListOutlined /> },
                { label: "Cards", value: "card", icon: <AppstoreOutlined /> },
              ]}
            />
          </Space>
        </Space>
      }
      bordered={false}
      loading={loading}
    >
      {(searchText || tagFilter.length > 0) && (
        <div style={{ marginBottom: 8, fontSize: 12, opacity: 0.65 }}>
          Showing {filteredJobs.length} of {(jobs ?? []).length} jobs
        </div>
      )}
      {viewMode === "table" ? (
        <Table
          dataSource={dataSource}
          columns={columns}
          loading={loading}
          pagination={{ pageSize: 10 }}
          size="small"
          rowClassName={(record) => (record._id === selectedId ? "job-row-selected" : "job-row")}
          onRow={(record) => ({
            onClick: () => onSelect(record),
            onDoubleClick: () => {
              onSelect(record);
              onEdit?.();
            },
            style: { cursor: "pointer" },
          })}
          scroll={{ x: 800 }}
        />
      ) : (
        <Row gutter={[16, 16]}>
          {dataSource.map((job) => (
            <Col xs={24} sm={12} md={8} lg={6} key={job._id}>
              <div onClick={() => onSelect(job)}>
                <JobCard
                  job={job}
                  selected={job._id === selectedId}
                  onEdit={() => {
                    onSelect(job);
                    onEdit?.();
                  }}
                  onRun={() => {
                    onSelect(job);
                    onRun?.(job._id);
                  }}
                  onClone={onClone ? () => onClone(job) : undefined}
                />
              </div>
            </Col>
          ))}
        </Row>
      )}
    </Card>
  );
}
