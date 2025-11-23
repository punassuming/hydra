import { Card, Typography } from "antd";

interface Props {
  title: string;
  description?: string;
}

export function ComingSoon({ title, description }: Props) {
  return (
    <Card>
      <Typography.Title level={3}>{title}</Typography.Title>
      <Typography.Paragraph>
        {description ?? "This section is under construction. Check back soon for full functionality."}
      </Typography.Paragraph>
    </Card>
  );
}
