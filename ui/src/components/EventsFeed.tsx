import { Card, List, Tag, Typography, Space } from "antd";
import { SchedulerEvent } from "../types";

interface Props {
  events: SchedulerEvent[];
}

export function EventsFeed({ events }: Props) {
  return (
    <Card title="Scheduler Events" bordered={false}>
      {events.length === 0 ? (
        <Typography.Text type="secondary">No recent events.</Typography.Text>
      ) : (
        <List
          dataSource={events}
          renderItem={(evt) => (
            <List.Item key={`${evt.ts}-${evt.type}`}>
              <Space direction="vertical" size={0}>
                <Tag>{evt.type}</Tag>
                <Typography.Text type="secondary">{new Date(evt.ts * 1000).toLocaleTimeString()}</Typography.Text>
                <Typography.Text code>{JSON.stringify(evt.payload)}</Typography.Text>
              </Space>
            </List.Item>
          )}
        />
      )}
    </Card>
  );
}
