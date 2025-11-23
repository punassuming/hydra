import { Button, Card, Table, Tag } from "antd";
import { Link } from "react-router-dom";
import { JobDefinition } from "../types";

interface Props {
  jobs?: JobDefinition[];
  onSelect: (job: JobDefinition) => void;
  selectedId?: string | null;
  loading?: boolean;
}

export function JobList({ jobs, onSelect, selectedId, loading }: Props) {
  const dataSource = (jobs ?? []).map((job) => ({ ...job, key: job._id }));
  const columns = [
    {
      title: "Name",
      dataIndex: "name",
      key: "name",
      render: (_: unknown, record: JobDefinition) => <Link to={`/jobs/${record._id}`}>{record.name}</Link>,
    },
    { title: "User", dataIndex: "user", key: "user" },
    {
      title: "Executor",
      key: "executor",
      render: (_: unknown, record: JobDefinition) => <Tag color="geekblue">{record.executor.type}</Tag>,
    },
    {
      title: "Schedule",
      key: "schedule",
      render: (_: unknown, record: JobDefinition) => (
        <div>
          <strong>{record.schedule.mode}</strong>
          <br />
          <small>
            {!record.schedule.enabled
              ? "disabled"
              : record.schedule.next_run_at
                ? new Date(record.schedule.next_run_at).toLocaleString()
                : record.schedule.mode === "immediate"
                  ? "immediate"
                  : "pending"}
          </small>
        </div>
      ),
    },
    { title: "Retries", dataIndex: "retries", key: "retries" },
    {
      title: "Updated",
      dataIndex: "updated_at",
      key: "updated_at",
      render: (value: string) => new Date(value).toLocaleString(),
    },
  ];

  return (
    <Card title="Jobs" bordered={false}>
      <Table
        dataSource={dataSource}
        columns={columns}
        loading={loading}
        pagination={{ pageSize: 6 }}
        size="small"
        rowClassName={(record) => (record._id === selectedId ? "job-row-selected" : "job-row")}
        onRow={(record) => ({
          onClick: () => onSelect(record),
          style: { cursor: "pointer" },
        })}
      />
    </Card>
  );
}
