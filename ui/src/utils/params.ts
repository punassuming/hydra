// Run params become environment variables, so names must be valid variable
// names. Keep in sync with scheduler/api/jobs.py (PARAM_KEY_PATTERN) and
// cli/__main__.py.
export const PARAM_KEY_PATTERN = /^[A-Za-z_][A-Za-z0-9_]*$/;
export const PARAM_KEY_MAX_LENGTH = 128;

export interface ParsedParams {
  params: Record<string, string>;
  errors: string[];
}

/** Parse "KEY=VALUE" lines. Blank lines are ignored; every other problem is
 * reported (with its line number) instead of being silently dropped. */
export function parseParams(text: string): ParsedParams {
  const params: Record<string, string> = {};
  const errors: string[] = [];
  text.split("\n").forEach((rawLine, index) => {
    const line = rawLine.trim();
    if (!line) return;
    const lineNo = index + 1;
    const eq = line.indexOf("=");
    if (eq === -1) {
      errors.push(`Line ${lineNo}: expected KEY=VALUE`);
      return;
    }
    const key = line.slice(0, eq).trim();
    const value = line.slice(eq + 1).trim();
    if (!key) {
      errors.push(`Line ${lineNo}: parameter name is empty`);
    } else if (key.length > PARAM_KEY_MAX_LENGTH || !PARAM_KEY_PATTERN.test(key)) {
      errors.push(
        `Line ${lineNo}: "${key}" is not a valid name (letters, digits and underscores; cannot start with a digit; max ${PARAM_KEY_MAX_LENGTH} characters)`,
      );
    } else {
      params[key] = value;
    }
  });
  return { params, errors };
}
