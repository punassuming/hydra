import { Col, Form, InputNumber, Row, Switch, Typography } from "antd";
import { JobPayload } from "../../api/jobs";

interface Props {
  payload: JobPayload;
  updatePayload: (field: keyof JobPayload, value: unknown) => void;
}

export function MiscSection({ payload, updatePayload }: Props) {
  return (
    <Row gutter={16}>
      <Col xs={24} md={8}>
        <Form.Item label="Priority (higher runs first)">
          <InputNumber
            min={0}
            max={100}
            style={{ width: "100%" }}
            value={payload.priority}
            onChange={(value) => updatePayload("priority", Number(value))}
          />
        </Form.Item>
      </Col>
      <Col xs={24} md={8}>
        <Form.Item
          label="SLA Max Duration (seconds)"
          tooltip="Alert (without stopping) if the job runs longer than this. Leave blank to disable."
        >
          <InputNumber
            min={1}
            style={{ width: "100%" }}
            value={payload.sla_max_duration_seconds ?? undefined}
            onChange={(value) => updatePayload("sla_max_duration_seconds", value ?? null)}
            placeholder="No SLA limit"
          />
        </Form.Item>
      </Col>
      <Col xs={24} md={8}>
        <Form.Item label="Bypass Worker Concurrency Quota">
          <Switch
            checked={Boolean(payload.bypass_concurrency)}
            onChange={(checked) => updatePayload("bypass_concurrency", checked)}
          />
          <Typography.Text type="secondary" style={{ marginLeft: 8 }}>
            Run beyond worker max concurrency
          </Typography.Text>
        </Form.Item>
      </Col>
    </Row>
  );
}
