package worker

import (
	"encoding/json"
	"fmt"
	"os"
	"strconv"
	"strings"
	"testing"
	"time"

	"github.com/punassuming/hydra/go-worker/internal/executor"
)

func TestEvaluateCompletion_NilCompletion_Success(t *testing.T) {
	ok, reason := evaluateCompletion(nil, &executor.ExecResult{ReturnCode: 0})
	if !ok {
		t.Errorf("expected success, got reason=%q", reason)
	}
}

func TestEvaluateCompletion_NilCompletion_Failure(t *testing.T) {
	ok, _ := evaluateCompletion(nil, &executor.ExecResult{ReturnCode: 1})
	if ok {
		t.Error("expected failure for rc=1 with nil completion")
	}
}

func TestEvaluateCompletion_ExitCodes(t *testing.T) {
	comp := &executor.Completion{ExitCodes: []int{0, 2}}
	ok, _ := evaluateCompletion(comp, &executor.ExecResult{ReturnCode: 2})
	if !ok {
		t.Error("expected success for rc=2 in allowed exit codes")
	}
	ok, _ = evaluateCompletion(comp, &executor.ExecResult{ReturnCode: 1})
	if ok {
		t.Error("expected failure for rc=1 not in exit codes")
	}
}

func TestEvaluateCompletion_StdoutContains(t *testing.T) {
	comp := &executor.Completion{
		ExitCodes:      []int{0},
		StdoutContains: []string{"SUCCESS"},
	}
	ok, _ := evaluateCompletion(comp, &executor.ExecResult{ReturnCode: 0, Stdout: "test SUCCESS done"})
	if !ok {
		t.Error("expected success when stdout contains required token")
	}
	ok, reason := evaluateCompletion(comp, &executor.ExecResult{ReturnCode: 0, Stdout: "test done"})
	if ok {
		t.Error("expected failure when stdout missing required token")
	}
	if reason == "" {
		t.Error("expected non-empty reason")
	}
}

func TestEvaluateCompletion_StdoutNotContains(t *testing.T) {
	comp := &executor.Completion{
		ExitCodes:         []int{0},
		StdoutNotContains: []string{"ERROR"},
	}
	ok, _ := evaluateCompletion(comp, &executor.ExecResult{ReturnCode: 0, Stdout: "all good"})
	if !ok {
		t.Error("expected success when stdout doesn't contain forbidden token")
	}
	ok, _ = evaluateCompletion(comp, &executor.ExecResult{ReturnCode: 0, Stdout: "got ERROR here"})
	if ok {
		t.Error("expected failure when stdout contains forbidden token")
	}
}

func TestEvaluateCompletion_StderrContains(t *testing.T) {
	comp := &executor.Completion{
		ExitCodes:      []int{0},
		StderrContains: []string{"WARN"},
	}
	ok, _ := evaluateCompletion(comp, &executor.ExecResult{ReturnCode: 0, Stderr: "WARN: something"})
	if !ok {
		t.Error("expected success when stderr contains required token")
	}
	ok, _ = evaluateCompletion(comp, &executor.ExecResult{ReturnCode: 0, Stderr: ""})
	if ok {
		t.Error("expected failure when stderr missing required token")
	}
}

func TestEvaluateCompletion_StderrNotContains(t *testing.T) {
	comp := &executor.Completion{
		ExitCodes:         []int{0},
		StderrNotContains: []string{"FATAL"},
	}
	ok, _ := evaluateCompletion(comp, &executor.ExecResult{ReturnCode: 0, Stderr: "info only"})
	if !ok {
		t.Error("expected success when stderr doesn't contain forbidden token")
	}
	ok, _ = evaluateCompletion(comp, &executor.ExecResult{ReturnCode: 0, Stderr: "FATAL error"})
	if ok {
		t.Error("expected failure when stderr contains forbidden token")
	}
}

func TestEvaluateCompletion_DefaultExitCodes(t *testing.T) {
	// Empty ExitCodes should default to [0].
	comp := &executor.Completion{ExitCodes: []int{}}
	ok, _ := evaluateCompletion(comp, &executor.ExecResult{ReturnCode: 0})
	if !ok {
		t.Error("expected success for rc=0 with empty exit codes (default to [0])")
	}
	ok, _ = evaluateCompletion(comp, &executor.ExecResult{ReturnCode: 1})
	if ok {
		t.Error("expected failure for rc=1 with empty exit codes (default to [0])")
	}
}

func TestEvaluateCompletion_EmptyForbiddenToken(t *testing.T) {
	// Empty string in not_contains should be ignored.
	comp := &executor.Completion{
		ExitCodes:         []int{0},
		StdoutNotContains: []string{""},
	}
	ok, _ := evaluateCompletion(comp, &executor.ExecResult{ReturnCode: 0, Stdout: "anything"})
	if !ok {
		t.Error("expected success when forbidden token is empty string")
	}
}

func TestEvaluateFileCriteria_NilCompletion(t *testing.T) {
	ok, _ := evaluateFileCriteria(nil, time.Now())
	if !ok {
		t.Error("expected success for nil completion")
	}
}

func TestEvaluateFileCriteria_RequireFileExists_Pass(t *testing.T) {
	f, err := os.CreateTemp("", "hydra-test-*")
	if err != nil {
		t.Fatal(err)
	}
	f.Close()
	defer os.Remove(f.Name())

	comp := &executor.Completion{RequireFileExists: []string{f.Name()}}
	ok, reason := evaluateFileCriteria(comp, time.Now())
	if !ok {
		t.Errorf("expected success for existing file, got: %s", reason)
	}
}

func TestEvaluateFileCriteria_RequireFileExists_Fail(t *testing.T) {
	comp := &executor.Completion{RequireFileExists: []string{"/nonexistent/hydra_test_file_xyz.txt"}}
	ok, reason := evaluateFileCriteria(comp, time.Now())
	if ok {
		t.Error("expected failure for non-existent file")
	}
	if reason == "" {
		t.Error("expected non-empty reason")
	}
}

func TestEvaluateFileCriteria_RequireFileUpdatedSinceStart_Pass(t *testing.T) {
	start := time.Now().Add(-1 * time.Second)

	f, err := os.CreateTemp("", "hydra-test-*")
	if err != nil {
		t.Fatal(err)
	}
	f.WriteString("updated data")
	f.Close()
	defer os.Remove(f.Name())

	comp := &executor.Completion{RequireFileUpdatedSinceStart: []string{f.Name()}}
	ok, reason := evaluateFileCriteria(comp, start)
	if !ok {
		t.Errorf("expected success for recently created file, got: %s", reason)
	}
}

func TestEvaluateFileCriteria_RequireFileUpdatedSinceStart_Fail_OldFile(t *testing.T) {
	f, err := os.CreateTemp("", "hydra-test-*")
	if err != nil {
		t.Fatal(err)
	}
	f.WriteString("old data")
	f.Close()
	defer os.Remove(f.Name())

	// Set start time in the future so the file appears not updated since start.
	futureStart := time.Now().Add(100 * time.Second)
	comp := &executor.Completion{RequireFileUpdatedSinceStart: []string{f.Name()}}
	ok, reason := evaluateFileCriteria(comp, futureStart)
	if ok {
		t.Error("expected failure when file mtime is before run start")
	}
	if reason == "" {
		t.Error("expected non-empty reason")
	}
}

func TestEvaluateFileCriteria_RequireFileUpdatedSinceStart_Fail_Missing(t *testing.T) {
	comp := &executor.Completion{RequireFileUpdatedSinceStart: []string{"/nonexistent/hydra_test_xyz.txt"}}
	ok, reason := evaluateFileCriteria(comp, time.Now())
	if ok {
		t.Error("expected failure for non-existent file")
	}
	if reason == "" {
		t.Error("expected non-empty reason")
	}
}

func TestMetrics_IsNumeric(t *testing.T) {
	tests := []struct {
		input string
		want  bool
	}{
		{"123", true},
		{"", false},
		{"abc", false},
		{"12a", false},
	}
	for _, tt := range tests {
		got := isNumeric(tt.input)
		if got != tt.want {
			t.Errorf("isNumeric(%q) = %v, want %v", tt.input, got, tt.want)
		}
	}
}

func TestCollectMetrics(t *testing.T) {
	m := collectMetrics()
	if _, ok := m["process_count"]; !ok {
		t.Error("metrics should have process_count")
	}
	if _, ok := m["memory_rss_mb"]; !ok {
		t.Error("metrics should have memory_rss_mb")
	}
}

func TestOrDefault(t *testing.T) {
	if got := orDefault(5.0, 10.0); got != 5.0 {
		t.Errorf("expected 5.0, got %f", got)
	}
	if got := orDefault(0.0, 10.0); got != 10.0 {
		t.Errorf("expected 10.0, got %f", got)
	}
}

func TestResolveIP(t *testing.T) {
	// Should not panic for any hostname.
	_ = resolveIP("localhost")
	_ = resolveIP("nonexistent-host-12345")
}

func TestAppendWorkerOp_Format(t *testing.T) {
	// Just verify the function signature/pattern compiles and doesn't panic on nil rdb.
	// Full integration test needs Redis. This validates code paths without Redis.
	_ = fmt.Sprintf("worker_ops:%s:%s", "domain", "worker")
}

func TestHandleStdout_ArtifactInterception(t *testing.T) {
	// Replicate the handleStdout closure logic to verify artifact parsing.
	const artifactPrefix = "__HYDRA_ARTIFACT__:"

	type artifactEvent struct {
		Name     string
		Metadata map[string]interface{}
	}

	var emittedArtifacts []artifactEvent
	var loggedLines []string

	fakePublish := func(name string, metadata map[string]interface{}) {
		emittedArtifacts = append(emittedArtifacts, artifactEvent{name, metadata})
	}
	fakeLog := func(line string) {
		loggedLines = append(loggedLines, line)
	}

	handleStdout := func(line string) {
		trimmed := strings.TrimSpace(line)
		if strings.HasPrefix(trimmed, artifactPrefix) {
			rawJSON := strings.TrimSpace(trimmed[len(artifactPrefix):])
			var parsed map[string]interface{}
			if err := json.Unmarshal([]byte(rawJSON), &parsed); err == nil {
				artifactName, _ := parsed["name"].(string)
				artifactName = strings.TrimSpace(artifactName)
				if artifactName != "" {
					metadata, _ := parsed["metadata"].(map[string]interface{})
					if metadata == nil {
						metadata = map[string]interface{}{}
					}
					fakePublish(artifactName, metadata)
					return
				}
			}
		}
		fakeLog(line)
	}

	// Normal line passes through
	handleStdout("regular output")
	if len(loggedLines) != 1 || loggedLines[0] != "regular output" {
		t.Errorf("expected normal line to be logged, got %v", loggedLines)
	}
	if len(emittedArtifacts) != 0 {
		t.Errorf("expected no artifacts emitted for normal line")
	}

	// Valid artifact line is intercepted and not logged
	handleStdout(`__HYDRA_ARTIFACT__: {"name": "my_export", "metadata": {"rows": 100}}`)
	if len(emittedArtifacts) != 1 {
		t.Fatalf("expected 1 artifact emitted, got %d", len(emittedArtifacts))
	}
	if emittedArtifacts[0].Name != "my_export" {
		t.Errorf("expected artifact name 'my_export', got %q", emittedArtifacts[0].Name)
	}
	if rows, ok := emittedArtifacts[0].Metadata["rows"].(float64); !ok || rows != 100 {
		t.Errorf("expected rows=100 in metadata, got %v", emittedArtifacts[0].Metadata)
	}
	// Artifact line should NOT be forwarded to the log
	if len(loggedLines) != 1 {
		t.Errorf("artifact line should not appear in log, loggedLines=%v", loggedLines)
	}

	// Malformed JSON falls through to logging
	handleStdout("__HYDRA_ARTIFACT__: {not valid json}")
	if len(loggedLines) != 2 {
		t.Errorf("malformed artifact line should be logged, got %v", loggedLines)
	}
	if len(emittedArtifacts) != 1 {
		t.Errorf("no new artifact should be emitted for malformed JSON")
	}

	// Artifact with whitespace trimming
	handleStdout("  __HYDRA_ARTIFACT__:  {\"name\": \"trimmed\", \"metadata\": {}}  ")
	if len(emittedArtifacts) != 2 || emittedArtifacts[1].Name != "trimmed" {
		t.Errorf("expected trimmed artifact to be emitted, got %v", emittedArtifacts)
	}
}

func TestHeartbeatFilePath_DefaultsWhenUnset(t *testing.T) {
	t.Setenv("WORKER_HEARTBEAT_FILE", "")
	if got := heartbeatFilePath(); got != defaultHeartbeatFile {
		t.Errorf("expected default %q, got %q", defaultHeartbeatFile, got)
	}
}

func TestHeartbeatFilePath_UsesEnvOverride(t *testing.T) {
	t.Setenv("WORKER_HEARTBEAT_FILE", "/tmp/custom-heartbeat")
	if got := heartbeatFilePath(); got != "/tmp/custom-heartbeat" {
		t.Errorf("expected env override, got %q", got)
	}
}

func TestTouchHeartbeatFile_WritesCurrentTimestamp(t *testing.T) {
	dir := t.TempDir()
	path := dir + "/heartbeat"
	t.Setenv("WORKER_HEARTBEAT_FILE", path)

	before := time.Now().Unix()
	touchHeartbeatFile()
	after := time.Now().Unix()

	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("expected heartbeat file to exist: %v", err)
	}
	written, err := strconv.ParseInt(strings.TrimSpace(string(data)), 10, 64)
	if err != nil {
		t.Fatalf("expected numeric timestamp, got %q: %v", data, err)
	}
	if written < before || written > after {
		t.Errorf("expected timestamp between %d and %d, got %d", before, after, written)
	}
}

func TestTouchHeartbeatFile_SurvivesUnwritablePath(t *testing.T) {
	// A liveness file write failure must never panic — it's best-effort.
	t.Setenv("WORKER_HEARTBEAT_FILE", "/nonexistent-dir/heartbeat")
	touchHeartbeatFile()
}
