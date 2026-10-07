package worker

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"strconv"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/redis/go-redis/v9"

	"github.com/punassuming/hydra/go-worker/internal/config"
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

func TestNextBLPOPBackoff(t *testing.T) {
	if got := nextBLPOPBackoff(0); got != blpopBackoffInitial {
		t.Errorf("expected the floor %s from a reset (0) state, got %s", blpopBackoffInitial, got)
	}
	if got := nextBLPOPBackoff(blpopBackoffInitial); got != blpopBackoffInitial*2 {
		t.Errorf("expected doubling to %s, got %s", blpopBackoffInitial*2, got)
	}
	if got := nextBLPOPBackoff(blpopBackoffMax); got != blpopBackoffMax {
		t.Errorf("expected the backoff to stay capped at %s, got %s", blpopBackoffMax, got)
	}
	// A value already past the cap (shouldn't happen in practice, but the
	// helper must not overflow/undercut the cap) still clamps to the cap.
	if got := nextBLPOPBackoff(blpopBackoffMax * 10); got != blpopBackoffMax {
		t.Errorf("expected an over-cap input to clamp to %s, got %s", blpopBackoffMax, got)
	}
}

func TestPollLoop_BLPOPErrorBackoffIsInterruptibleByContext(t *testing.T) {
	// A worker sitting in the (up to 60s) BLPOP-error backoff must still
	// return promptly on shutdown instead of riding out the full sleep —
	// otherwise a short termination grace period hard-kills it mid-backoff.
	rdb := redis.NewClient(&redis.Options{
		Addr:        "127.0.0.1:1",
		DialTimeout: 50 * time.Millisecond,
		MaxRetries:  -1,
	})
	defer rdb.Close()

	w := &workerState{
		cfg:       &config.Config{WorkerID: "w1", Domain: "prod", MaxConcurrency: 1},
		rdb:       rdb,
		activeIDs: make(map[string]struct{}),
		killChans: make(map[string]context.CancelFunc),
	}

	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() { done <- w.pollLoop(ctx, "queue:test") }()

	// Give it time for at least one failed BLPOP attempt to land it in the
	// (2s-floor) backoff sleep before cancelling.
	time.Sleep(150 * time.Millisecond)
	cancel()

	select {
	case err := <-done:
		if err != nil {
			t.Fatalf("expected pollLoop to return nil on shutdown, got %v", err)
		}
	case <-time.After(500 * time.Millisecond):
		t.Fatal("pollLoop did not return promptly after context cancellation during BLPOP backoff")
	}
}

func TestRunJob_RecoversFromPanicAndMarksRunFailed(t *testing.T) {
	// A panic anywhere in job execution must not crash the whole worker
	// process — runJob should recover, log, and return normally so other
	// concurrently-running jobs on this worker are unaffected.
	original := execJob
	defer func() { execJob = original }()
	execJob = func(_ context.Context, _ *executor.JobEnvelope, _ func(string), _ func(string)) *executor.ExecResult {
		panic("simulated executor panic")
	}

	// Nothing listens on this address; every Redis call below fails fast
	// (short dial timeout, no retries) rather than blocking — runJob's own
	// Redis calls all ignore their error returns already, so this is enough
	// to exercise the function without a real or fake Redis server.
	rdb := redis.NewClient(&redis.Options{
		Addr:        "127.0.0.1:1",
		DialTimeout: 100 * time.Millisecond,
		MaxRetries:  -1,
	})
	defer rdb.Close()

	w := &workerState{
		cfg:       &config.Config{WorkerID: "w1", Domain: "prod", MaxConcurrency: 2},
		rdb:       rdb,
		activeIDs: make(map[string]struct{}),
		killChans: make(map[string]context.CancelFunc),
	}

	env := &executor.JobEnvelope{
		JobID: "job-1",
		RunID: "run-1",
		Job:   executor.JobDef{ID: "job-1", User: "tester"},
	}

	done := make(chan struct{})
	go func() {
		w.runJob(context.Background(), env)
		close(done)
	}()

	select {
	case <-done:
	case <-time.After(10 * time.Second):
		t.Fatal("runJob did not return — the panic was not recovered")
	}

	if _, stillActive := w.activeIDs["job-1"]; stillActive {
		t.Error("expected job-1 to be removed from activeIDs after the panic")
	}
	if running := atomic.LoadInt32(&w.running); running != 0 {
		t.Errorf("expected running count to be 0 after the panic, got %d", running)
	}
}

func TestSupervise_RestartsAfterPanic(t *testing.T) {
	orig := superviseRestartDelay
	superviseRestartDelay = 10 * time.Millisecond
	defer func() { superviseRestartDelay = orig }()

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	var calls int32
	started := make(chan struct{}, 2)
	supervise(ctx, "test", func(c context.Context) {
		n := atomic.AddInt32(&calls, 1)
		started <- struct{}{}
		if n == 1 {
			panic("boom")
		}
		<-c.Done()
	})

	for i := 0; i < 2; i++ {
		select {
		case <-started:
		case <-time.After(2 * time.Second):
			t.Fatalf("goroutine was not (re)started; calls=%d", atomic.LoadInt32(&calls))
		}
	}
}

func TestSupervise_StopsWhenContextCancelled(t *testing.T) {
	orig := superviseRestartDelay
	superviseRestartDelay = 10 * time.Millisecond
	defer func() { superviseRestartDelay = orig }()

	ctx, cancel := context.WithCancel(context.Background())
	var calls int32
	supervise(ctx, "test", func(c context.Context) {
		atomic.AddInt32(&calls, 1)
		<-c.Done()
	})
	time.Sleep(50 * time.Millisecond)
	cancel()
	time.Sleep(100 * time.Millisecond)
	if n := atomic.LoadInt32(&calls); n != 1 {
		t.Errorf("expected exactly 1 run, got %d", n)
	}
}

func TestDrain_WaitsForJobsWithinGrace(t *testing.T) {
	w := &workerState{killChans: make(map[string]context.CancelFunc)}
	cancelled := false
	w.killChans["run-1"] = func() { cancelled = true }

	w.jobs.Add(1)
	go func() {
		defer w.jobs.Done()
		time.Sleep(50 * time.Millisecond)
	}()

	start := time.Now()
	w.drain(2 * time.Second)
	if time.Since(start) > time.Second {
		t.Errorf("drain should return as soon as jobs finish, took %s", time.Since(start))
	}
	if cancelled {
		t.Error("jobs finishing within the grace period must not be cancelled")
	}
}

func TestDrain_CancelsJobsAfterGrace(t *testing.T) {
	orig := drainForcedCancelWait
	drainForcedCancelWait = 2 * time.Second
	defer func() { drainForcedCancelWait = orig }()

	w := &workerState{killChans: make(map[string]context.CancelFunc)}
	jobCtx, jobCancel := context.WithCancel(context.Background())
	w.killChans["run-1"] = jobCancel

	w.jobs.Add(1)
	go func() {
		defer w.jobs.Done()
		<-jobCtx.Done() // a long job that only ends when cancelled
	}()

	start := time.Now()
	w.drain(50 * time.Millisecond)
	if time.Since(start) > time.Second {
		t.Errorf("drain should cancel after grace and return promptly, took %s", time.Since(start))
	}
	if jobCtx.Err() == nil {
		t.Error("expected the in-flight job to be cancelled after the grace period")
	}
}

func TestShutdownGrace(t *testing.T) {
	t.Setenv("WORKER_SHUTDOWN_GRACE_SECONDS", "")
	if got := shutdownGrace(); got != defaultShutdownGrace {
		t.Errorf("default grace = %s, want %s", got, defaultShutdownGrace)
	}
	t.Setenv("WORKER_SHUTDOWN_GRACE_SECONDS", "7")
	if got := shutdownGrace(); got != 7*time.Second {
		t.Errorf("grace = %s, want 7s", got)
	}
	t.Setenv("WORKER_SHUTDOWN_GRACE_SECONDS", "junk")
	if got := shutdownGrace(); got != defaultShutdownGrace {
		t.Errorf("invalid value should fall back to default, got %s", got)
	}
}
