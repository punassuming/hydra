import { Select } from "antd";
import type { CSSProperties } from "react";

export type AIProvider = "gemini" | "openai";

interface ProviderSelectProps {
  value: AIProvider;
  onChange: (value: AIProvider) => void;
  style?: CSSProperties;
}

/** Shared Gemini/OpenAI picker used by every AI-assisted feature (Magic Job
 * Generator, AI Log Assistant, Run Diff Copilot) so provider options and
 * labels only need to change in one place. */
export function ProviderSelect({ value, onChange, style }: ProviderSelectProps) {
  return (
    <Select
      value={value}
      onChange={onChange}
      options={[
        { label: "Gemini", value: "gemini" },
        { label: "OpenAI", value: "openai" },
      ]}
      style={{ width: 110, ...style }}
    />
  );
}
