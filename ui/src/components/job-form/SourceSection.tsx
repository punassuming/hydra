import { Alert, Col, Form, Input, Row, Select, Switch, Typography } from "antd";
import { SourceConfig } from "../../types";
import { JobPayload } from "../../api/jobs";

interface Props {
  source: JobPayload["source"];
  updateSource: (update: Partial<SourceConfig> | null) => void;
}

export function SourceSection({ source, updateSource }: Props) {
  return (
    <>
      <Row gutter={16} align="middle">
                <Col xs={24} md={12}>
                  <Form.Item label="Enable Source Provisioning">
                    <Switch
                      checked={!!source}
                      onChange={(checked) => updateSource(checked ? { protocol: "git", url: "", ref: "main" } : null)}
                    />
                    <Typography.Text type="secondary" style={{ marginLeft: 8 }}>
                      Provision source code before running the job
                    </Typography.Text>
                  </Form.Item>
                </Col>
                {source && (
                  <Col xs={24} md={6}>
                    <Form.Item label="Protocol">
                      <Select
                        value={source.protocol ?? "git"}
                        onChange={(v) => {
                          const proto = v as "git" | "copy" | "rsync";
                          updateSource({ protocol: proto, url: "", ref: proto === "git" ? "main" : "", path: null, sparse: false, credential_ref: null });
                        }}
                        options={[
                          { label: "Git clone", value: "git" },
                          { label: "Remote copy (rsync)", value: "rsync" },
                          { label: "Local copy", value: "copy" },
                        ]}
                      />
                    </Form.Item>
                  </Col>
                )}
              </Row>
              {source && (source.protocol ?? "git") === "git" && (
                <>
                  <Row gutter={16}>
                    <Col xs={24} md={12}>
                      <Form.Item label="Repository URL" required>
                        <Input
                          value={source.url ?? ""}
                          onChange={(e) => updateSource({ url: e.target.value })}
                          placeholder="https://github.com/user/repo.git"
                        />
                      </Form.Item>
                    </Col>
                    <Col xs={24} md={6}>
                      <Form.Item label="Branch / Tag / Ref">
                        <Input
                          value={source.ref ?? "main"}
                          onChange={(e) => updateSource({ ref: e.target.value || "main" })}
                          placeholder="main"
                        />
                      </Form.Item>
                    </Col>
                    <Col xs={24} md={6}>
                      <Form.Item label="Sub-directory (optional)">
                        <Input
                          value={source.path ?? ""}
                          onChange={(e) => updateSource({ path: e.target.value || null })}
                          placeholder="scripts/jobs"
                        />
                      </Form.Item>
                    </Col>
                  </Row>
                  <Row gutter={16}>
                    <Col xs={24} md={12}>
                      <Form.Item label="Credential Reference (PAT)">
                        <Input
                          value={source.credential_ref ?? ""}
                          onChange={(e) => updateSource({ credential_ref: e.target.value || null })}
                          placeholder="stored credential name for private repos (optional)"
                        />
                      </Form.Item>
                    </Col>
                    <Col xs={24} md={6}>
                      <Form.Item label="Sparse Checkout">
                        <Switch
                          checked={!!source.sparse}
                          onChange={(checked) => updateSource({ sparse: checked })}
                        />
                        <Typography.Text type="secondary" style={{ marginLeft: 8 }}>
                          Only fetch the sub-directory
                        </Typography.Text>
                      </Form.Item>
                    </Col>
                  </Row>
                </>
              )}
              {source && source.protocol === "rsync" && (
                <Row gutter={16}>
                  <Col xs={24} md={12}>
                    <Form.Item label="Remote Source" required>
                      <Input
                        value={source.url ?? ""}
                        onChange={(e) => updateSource({ url: e.target.value })}
                        placeholder="user@host:/path/to/source"
                      />
                    </Form.Item>
                  </Col>
                  <Col xs={24} md={6}>
                    <Form.Item label="Sub-directory (optional)">
                      <Input
                        value={source.path ?? ""}
                        onChange={(e) => updateSource({ path: e.target.value || null })}
                        placeholder="scripts/jobs"
                      />
                    </Form.Item>
                  </Col>
                  <Col xs={24} md={6}>
                    <Form.Item label="SSH Key Credential (optional)">
                      <Input
                        value={source.credential_ref ?? ""}
                        onChange={(e) => updateSource({ credential_ref: e.target.value || null })}
                        placeholder="stored SSH key credential name"
                      />
                    </Form.Item>
                  </Col>
                </Row>
              )}
              {source && source.protocol === "copy" && (
                <Row gutter={16}>
                  <Col xs={24} md={12}>
                    <Form.Item label="Source Path" required>
                      <Input
                        value={source.url ?? ""}
                        onChange={(e) => updateSource({ url: e.target.value })}
                        placeholder="/data/my-scripts or /opt/app/lib.py"
                      />
                    </Form.Item>
                  </Col>
                  <Col xs={24} md={6}>
                    <Form.Item label="Sub-directory (optional)">
                      <Input
                        value={source.path ?? ""}
                        onChange={(e) => updateSource({ path: e.target.value || null })}
                        placeholder="scripts/jobs"
                      />
                    </Form.Item>
                  </Col>
                </Row>
              )}
              {source && (
                <Alert
                  type="info"
                  showIcon
                  message={
                    (source.protocol ?? "git") === "git"
                      ? source.sparse && source.path
                        ? "Sparse checkout enabled - only the specified sub-directory will be fetched."
                        : "The worker will shallow-clone the repository into a temporary directory before execution."
                      : source.protocol === "rsync"
                        ? "The worker will rsync files from the remote host over SSH into a temporary directory before execution."
                        : "The worker will copy the file or directory from the local filesystem into a temporary directory before execution."
                  }
                  style={{ marginTop: 8 }}
                />
              )}
    </>
  );
}
