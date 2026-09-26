package executor

import (
	"context"
	"os"
	"strings"
	"testing"
)

func TestExecShell_Basic(t *testing.T) {
	env := &JobEnvelope{
		JobID: "test-1",
		RunID: "run-1",
		Job: JobDef{
			Executor: ExecutorSpec{
				Type:   "shell",
				Script: "echo hello world",
			},
		},
	}
	result := Execute(context.Background(), env, nil, nil)
	if result.ReturnCode != 0 {
		t.Fatalf("expected rc=0, got %d, stderr=%s", result.ReturnCode, result.Stderr)
	}
	if !strings.Contains(result.Stdout, "hello world") {
		t.Errorf("expected stdout to contain 'hello world', got %q", result.Stdout)
	}
}

func TestExecShell_WithEnv(t *testing.T) {
	env := &JobEnvelope{
		JobID: "test-2",
		RunID: "run-2",
		Job: JobDef{
			Executor: ExecutorSpec{
				Type:   "shell",
				Script: "echo $MY_VAR",
				Env:    map[string]string{"MY_VAR": "test_value"},
			},
		},
	}
	result := Execute(context.Background(), env, nil, nil)
	if result.ReturnCode != 0 {
		t.Fatalf("expected rc=0, got %d, stderr=%s", result.ReturnCode, result.Stderr)
	}
	if !strings.Contains(result.Stdout, "test_value") {
		t.Errorf("expected stdout to contain 'test_value', got %q", result.Stdout)
	}
}

func TestExecShell_Timeout(t *testing.T) {
	env := &JobEnvelope{
		JobID: "test-3",
		RunID: "run-3",
		Job: JobDef{
			Timeout: 1,
			Executor: ExecutorSpec{
				Type:   "shell",
				Script: "sleep 30",
			},
		},
	}
	result := Execute(context.Background(), env, nil, nil)
	if result.ReturnCode == 0 {
		t.Fatalf("expected non-zero rc for timeout, got 0")
	}
}

func TestExecShell_Failure(t *testing.T) {
	env := &JobEnvelope{
		JobID: "test-4",
		RunID: "run-4",
		Job: JobDef{
			Executor: ExecutorSpec{
				Type:   "shell",
				Script: "exit 42",
			},
		},
	}
	result := Execute(context.Background(), env, nil, nil)
	if result.ReturnCode != 42 {
		t.Errorf("expected rc=42, got %d", result.ReturnCode)
	}
}

func TestExecExternal(t *testing.T) {
	env := &JobEnvelope{
		JobID: "test-5",
		RunID: "run-5",
		Job: JobDef{
			Executor: ExecutorSpec{
				Type:    "external",
				Command: "echo",
				Args:    []string{"hello", "external"},
			},
		},
	}
	result := Execute(context.Background(), env, nil, nil)
	if result.ReturnCode != 0 {
		t.Fatalf("expected rc=0, got %d, stderr=%s", result.ReturnCode, result.Stderr)
	}
	if !strings.Contains(result.Stdout, "hello external") {
		t.Errorf("expected stdout to contain 'hello external', got %q", result.Stdout)
	}
}

func TestExecute_SourceFetchMsPopulatedForSourceJob(t *testing.T) {
	srcDir := t.TempDir()
	if err := os.WriteFile(srcDir+"/hello.txt", []byte("hi"), 0644); err != nil {
		t.Fatalf("failed to seed source dir: %v", err)
	}
	env := &JobEnvelope{
		JobID: "test-source",
		RunID: "run-source",
		Job: JobDef{
			Executor: ExecutorSpec{
				Type:   "shell",
				Script: "cat hello.txt",
			},
			Source: &Source{URL: srcDir, Protocol: "copy"},
		},
	}
	result := Execute(context.Background(), env, nil, nil)
	if result.ReturnCode != 0 {
		t.Fatalf("expected rc=0, got %d, stderr=%s", result.ReturnCode, result.Stderr)
	}
	if result.SourceFetchMs <= 0 {
		t.Errorf("expected SourceFetchMs > 0 for a job with a source, got %v", result.SourceFetchMs)
	}
}

func TestExecute_SourceFetchMsZeroWithoutSource(t *testing.T) {
	env := &JobEnvelope{
		JobID: "test-no-source",
		RunID: "run-no-source",
		Job: JobDef{
			Executor: ExecutorSpec{
				Type:   "shell",
				Script: "echo hi",
			},
		},
	}
	result := Execute(context.Background(), env, nil, nil)
	if result.SourceFetchMs != 0 {
		t.Errorf("expected SourceFetchMs == 0 for a job without a source, got %v", result.SourceFetchMs)
	}
}

func TestExecPython_EnvPrepMsPopulated(t *testing.T) {
	env := &JobEnvelope{
		JobID: "test-python-timing",
		RunID: "run-python-timing",
		Job: JobDef{
			Executor: ExecutorSpec{
				Type: "python",
				Code: "print('hi')",
			},
		},
	}
	result := Execute(context.Background(), env, nil, nil)
	if result.ReturnCode != 0 {
		t.Skipf("skipping: no python interpreter available (rc=%d, stderr=%s)", result.ReturnCode, result.Stderr)
	}
	if result.EnvPrepMs <= 0 {
		t.Errorf("expected EnvPrepMs > 0 for a python job, got %v", result.EnvPrepMs)
	}
}

func TestExecShell_StreamCallbacks(t *testing.T) {
	var stdoutLines []string
	env := &JobEnvelope{
		JobID: "test-6",
		RunID: "run-6",
		Job: JobDef{
			Executor: ExecutorSpec{
				Type:   "shell",
				Script: "echo line1\necho line2\necho line3",
			},
		},
	}
	result := Execute(context.Background(), env,
		func(line string) { stdoutLines = append(stdoutLines, line) },
		nil,
	)
	if result.ReturnCode != 0 {
		t.Fatalf("expected rc=0, got %d", result.ReturnCode)
	}
	if len(stdoutLines) != 3 {
		t.Errorf("expected 3 stdout callback calls, got %d", len(stdoutLines))
	}
}

func TestExecShell_EmptyScript(t *testing.T) {
	env := &JobEnvelope{
		JobID: "test-7",
		RunID: "run-7",
		Job: JobDef{
			Executor: ExecutorSpec{
				Type:   "shell",
				Script: "",
			},
		},
	}
	result := Execute(context.Background(), env, nil, nil)
	if result.ReturnCode != 1 {
		t.Errorf("expected rc=1 for empty script, got %d", result.ReturnCode)
	}
}

func TestExecShell_Params(t *testing.T) {
	env := &JobEnvelope{
		JobID:  "test-8",
		RunID:  "run-8",
		Params: map[string]string{"FOO": "bar"},
		Job: JobDef{
			Executor: ExecutorSpec{
				Type:   "shell",
				Script: "echo $HYDRA_PARAM_FOO",
			},
		},
	}
	result := Execute(context.Background(), env, nil, nil)
	if result.ReturnCode != 0 {
		t.Fatalf("expected rc=0, got %d, stderr=%s", result.ReturnCode, result.Stderr)
	}
	if !strings.Contains(result.Stdout, "bar") {
		t.Errorf("expected stdout to contain 'bar' from param, got %q", result.Stdout)
	}
}

func TestDetectCapabilities(t *testing.T) {
	caps := DetectCapabilities()
	// Should always include shell and external.
	found := make(map[string]bool)
	for _, c := range caps {
		found[c] = true
	}
	if !found["shell"] {
		t.Error("capabilities should include 'shell'")
	}
	if !found["external"] {
		t.Error("capabilities should include 'external'")
	}
}

func TestDetectShells(t *testing.T) {
	shells := DetectShells()
	// On Linux CI, bash should be available.
	found := false
	for _, s := range shells {
		if s == "bash" {
			found = true
		}
	}
	if !found {
		t.Error("DetectShells should find bash on Linux")
	}
}

func TestBuildEnv(t *testing.T) {
	env := buildEnv(
		map[string]string{"A": "1"},
		map[string]string{"B": "2"},
	)
	if env["A"] != "1" {
		t.Errorf("expected A=1, got %q", env["A"])
	}
	if env["HYDRA_PARAM_B"] != "2" {
		t.Errorf("expected HYDRA_PARAM_B=2, got %q", env["HYDRA_PARAM_B"])
	}
}

func TestUnsupportedExecutorType(t *testing.T) {
	env := &JobEnvelope{
		JobID: "test-unsupported",
		RunID: "run-unsupported",
		Job: JobDef{
			Executor: ExecutorSpec{
				Type: "unknown_type",
			},
		},
	}
	result := Execute(context.Background(), env, nil, nil)
	if result.ReturnCode != 1 {
		t.Errorf("expected rc=1 for unsupported type, got %d", result.ReturnCode)
	}
	if !strings.Contains(result.Stderr, "unsupported") {
		t.Errorf("expected stderr to mention unsupported, got %q", result.Stderr)
	}
}

func TestExecSQL_RequiresConnectionURI(t *testing.T) {
	env := &JobEnvelope{
		JobID: "test-sql-1",
		RunID: "run-sql-1",
		Job: JobDef{
			Executor: ExecutorSpec{
				Type:  "sql",
				Query: "SELECT 1",
			},
		},
	}
	result := Execute(context.Background(), env, nil, nil)
	if result.ReturnCode != 1 {
		t.Errorf("expected rc=1 for missing connection_uri, got %d", result.ReturnCode)
	}
	if !strings.Contains(result.Stderr, "connection_uri") {
		t.Errorf("expected stderr to mention connection_uri, got %q", result.Stderr)
	}
}

func TestExecSQL_RequiresQuery(t *testing.T) {
	env := &JobEnvelope{
		JobID: "test-sql-2",
		RunID: "run-sql-2",
		Job: JobDef{
			Executor: ExecutorSpec{
				Type:          "sql",
				ConnectionURI: "postgresql://localhost/test",
				Query:         "",
			},
		},
	}
	result := Execute(context.Background(), env, nil, nil)
	if result.ReturnCode != 1 {
		t.Errorf("expected rc=1 for empty query, got %d", result.ReturnCode)
	}
	if !strings.Contains(result.Stderr, "non-empty query") {
		t.Errorf("expected stderr to mention non-empty query, got %q", result.Stderr)
	}
}

func TestExecHTTP_RequiresURL(t *testing.T) {
	env := &JobEnvelope{
		JobID: "test-http-1",
		RunID: "run-http-1",
		Job: JobDef{
			Executor: ExecutorSpec{
				Type: "http",
				URL:  "",
			},
		},
	}
	result := Execute(context.Background(), env, nil, nil)
	if result.ReturnCode != 1 {
		t.Errorf("expected rc=1 for empty URL, got %d", result.ReturnCode)
	}
	if !strings.Contains(result.Stderr, "url") {
		t.Errorf("expected stderr to mention url, got %q", result.Stderr)
	}
}

func TestExecHTTP_ConnectionRefused(t *testing.T) {
	env := &JobEnvelope{
		JobID: "test-http-2",
		RunID: "run-http-2",
		Job: JobDef{
			Executor: ExecutorSpec{
				Type:           "http",
				URL:            "http://127.0.0.1:1",
				TimeoutSeconds: 2,
			},
		},
	}
	result := Execute(context.Background(), env, nil, nil)
	if result.ReturnCode != 1 {
		t.Errorf("expected rc=1 for connection refused, got %d", result.ReturnCode)
	}
}

func TestWithImpersonation_Empty(t *testing.T) {
	cmd := []string{"echo", "hello"}
	result, err := withImpersonation(cmd, "")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(result) != 2 || result[0] != "echo" {
		t.Errorf("expected unchanged cmd, got %v", result)
	}
}

func TestWithImpersonation_Linux(t *testing.T) {
	if testing.Short() {
		t.Skip("skipping in short mode")
	}
	cmd := []string{"echo", "hello"}
	result, err := withImpersonation(cmd, "testuser")
	if err != nil {
		// On non-Linux/macOS this will error — that's fine
		if strings.Contains(err.Error(), "not supported") {
			t.Skip("impersonation not supported on this OS")
		}
		t.Fatalf("unexpected error: %v", err)
	}
	if result[0] != "sudo" || result[1] != "-n" || result[2] != "-u" || result[3] != "testuser" {
		t.Errorf("expected sudo prefix, got %v", result)
	}
}

func TestDetectCapabilities_IncludesHTTP(t *testing.T) {
	caps := DetectCapabilities()
	found := make(map[string]bool)
	for _, c := range caps {
		found[c] = true
	}
	if !found["http"] {
		t.Error("capabilities should include 'http'")
	}
}

func TestDetectCapabilities_SQLRequiresPythonAndSQLAlchemy(t *testing.T) {
	caps := DetectCapabilities()
	hasPython := false
	hasSQL := false
	for _, c := range caps {
		if c == "python" {
			hasPython = true
		}
		if c == "sql" {
			hasSQL = true
		}
	}
	// SQL should never be advertised without Python.
	if !hasPython && hasSQL {
		t.Error("sql should not be advertised without python")
	}
	// SQL should be advertised iff sqlalchemy actually imports — it's not
	// enough for python to merely be present (that would be a capability lie).
	if hasSQL != sqlalchemyImportable() {
		t.Errorf("hasSQL=%v should match sqlalchemyImportable()=%v", hasSQL, sqlalchemyImportable())
	}
}

func TestDetectCapabilities_SQLExcludedWhenImportFails(t *testing.T) {
	// Point HYDRA_PYTHON_PATH at a fake interpreter that answers "--version"
	// (so findPython() accepts it) but fails "-c import sqlalchemy", to force
	// the import-preflight to fail deterministically regardless of what's
	// actually installed on the host running this test.
	fakePython := writeFakePythonScript(t, false)
	t.Setenv("HYDRA_PYTHON_PATH", fakePython)

	if sqlalchemyImportable() {
		t.Error("expected sqlalchemyImportable() to return false when the import fails")
	}
	caps := DetectCapabilities()
	for _, c := range caps {
		if c == "sql" {
			t.Error("expected 'sql' to be excluded from capabilities when sqlalchemy import fails")
		}
	}
}

func TestDetectCapabilities_SQLIncludedWhenImportSucceeds(t *testing.T) {
	fakePython := writeFakePythonScript(t, true)
	t.Setenv("HYDRA_PYTHON_PATH", fakePython)

	if !sqlalchemyImportable() {
		t.Error("expected sqlalchemyImportable() to return true when the import succeeds")
	}
	caps := DetectCapabilities()
	found := false
	for _, c := range caps {
		if c == "sql" {
			found = true
		}
	}
	if !found {
		t.Error("expected 'sql' to be included in capabilities when sqlalchemy import succeeds")
	}
}

// writeFakePythonScript writes a shell script standing in for a python3
// interpreter: it exits 0 for any "--version" probe (so findPython() accepts
// it), and for an "-c ..." probe it exits 0 if importSucceeds is true, 1
// otherwise — deterministic stand-in for sqlalchemyImportable()'s subprocess
// check without needing a real Python/sqlalchemy install in the test env.
func writeFakePythonScript(t *testing.T, importSucceeds bool) string {
	t.Helper()
	dir := t.TempDir()
	path := dir + "/fake-python3"
	exitCode := "1"
	if importSucceeds {
		exitCode = "0"
	}
	script := "#!/bin/sh\n" +
		"case \"$1\" in\n" +
		"  --version) exit 0;;\n" +
		"  -c) exit " + exitCode + ";;\n" +
		"esac\n" +
		"exit 0\n"
	if err := os.WriteFile(path, []byte(script), 0o755); err != nil {
		t.Fatalf("failed to write fake python script: %v", err)
	}
	return path
}
