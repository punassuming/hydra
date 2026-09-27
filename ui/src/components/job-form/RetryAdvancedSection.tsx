import { Col, Form, InputNumber, Row } from "antd";
import { JobPayload } from "../../api/jobs";

interface Props {
  payload: JobPayload;
  updatePayload: (field: keyof JobPayload, value: unknown) => void;
}

export function RetryAdvancedSection({ payload, updatePayload }: Props) {
  return (
    <Row gutter={16}>
      <Col xs={24} md={8}>
        <Form.Item label="Worker-Level Retries" tooltip="Retries within the same worker dispatch (fast, no re-queue)">
          <InputNumber
            min={0}
            style={{ width: "100%" }}
            value={payload.retries}
            onChange={(value) => updatePayload("retries", Number(value))}
          />
        </Form.Item>
      </Col>
      <Col xs={24} md={8}>
        <Form.Item label="Scheduler-Level Retries" tooltip="Re-enqueue to any available worker after terminal failure">
          <InputNumber
            min={0}
            style={{ width: "100%" }}
            value={payload.max_retries ?? 0}
            onChange={(value) => updatePayload("max_retries", Number(value))}
          />
        </Form.Item>
      </Col>
      <Col xs={24} md={8}>
        <Form.Item
          label="Retry Delay (seconds)"
          tooltip="Base delay before the first scheduler retry; each subsequent retry doubles this delay (capped server-side), not a fixed wait every time."
        >
          <InputNumber
            min={0}
            style={{ width: "100%" }}
            value={payload.retry_delay_seconds ?? 0}
            onChange={(value) => updatePayload("retry_delay_seconds", Number(value))}
          />
        </Form.Item>
      </Col>
    </Row>
  );
}
