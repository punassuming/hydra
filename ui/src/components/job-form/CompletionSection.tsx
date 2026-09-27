import { Col, Form, Input, Row } from "antd";
import { JobPayload } from "../../api/jobs";
import { parseList } from "./defaults";

interface Props {
  completion: JobPayload["completion"];
  updateCompletion: (update: Record<string, unknown>) => void;
}

export function CompletionSection({ completion, updateCompletion }: Props) {
  const setCompletionList = (field: keyof JobPayload["completion"], value: string) => {
    updateCompletion({ [field]: parseList(value) });
  };

  return (
    <>
      <Row gutter={16}>
        <Col span={24}>
          <Form.Item label="Exit Codes">
            <Input
              value={completion.exit_codes.join(", ")}
              onChange={(e) => {
                const values = parseList(e.target.value)
                  .map((c) => Number(c))
                  .filter((n) => !Number.isNaN(n));
                updateCompletion({ exit_codes: values.length ? values : [] });
              }}
              placeholder="0, 2"
            />
          </Form.Item>
        </Col>
      </Row>
      <Row gutter={16}>
        <Col xs={24} md={12}>
          <Form.Item label="Stdout must contain">
            <Input.TextArea
              value={completion.stdout_contains.join("\n")}
              onChange={(e) => setCompletionList("stdout_contains", e.target.value)}
              placeholder="ready"
              autoSize
            />
          </Form.Item>
        </Col>
        <Col xs={24} md={12}>
          <Form.Item label="Stdout must NOT contain">
            <Input.TextArea
              value={completion.stdout_not_contains.join("\n")}
              onChange={(e) => setCompletionList("stdout_not_contains", e.target.value)}
              placeholder="error"
              autoSize
            />
          </Form.Item>
        </Col>
      </Row>
      <Row gutter={16}>
        <Col xs={24} md={12}>
          <Form.Item label="Stderr must contain">
            <Input.TextArea
              value={completion.stderr_contains.join("\n")}
              onChange={(e) => setCompletionList("stderr_contains", e.target.value)}
              autoSize
            />
          </Form.Item>
        </Col>
        <Col xs={24} md={12}>
          <Form.Item label="Stderr must NOT contain">
            <Input.TextArea
              value={completion.stderr_not_contains.join("\n")}
              onChange={(e) => setCompletionList("stderr_not_contains", e.target.value)}
              autoSize
            />
          </Form.Item>
        </Col>
      </Row>
    </>
  );
}
