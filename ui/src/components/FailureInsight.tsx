import { Alert, Button, Collapse, Input, Select, Space, Spin, Tag, Typography } from "antd";
import { BugOutlined, ThunderboltOutlined, QuestionCircleOutlined, DiffOutlined } from "@ant-design/icons";
import { useState } from "react";
import { analyzeRun, diagnoseRegression, RegressionDiagnosis } from "../api/jobs";
import { ProviderSelect, AIProvider } from "./ProviderSelect";

interface FailureInsightProps {
  runId: string;
  stdout?: string;
  stderr?: string;
  exitCode?: number;
  compact?: boolean;
}

const CONFIDENCE_COLOR: Record<RegressionDiagnosis["confidence"], string> = {
  high: "green",
  medium: "orange",
  low: "default",
};

export function FailureInsight({
  runId,
  stdout = "",
  stderr = "",
  exitCode = 1,
  compact = false,
}: FailureInsightProps) {
  const [analysis, setAnalysis] = useState<string | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [provider, setProvider] = useState<AIProvider>("gemini");
  const [analysisType, setAnalysisType] = useState<"failure" | "summary" | "errors" | "retry" | "custom">("failure");
  const [question, setQuestion] = useState("");

  const [diagnosis, setDiagnosis] = useState<RegressionDiagnosis | null>(null);
  const [diagnosing, setDiagnosing] = useState(false);
  const [diagnosisError, setDiagnosisError] = useState<string | null>(null);

  const handleAnalyze = async () => {
    setAnalyzing(true);
    try {
      const res = await analyzeRun({
        run_id: runId,
        stdout,
        stderr,
        exit_code: exitCode,
        provider,
        analysis_type: analysisType,
        question: analysisType === "custom" ? question : undefined,
      });
      setAnalysis(res.analysis);
    } catch (e) {
      console.error(e);
      setAnalysis("Failed to analyze. Please try again.");
    } finally {
      setAnalyzing(false);
    }
  };

  const handleDiagnoseRegression = async () => {
    setDiagnosing(true);
    setDiagnosisError(null);
    try {
      const res = await diagnoseRegression(runId, provider);
      setDiagnosis(res);
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e);
      setDiagnosisError(
        message.startsWith("no_prior_success")
          ? "No successful run of this job exists yet to compare against."
          : `Failed to compare against last success: ${message}`,
      );
    } finally {
      setDiagnosing(false);
    }
  };

  if (diagnosis) {
    return (
      <Alert
        message={
          <Space>
            <DiffOutlined />
            Run Diff Copilot ({provider.toUpperCase()})
            <Tag color={CONFIDENCE_COLOR[diagnosis.confidence]}>{diagnosis.confidence} confidence</Tag>
            <Tag color={diagnosis.is_transient ? "blue" : "red"}>{diagnosis.is_transient ? "Transient" : "Persistent"}</Tag>
          </Space>
        }
        description={
          <div>
            <Typography.Paragraph strong style={{ marginBottom: 8 }}>
              {diagnosis.likely_cause}
            </Typography.Paragraph>
            <Collapse
              size="small"
              ghost
              items={[
                {
                  key: "evidence",
                  label: `Evidence (${diagnosis.evidence.length})`,
                  children: (
                    <ul style={{ margin: 0, paddingLeft: 20 }}>
                      {diagnosis.evidence.map((item, i) => (
                        <li key={i}>{item}</li>
                      ))}
                    </ul>
                  ),
                },
              ]}
            />
            <Typography.Paragraph style={{ marginTop: 8, marginBottom: 8 }}>
              <Typography.Text strong>Suggested fix: </Typography.Text>
              {diagnosis.suggested_fix}
            </Typography.Paragraph>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              Compared against run {diagnosis.compared_run_id}
              {diagnosis.compared_run_started_at ? ` (${new Date(diagnosis.compared_run_started_at).toLocaleString()})` : ""}
              {typeof diagnosis.current_duration_seconds === "number" && typeof diagnosis.baseline_p90_seconds === "number"
                ? ` · this run: ${diagnosis.current_duration_seconds.toFixed(1)}s vs p90 ${diagnosis.baseline_p90_seconds.toFixed(1)}s`
                : ""}
            </Typography.Text>
            <div>
              <Button type="link" size="small" onClick={() => setDiagnosis(null)} style={{ paddingLeft: 0 }}>
                Clear
              </Button>
            </div>
          </div>
        }
        type="warning"
        showIcon
        closable
        onClose={() => setDiagnosis(null)}
        style={{ marginTop: 12 }}
      />
    );
  }

  if (analysis) {
    return (
      <Alert
        message={
          <Space>
            <BugOutlined />
            AI Log Assistant ({provider.toUpperCase()} · {analysisType})
          </Space>
        }
        description={
          <div>
            <pre
              style={{
                whiteSpace: "pre-wrap",
                wordBreak: "break-word",
                fontSize: "13px",
                margin: 0,
              }}
            >
              {analysis}
            </pre>
            <Button
              type="link"
              size="small"
              onClick={() => setAnalysis(null)}
              style={{ paddingLeft: 0 }}
            >
              Clear Analysis
            </Button>
          </div>
        }
        type="warning"
        showIcon
        closable
        onClose={() => setAnalysis(null)}
        style={{ marginTop: 12 }}
      />
    );
  }

  return (
    <div style={{ marginTop: 12 }}>
      <Space direction="vertical" style={{ width: "100%" }} size={8}>
        <Space wrap>
          <ProviderSelect value={provider} onChange={setProvider} />
          <Select
            value={analysisType}
            onChange={(value) => setAnalysisType(value)}
            options={[
              { label: "Fix Failure", value: "failure" },
              { label: "Summarize", value: "summary" },
              { label: "Extract Errors", value: "errors" },
              { label: "Retry Tuning", value: "retry" },
              { label: "Custom", value: "custom" },
            ]}
            style={{ width: compact ? 150 : 190 }}
          />
          {analysisType === "custom" && (
            <Input
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              prefix={<QuestionCircleOutlined />}
              placeholder="Ask about this run"
              style={{ width: compact ? 220 : 340 }}
            />
          )}
        </Space>
        <Space wrap>
          <Button
            onClick={handleAnalyze}
            loading={analyzing}
            icon={analyzing ? <Spin size="small" /> : <ThunderboltOutlined />}
          >
            {analyzing ? "Analyzing..." : compact ? "Analyze Logs" : "Run AI Log Analysis"}
          </Button>
          <Button
            onClick={handleDiagnoseRegression}
            loading={diagnosing}
            icon={diagnosing ? <Spin size="small" /> : <DiffOutlined />}
          >
            {diagnosing ? "Comparing..." : "Compare vs Last Success"}
          </Button>
        </Space>
        {diagnosisError && (
          <Alert type="info" showIcon closable message={diagnosisError} onClose={() => setDiagnosisError(null)} />
        )}
        {!compact && (
          <Typography.Text type="secondary">
            Use the AI Log Assistant to summarize logs or extract errors from this run alone, or Compare vs Last
            Success to diff this run against the job's last successful run and get a grounded root-cause hypothesis.
          </Typography.Text>
        )}
      </Space>
    </div>
  );
}
