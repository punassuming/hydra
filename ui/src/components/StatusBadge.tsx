import { Tag } from "antd";
import {
  CheckCircleOutlined,
  ClockCircleOutlined,
  CloseCircleOutlined,
  FieldTimeOutlined,
  QuestionCircleOutlined,
  SendOutlined,
  SyncOutlined,
} from "@ant-design/icons";
import type { ReactNode } from "react";

interface StatusBadgeProps {
  status: string;
  size?: "small" | "default" | "large";
}

interface StatusConfig {
  color: string;
  icon: ReactNode;
  text: string;
}

// Every status is distinguishable by icon and text, not color alone, so the
// badge stays readable for colorblind users and screen readers.
export function getStatusConfig(status: string): StatusConfig {
  switch (status) {
    case "success":
      return { color: "success", icon: <CheckCircleOutlined />, text: "Success" };
    case "running":
      return { color: "processing", icon: <SyncOutlined spin />, text: "Running" };
    case "failed":
    case "error":
      return { color: "error", icon: <CloseCircleOutlined />, text: status === "error" ? "Error" : "Failed" };
    case "timed_out":
      return { color: "warning", icon: <FieldTimeOutlined />, text: "Timed out" };
    case "dispatched":
      return { color: "cyan", icon: <SendOutlined />, text: "Dispatched" };
    case "queued":
    case "pending":
      return { color: "default", icon: <ClockCircleOutlined />, text: "Queued" };
    default:
      return { color: "default", icon: <QuestionCircleOutlined />, text: status || "Unknown" };
  }
}

export function StatusBadge({ status }: StatusBadgeProps) {
  const config = getStatusConfig(status);

  return (
    <Tag color={config.color} icon={config.icon} style={{ margin: 0 }} aria-label={`Status: ${config.text}`}>
      {config.text}
    </Tag>
  );
}
