package executor

import (
	"context"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

func TestCheckHTTPSensor_ConditionMet(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	}))
	defer server.Close()

	spec := &ExecutorSpec{Target: server.URL, PollIntervalSeconds: 5}
	if !checkHTTPSensor(spec) {
		t.Fatal("expected checkHTTPSensor to return true for a 200 response with default expected_status")
	}
}

func TestCheckHTTPSensor_UnexpectedStatus(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusNotFound)
	}))
	defer server.Close()

	spec := &ExecutorSpec{Target: server.URL, ExpectedStatus: []int{200}, PollIntervalSeconds: 5}
	if checkHTTPSensor(spec) {
		t.Fatal("expected checkHTTPSensor to return false for a 404 response when expecting 200")
	}
}

func TestCheckHTTPSensor_EmptyTarget(t *testing.T) {
	if checkHTTPSensor(&ExecutorSpec{}) {
		t.Fatal("expected checkHTTPSensor to return false when target is empty")
	}
}

func TestExecSensor_HTTPConditionMetImmediately(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	}))
	defer server.Close()

	spec := &ExecutorSpec{
		SensorType:          "http",
		Target:              server.URL,
		PollIntervalSeconds: 1,
		TimeoutSeconds:      10,
	}
	result := execSensor(context.Background(), spec, nil)
	if result.ReturnCode != 0 {
		t.Fatalf("expected rc=0, got %d, stderr=%s", result.ReturnCode, result.Stderr)
	}
	if !strings.Contains(result.Stdout, "condition_met") {
		t.Errorf("expected stdout to contain 'condition_met', got %q", result.Stdout)
	}
}

func TestExecSensor_Timeout(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusNotFound)
	}))
	defer server.Close()

	spec := &ExecutorSpec{
		SensorType:          "http",
		Target:              server.URL,
		ExpectedStatus:      []int{200},
		PollIntervalSeconds: 1,
		TimeoutSeconds:      1,
	}
	result := execSensor(context.Background(), spec, nil)
	if result.ReturnCode != exitCodeTimeout {
		t.Fatalf("expected rc=%d (exitCodeTimeout), got %d", exitCodeTimeout, result.ReturnCode)
	}
	if !strings.Contains(result.Stderr, "timed out") {
		t.Errorf("expected stderr to mention 'timed out', got %q", result.Stderr)
	}
}

func TestExecSensor_ContextCancelStopsLoop(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusNotFound)
	}))
	defer server.Close()

	spec := &ExecutorSpec{
		SensorType:          "http",
		Target:              server.URL,
		ExpectedStatus:      []int{200},
		PollIntervalSeconds: 60,
		TimeoutSeconds:      300,
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()

	done := make(chan *ExecResult, 1)
	go func() { done <- execSensor(ctx, spec, nil) }()

	select {
	case result := <-done:
		if result.ReturnCode != exitCodeCanceled {
			t.Fatalf("expected rc=%d (exitCodeCanceled), got %d", exitCodeCanceled, result.ReturnCode)
		}
		if !strings.Contains(result.Stderr, "killed") {
			t.Errorf("expected stderr to mention 'killed', got %q", result.Stderr)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("execSensor did not return promptly after ctx was cancelled")
	}
}

func TestExecSensor_UnknownSensorType(t *testing.T) {
	spec := &ExecutorSpec{
		SensorType:          "unknown_type",
		Target:              "https://example.com",
		PollIntervalSeconds: 1,
		TimeoutSeconds:      5,
	}
	result := execSensor(context.Background(), spec, nil)
	if result.ReturnCode != 1 {
		t.Fatalf("expected rc=1, got %d", result.ReturnCode)
	}
	if !strings.Contains(result.Stderr, "unknown sensor_type") {
		t.Errorf("expected stderr to mention 'unknown sensor_type', got %q", result.Stderr)
	}
}

func TestExecute_DispatchesSensorType(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	}))
	defer server.Close()

	env := &JobEnvelope{
		JobID: "test-sensor",
		RunID: "run-sensor",
		Job: JobDef{
			Executor: ExecutorSpec{
				Type:                "sensor",
				SensorType:          "http",
				Target:              server.URL,
				PollIntervalSeconds: 1,
				TimeoutSeconds:      10,
			},
		},
	}
	result := Execute(context.Background(), env, nil, nil)
	if result.ReturnCode != 0 {
		t.Fatalf("expected rc=0, got %d, stderr=%s", result.ReturnCode, result.Stderr)
	}
}

func TestDetectCapabilities_IncludesSensor(t *testing.T) {
	caps := DetectCapabilities()
	found := false
	for _, c := range caps {
		if c == "sensor" {
			found = true
			break
		}
	}
	if !found {
		t.Errorf("expected DetectCapabilities() to include 'sensor', got %v", caps)
	}
}
