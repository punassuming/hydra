package executor

import (
	"context"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"strings"
	"time"
)

// checkHTTPSensor returns true if the HTTP sensor condition is met (an
// expected status code was received). Mirrors worker/executor.py's
// _check_http_sensor.
func checkHTTPSensor(spec *ExecutorSpec) bool {
	target := strings.TrimSpace(spec.Target)
	if target == "" {
		return false
	}
	method := strings.ToUpper(spec.Method)
	if method == "" {
		method = "GET"
	}
	expectedStatus := spec.ExpectedStatus
	if len(expectedStatus) == 0 {
		expectedStatus = []int{200}
	}
	pollInterval := spec.PollIntervalSeconds
	if pollInterval <= 0 {
		pollInterval = 30
	}
	// Cap per-request timeout well below poll_interval so a slow response
	// does not delay the next interval check.
	requestTimeout := pollInterval
	if requestTimeout > 25 {
		requestTimeout = 25
	}

	var bodyReader io.Reader
	if spec.Body != "" {
		bodyReader = strings.NewReader(spec.Body)
	}
	ctx, cancel := context.WithTimeout(context.Background(), time.Duration(requestTimeout)*time.Second)
	defer cancel()
	req, err := http.NewRequestWithContext(ctx, method, target, bodyReader)
	if err != nil {
		return false
	}
	for k, v := range spec.Headers {
		req.Header.Set(k, v)
	}

	client := &http.Client{Timeout: time.Duration(requestTimeout) * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return false
	}
	defer resp.Body.Close()
	_, _ = io.Copy(io.Discard, resp.Body)

	for _, code := range expectedStatus {
		if resp.StatusCode == code {
			return true
		}
	}
	return false
}

// checkSQLSensor returns true if the SQL sensor condition is met (the query
// returns at least one row). Mirrors worker/executor.py's _check_sql_sensor
// — like the SQL executor (execSQL), this bridges through a Python
// interpreter since Go has no native driver for these dialects.
func checkSQLSensor(spec *ExecutorSpec) bool {
	connURI := strings.TrimSpace(spec.ConnectionURI)
	if connURI == "" {
		return false
	}
	query := strings.TrimSpace(spec.Target)
	if query == "" {
		return false
	}
	dialect := spec.Dialect
	if dialect == "" {
		dialect = "postgres"
	}

	python := findPython()
	if python == "" {
		return false
	}

	var script string
	if dialect == "mongodb" {
		script = fmt.Sprintf(
			"import sys\n"+
				"try:\n"+
				"    from pymongo import MongoClient\n"+
				"    client = MongoClient(%q, serverSelectionTimeoutMS=5000)\n"+
				"    db = client.get_default_database()\n"+
				"    result = db.command(%q)\n"+
				"    sys.exit(0 if result else 1)\n"+
				"except Exception:\n"+
				"    sys.exit(1)\n",
			connURI, query,
		)
	} else {
		script = fmt.Sprintf(
			"import sys\n"+
				"try:\n"+
				"    import sqlalchemy\n"+
				"    engine = sqlalchemy.create_engine(%q, pool_pre_ping=True)\n"+
				"    with engine.connect() as conn:\n"+
				"        result = conn.execute(sqlalchemy.text(%q))\n"+
				"        row = result.fetchone()\n"+
				"        sys.exit(0 if row is not None else 1)\n"+
				"except Exception:\n"+
				"    sys.exit(1)\n",
			connURI, query,
		)
	}

	tmp, err := writeTempFile("hydra-sensor-sql-", ".py", script)
	if err != nil {
		return false
	}
	defer os.Remove(tmp)

	return exec.Command(python, tmp).Run() == nil
}

// execSensor executes a sensor job: poll until the condition is met or the
// overall timeout expires. Mirrors worker/executor.py's _execute_sensor —
// the poll loop runs on the worker, keeping the scheduler free from direct
// external polling. ctx cancellation (job-kill) is honored the same way the
// rest of this package's executors honor it.
func execSensor(ctx context.Context, spec *ExecutorSpec, onStdout func(string)) *ExecResult {
	sensorType := spec.SensorType
	if sensorType == "" {
		sensorType = "http"
	}
	pollInterval := spec.PollIntervalSeconds
	if pollInterval <= 0 {
		pollInterval = 30
	}
	timeoutSeconds := spec.TimeoutSeconds
	if timeoutSeconds <= 0 {
		timeoutSeconds = 3600
	}
	start := time.Now()

	for {
		select {
		case <-ctx.Done():
			return &ExecResult{ReturnCode: exitCodeCanceled, Stderr: "sensor run killed"}
		default:
		}

		elapsed := time.Since(start)
		if elapsed.Seconds() >= float64(timeoutSeconds) {
			return &ExecResult{ReturnCode: exitCodeTimeout, Stderr: fmt.Sprintf("sensor timed out after %.1fs", elapsed.Seconds())}
		}

		var met bool
		switch sensorType {
		case "http":
			met = checkHTTPSensor(spec)
		case "sql":
			met = checkSQLSensor(spec)
		default:
			return &ExecResult{ReturnCode: 1, Stderr: fmt.Sprintf("unknown sensor_type '%s'", sensorType)}
		}

		if met {
			msg := fmt.Sprintf("condition_met after %.1fs", time.Since(start).Seconds())
			if onStdout != nil {
				onStdout(msg)
			}
			return &ExecResult{ReturnCode: 0, Stdout: msg}
		}

		// Wait out the poll interval in small increments so we can react to
		// ctx cancellation and the overall timeout without excess latency.
		waitEnd := time.Now().Add(time.Duration(pollInterval) * time.Second)
		for time.Now().Before(waitEnd) {
			if time.Since(start).Seconds() >= float64(timeoutSeconds) {
				break
			}
			sleepFor := time.Second
			if remaining := time.Until(waitEnd); remaining < sleepFor {
				sleepFor = remaining
			}
			if sleepFor <= 0 {
				break
			}
			timer := time.NewTimer(sleepFor)
			select {
			case <-ctx.Done():
				timer.Stop()
				return &ExecResult{ReturnCode: exitCodeCanceled, Stderr: "sensor run killed"}
			case <-timer.C:
			}
		}
	}
}
