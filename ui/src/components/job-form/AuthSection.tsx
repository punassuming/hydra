import { Col, Form, Input, Row, Typography } from "antd";
import { JobPayload } from "../../api/jobs";

interface Props {
  executor: JobPayload["executor"];
  updateExecutor: (update: Record<string, unknown>) => void;
}

export function AuthSection({ executor, updateExecutor }: Props) {
  return (
    <>
      <Row gutter={16}>
                <Col xs={24} md={8}>
                  <Form.Item label="Linux Impersonation User">
                    <Input
                      value={(executor as any).impersonate_user ?? ""}
                      onChange={(e) => updateExecutor({ impersonate_user: e.target.value || null })}
                      placeholder="svc_batch (optional)"
                    />
                  </Form.Item>
                </Col>
                <Col xs={24} md={8}>
                  <Form.Item label="Kerberos Principal">
                    <Input
                      value={(executor as any).kerberos?.principal ?? ""}
                      onChange={(e) =>
                        updateExecutor({
                          kerberos: { ...((executor as any).kerberos ?? {}), principal: e.target.value },
                        })
                      }
                      placeholder="user@REALM"
                    />
                  </Form.Item>
                </Col>
                <Col xs={24} md={8}>
                  <Form.Item label="Kerberos Keytab Path">
                    <Input
                      value={(executor as any).kerberos?.keytab ?? ""}
                      onChange={(e) =>
                        updateExecutor({
                          kerberos: { ...((executor as any).kerberos ?? {}), keytab: e.target.value },
                        })
                      }
                      placeholder="/etc/security/keytabs/user.keytab"
                    />
                  </Form.Item>
                </Col>
                <Col xs={24} md={12}>
                  <Form.Item label="Kerberos Cache (optional)">
                    <Input
                      value={(executor as any).kerberos?.ccache ?? ""}
                      onChange={(e) =>
                        updateExecutor({
                          kerberos: { ...((executor as any).kerberos ?? {}), ccache: e.target.value || null },
                        })
                      }
                      placeholder="/tmp/krb5cc_hydra"
                    />
                  </Form.Item>
                </Col>
              </Row>
      <Typography.Text type="secondary">
        Linux workers only. If impersonate_user is set, worker runs command as sudo -n -u &lt;user&gt; and runs kinit -kt before job execution when Kerberos fields are provided.
      </Typography.Text>
    </>
  );
}
