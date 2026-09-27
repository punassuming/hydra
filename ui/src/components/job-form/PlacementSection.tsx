import { Col, Form, Row, Select, Typography } from "antd";
import { JobPayload } from "../../api/jobs";
import { defaultAffinity, WorkerHints } from "./defaults";

interface Props {
  payload: JobPayload;
  updateAffinity: (key: keyof typeof defaultAffinity, value: string[]) => void;
  workerHints: WorkerHints;
}

export function PlacementSection({ payload, updateAffinity, workerHints }: Props) {
  return (
    <>
      <Row gutter={16}>
                <Col xs={24} md={8}>
                  <Form.Item label="Target OS">
                    <Select
                      mode="tags"
                      value={payload.affinity.os}
                      onChange={(vals) => updateAffinity("os", vals)}
                      options={workerHints.os.map((v) => ({ label: v, value: v }))}
                      placeholder="linux, windows"
                    />
                  </Form.Item>
                </Col>
                <Col xs={24} md={8}>
                  <Form.Item label="Tags">
                    <Select
                      mode="tags"
                      value={payload.affinity.tags}
                      onChange={(vals) => updateAffinity("tags", vals)}
                      options={workerHints.tags.map((v) => ({ label: v, value: v }))}
                      placeholder="gpu, python, ingest"
                    />
                  </Form.Item>
                </Col>
                <Col xs={24} md={8}>
                  <Form.Item label="Allowed Users">
                    <Select
                      mode="tags"
                      value={payload.affinity.allowed_users}
                      onChange={(vals) => updateAffinity("allowed_users", vals)}
                      options={workerHints.users.map((v) => ({ label: v, value: v }))}
                      placeholder="alice, bob"
                    />
                  </Form.Item>
                </Col>
              </Row>
              <Row gutter={16}>
                <Col xs={24} md={8}>
                  <Form.Item label="Hostnames">
                    <Select
                      mode="tags"
                      value={payload.affinity.hostnames ?? []}
                      onChange={(vals) => updateAffinity("hostnames", vals)}
                      options={workerHints.hostnames.map((v) => ({ label: v, value: v }))}
                      placeholder="worker-1, batch-2"
                    />
                  </Form.Item>
                </Col>
                <Col xs={24} md={8}>
                  <Form.Item label="Subnets">
                    <Select
                      mode="tags"
                      value={payload.affinity.subnets ?? []}
                      onChange={(vals) => updateAffinity("subnets", vals)}
                      options={workerHints.subnets.map((v) => ({ label: v, value: v }))}
                      placeholder="10.0.1"
                    />
                  </Form.Item>
                </Col>
                <Col xs={24} md={8}>
                  <Form.Item label="Deployment Types">
                    <Select
                      mode="tags"
                      value={payload.affinity.deployment_types ?? []}
                      onChange={(vals) => updateAffinity("deployment_types", vals)}
                      options={workerHints.deployments.map((v) => ({ label: v, value: v }))}
                      placeholder="docker, kubernetes"
                    />
                  </Form.Item>
                </Col>
              </Row>
      <Typography.Text type="secondary">
        Executor type matching is automatic based on the selected executor.
      </Typography.Text>
    </>
  );
}
