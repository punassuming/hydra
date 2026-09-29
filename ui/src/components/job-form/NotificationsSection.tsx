import { Col, Form, Input, Row, Space, Switch, Typography } from "antd";
import { JobPayload } from "../../api/jobs";
import { parseList } from "./defaults";

interface Props {
  payload: JobPayload;
  updatePayload: (field: keyof JobPayload, value: unknown) => void;
  notifyWebhookEnabled: boolean;
  setNotifyWebhookEnabled: (v: boolean) => void;
  notifyEmailEnabled: boolean;
  setNotifyEmailEnabled: (v: boolean) => void;
}

export function NotificationsSection({
  payload,
  updatePayload,
  notifyWebhookEnabled,
  setNotifyWebhookEnabled,
  notifyEmailEnabled,
  setNotifyEmailEnabled,
}: Props) {
  return (
    <Space direction="vertical" style={{ width: "100%" }} size={6}>
              <Space>
                <Typography.Text strong>Webhook Alerts</Typography.Text>
                <Switch checked={notifyWebhookEnabled} onChange={setNotifyWebhookEnabled} />
              </Space>
              {notifyWebhookEnabled && (
                <Form.Item label="Failure Webhook URLs (one per line)" tooltip="HTTP POST will be sent on terminal failure">
                  <Input.TextArea
                    value={(payload.on_failure_webhooks ?? []).join("\n")}
                    onChange={(e) => updatePayload("on_failure_webhooks", parseList(e.target.value))}
                    placeholder="https://hooks.example.com/alert"
                    autoSize={{ minRows: 2 }}
                  />
                </Form.Item>
              )}
              <Space>
                <Typography.Text strong>Email Alerts</Typography.Text>
                <Switch checked={notifyEmailEnabled} onChange={setNotifyEmailEnabled} />
              </Space>
              {notifyEmailEnabled && (
                <>
                  <Row gutter={16}>
                    <Col xs={24} md={10}>
                      <Form.Item label="SMTP Credential Ref" tooltip="Domain credential name containing SMTP auth and host settings.">
                        <Input
                          value={payload.on_failure_email_credential_ref ?? ""}
                          onChange={(e) => updatePayload("on_failure_email_credential_ref", e.target.value)}
                          placeholder="smtp-alerts"
                        />
                      </Form.Item>
                    </Col>
                  </Row>
                  <Form.Item
                    label="Failure Email Recipients (one per line)"
                    tooltip="Email addresses to notify on terminal failure."
                  >
                    <Input.TextArea
                      value={(payload.on_failure_email_to ?? []).join("\n")}
                      onChange={(e) => updatePayload("on_failure_email_to", parseList(e.target.value))}
                      placeholder="ops@example.com"
                      autoSize={{ minRows: 2 }}
                    />
                  </Form.Item>
                </>
              )}
    </Space>
  );
}
