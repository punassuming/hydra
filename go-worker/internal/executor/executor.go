// Package executor implements the job execution engine for the Go worker,
// supporting shell, external, batch, python, powershell, sql, and http executor types.
package executor

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"sync"
	"time"

	"github.com/punassuming/hydra/go-worker/internal/source"
)

// ---------------------------------------------------------------------------
// Data model — matches the JSON envelope dispatched by the scheduler.
// ---------------------------------------------------------------------------

// Schedule holds cron/interval scheduling metadata.
type Schedule struct {
	Mode      string  `json:"mode"`
	NextRunAt *string `json:"next_run_at"`
	Cron      string  `json:"cron,omitempty"`
	Interval  int     `json:"interval,omitempty"`
}

// Completion defines success/failure criteria for a run.
type Completion struct {
	ExitCodes                    []int    `json:"exit_codes"`
	StdoutContains               []string `json:"stdout_contains"`
	StdoutNotContains            []string `json:"stdout_not_contains"`
	StderrContains               []string `json:"stderr_contains"`
	StderrNotContains            []string `json:"stderr_not_contains"`
	RequireFileExists            []string `json:"require_file_exists"`
	RequireFileUpdatedSinceStart []string `json:"require_file_updated_since_start"`
}

// Source describes a git (or other) source to fetch before execution.
type Source struct {
	URL      string `json:"url,omitempty"`
	Ref      string `json:"ref,omitempty"`
	Path     string `json:"path,omitempty"`
	Token    string `json:"token,omitempty"`
	Protocol string `json:"protocol,omitempty"`
	Sparse   bool   `json:"sparse,omitempty"`
}

// ExecutorSpec holds the executor configuration from the job definition.
type ExecutorSpec struct {
	Type        string            `json:"type"`
	Script      string            `json:"script,omitempty"`
	Shell       string            `json:"shell,omitempty"`
	Env         map[string]string `json:"env,omitempty"`
	Workdir     string            `json:"workdir,omitempty"`
	Args        []string          `json:"args,omitempty"`
	Command     string            `json:"command,omitempty"`
	Code        string            `json:"code,omitempty"`
	Interpreter string            `json:"interpreter,omitempty"`
	// SQL executor fields
	Dialect       string `json:"dialect,omitempty"`
	ConnectionURI string `json:"connection_uri,omitempty"`
	Query         string `json:"query,omitempty"`
	Database      string `json:"database,omitempty"`
	MaxRows       int    `json:"max_rows,omitempty"`
	Autocommit    *bool  `json:"autocommit,omitempty"`
	// HTTP executor fields
	Method         string            `json:"method,omitempty"`
	URL            string            `json:"url,omitempty"`
	Headers        map[string]string `json:"headers,omitempty"`
	Body           string            `json:"body,omitempty"`
	ExpectedStatus []int             `json:"expected_status,omitempty"`
	TimeoutSeconds int               `json:"timeout_seconds,omitempty"`
	// Impersonation / Kerberos
	ImpersonateUser string            `json:"impersonate_user,omitempty"`
	Kerberos        map[string]string `json:"kerberos,omitempty"`
	// Sensor executor fields
	SensorType          string `json:"sensor_type,omitempty"`
	Target              string `json:"target,omitempty"`
	PollIntervalSeconds int    `json:"poll_interval_seconds,omitempty"`
}

// JobDef is the full job definition nested inside the envelope.
type JobDef struct {
	ID                 string       `json:"_id"`
	User               string       `json:"user,omitempty"`
	Executor           ExecutorSpec `json:"executor"`
	Timeout            int          `json:"timeout,omitempty"`
	Retries            int          `json:"retries,omitempty"`
	BypassConcurrency  bool         `json:"bypass_concurrency,omitempty"`
	Schedule           *Schedule    `json:"schedule,omitempty"`
	Completion         *Completion  `json:"completion,omitempty"`
	Source             *Source      `json:"source,omitempty"`
}

// JobEnvelope is the top-level payload dispatched by the scheduler.
type JobEnvelope struct {
	JobID        string            `json:"job_id"`
	RunID        string            `json:"run_id"`
	DispatchTS   float64           `json:"dispatch_ts"`
	EnqueuedTS   float64           `json:"enqueued_ts"`
	RetryAttempt int               `json:"retry_attempt"`
	Params       map[string]string `json:"params,omitempty"`
	Job          JobDef            `json:"job"`
}

// ExecResult carries the outcome of a job execution.
type ExecResult struct {
	ReturnCode int
	Stdout     string
	Stderr     string
	// SourceFetchMs and EnvPrepMs are populated by Execute/execPython when
	// applicable, mirroring the Python worker's run_end timing fields
	// (timings["source_fetch_ms"]/["env_prep_ms"] in worker/executor.py).
	// Zero when the corresponding step didn't run for this job.
	SourceFetchMs float64
	EnvPrepMs     float64
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

// Execute runs the job described by env. Stdout/stderr lines are streamed to
// the optional callback functions as they are produced.
func Execute(ctx context.Context, env *JobEnvelope, onStdout, onStderr func(string)) *ExecResult {
	spec := &env.Job.Executor
	execType := strings.ToLower(strings.TrimSpace(spec.Type))
	if execType == "" {
		execType = "shell"
	}

	// Sensor executor: delegate entirely to the polling loop, before any of
	// the source-fetch/impersonation/job-timeout machinery below. A sensor
	// job manages its own bounded loop via timeout_seconds, not the generic
	// job-level timeout, mirroring worker/executor.py's early dispatch
	// (execute_job returns _execute_sensor(...) before touching source
	// fetch, env prep, or the per-command timeout).
	if execType == "sensor" {
		return execSensor(ctx, spec, onStdout)
	}

	// Build merged environment: OS env + executor env + params.
	mergedEnv := buildEnv(spec.Env, env.Params)
	workdir := spec.Workdir
	args := spec.Args

	// Impersonation / Kerberos
	impersonateUser := strings.TrimSpace(spec.ImpersonateUser)
	kerberos := spec.Kerberos

	if (impersonateUser != "" || len(kerberos) > 0) && runtime.GOOS != "linux" && runtime.GOOS != "darwin" {
		return &ExecResult{ReturnCode: 1, Stderr: fmt.Sprintf("impersonation/kerberos not supported on %s", runtime.GOOS)}
	}

	// Kerberos bootstrap
	if len(kerberos) > 0 && kerberos["principal"] != "" && kerberos["keytab"] != "" {
		if cc := kerberos["ccache"]; cc != "" {
			mergedEnv["KRB5CCNAME"] = cc
		}
		if err := kerberosInit(ctx, kerberos, impersonateUser, mergedEnv); err != nil {
			return &ExecResult{ReturnCode: 1, Stderr: err.Error()}
		}
	}

	// Apply job-level timeout via context.
	if env.Job.Timeout > 0 {
		var cancel context.CancelFunc
		ctx, cancel = context.WithTimeout(ctx, time.Duration(env.Job.Timeout)*time.Second)
		defer cancel()
	}

	// Source fetching (git/copy/rsync).
	var sourceFetchMs float64
	hadSource := false
	if src := env.Job.Source; src != nil && src.URL != "" {
		hadSource = true
		fetchStart := time.Now()
		jobID := env.JobID
		if jobID == "" {
			jobID = env.Job.ID
		}
		tmpDir, err := os.MkdirTemp(tempDir(), fmt.Sprintf("hydra-source-%s-", jobID))
		if err != nil {
			return &ExecResult{ReturnCode: 1, Stderr: fmt.Sprintf("failed to create source temp dir: %v", err)}
		}
		defer os.RemoveAll(tmpDir)

		protocol := src.Protocol
		if protocol == "" {
			protocol = "git"
		}
		var fetchErr error
		switch protocol {
		case "copy":
			fetchErr = source.FetchCopy(src.URL, tmpDir)
		case "rsync":
			fetchErr = source.FetchRsync(src.URL, tmpDir, src.Token)
		default:
			sparsePath := ""
			if src.Sparse {
				sparsePath = src.Path
			}
			fetchErr = source.FetchGit(src.URL, src.Ref, tmpDir, src.Token, sparsePath)
		}
		if fetchErr != nil {
			return &ExecResult{ReturnCode: 1, Stderr: fmt.Sprintf("failed to fetch source: %v", fetchErr)}
		}

		basePath := tmpDir
		if src.Path != "" {
			basePath = filepath.Join(basePath, src.Path)
		}
		if workdir != "" {
			if filepath.IsAbs(workdir) {
				workdir = filepath.Join(basePath, strings.TrimLeft(workdir, "/\\"))
			} else {
				workdir = filepath.Join(basePath, workdir)
			}
		} else {
			workdir = basePath
		}
		sourceFetchMs = float64(time.Since(fetchStart).Microseconds()) / 1000.0
	}

	var result *ExecResult
	switch execType {
	case "shell":
		result = execShell(ctx, spec, args, mergedEnv, workdir, impersonateUser, onStdout, onStderr)
	case "external":
		result = execExternal(ctx, spec, args, mergedEnv, workdir, impersonateUser, onStdout, onStderr)
	case "batch":
		result = execBatch(ctx, spec, args, mergedEnv, workdir, onStdout, onStderr)
	case "python":
		result = execPython(ctx, spec, args, mergedEnv, workdir, impersonateUser, onStdout, onStderr)
	case "powershell":
		result = execPowershell(ctx, spec, args, mergedEnv, workdir, impersonateUser, onStdout, onStderr)
	case "sql":
		result = execSQL(ctx, spec, mergedEnv, onStdout, onStderr)
	case "http":
		result = execHTTP(ctx, spec, onStdout, onStderr)
	default:
		result = &ExecResult{ReturnCode: 1, Stderr: fmt.Sprintf("unsupported executor type: %s", execType)}
	}
	if hadSource {
		result.SourceFetchMs = sourceFetchMs
	}
	return result
}

// ---------------------------------------------------------------------------
// Executor type handlers
// ---------------------------------------------------------------------------

func execShell(ctx context.Context, spec *ExecutorSpec, args []string, env map[string]string, workdir, impersonateUser string, onStdout, onStderr func(string)) *ExecResult {
	script := spec.Script
	if script == "" {
		return &ExecResult{ReturnCode: 1, Stderr: "shell executor requires a non-empty script"}
	}

	shell := spec.Shell
	if shell == "" {
		shell = "bash"
	}

	tmp, err := writeTempFile("hydra-sh-", ".sh", script)
	if err != nil {
		return &ExecResult{ReturnCode: 1, Stderr: fmt.Sprintf("failed to write temp script: %v", err)}
	}
	defer os.Remove(tmp)

	var cmd []string
	if shell == "bash" {
		bashPath := strings.TrimSpace(os.Getenv("HYDRA_SHELL_PATH"))
		if bashPath == "" {
			bashPath = "/bin/bash"
		}
		cmd = append([]string{bashPath, "-l", tmp}, args...)
	} else {
		cmd = append([]string{shell, tmp}, args...)
	}
	cmd, impErr := withImpersonation(cmd, impersonateUser)
	if impErr != nil {
		return &ExecResult{ReturnCode: 1, Stderr: impErr.Error()}
	}
	return runCommand(ctx, cmd, env, workdir, onStdout, onStderr)
}

func execExternal(ctx context.Context, spec *ExecutorSpec, args []string, env map[string]string, workdir, impersonateUser string, onStdout, onStderr func(string)) *ExecResult {
	binary := spec.Command
	if binary == "" {
		return &ExecResult{ReturnCode: 1, Stderr: "external executor requires a non-empty command"}
	}
	cmd := append([]string{binary}, args...)
	cmd, impErr := withImpersonation(cmd, impersonateUser)
	if impErr != nil {
		return &ExecResult{ReturnCode: 1, Stderr: impErr.Error()}
	}
	return runCommand(ctx, cmd, env, workdir, onStdout, onStderr)
}

func execBatch(ctx context.Context, spec *ExecutorSpec, args []string, env map[string]string, workdir string, onStdout, onStderr func(string)) *ExecResult {
	script := spec.Script
	if script == "" {
		return &ExecResult{ReturnCode: 1, Stderr: "batch executor requires a non-empty script"}
	}

	shell := spec.Shell
	if shell == "" {
		shell = "cmd"
	}

	suffix := ".sh"
	if shell == "cmd" {
		suffix = ".bat"
	}

	tmp, err := writeTempFile("hydra-batch-", suffix, script)
	if err != nil {
		return &ExecResult{ReturnCode: 1, Stderr: fmt.Sprintf("failed to write temp script: %v", err)}
	}
	defer os.Remove(tmp)

	var cmd []string
	if shell == "cmd" {
		cmd = append([]string{"cmd", "/c", tmp}, args...)
	} else {
		cmd = append([]string{shell, tmp}, args...)
	}
	return runCommand(ctx, cmd, env, workdir, onStdout, onStderr)
}

func execPython(ctx context.Context, spec *ExecutorSpec, args []string, env map[string]string, workdir, impersonateUser string, onStdout, onStderr func(string)) *ExecResult {
	envPrepStart := time.Now()
	code := spec.Code
	if code == "" {
		return &ExecResult{ReturnCode: 1, Stderr: "python executor requires non-empty code"}
	}

	interpreter := spec.Interpreter
	if interpreter == "" {
		interpreter = findPython()
		if interpreter == "" {
			return &ExecResult{ReturnCode: 1, Stderr: "no python interpreter found (tried python3, python)"}
		}
	}

	tmp, err := writeTempFile("hydra-py-", ".py", code)
	if err != nil {
		return &ExecResult{ReturnCode: 1, Stderr: fmt.Sprintf("failed to write temp script: %v", err)}
	}
	defer os.Remove(tmp)

	cmd := append([]string{interpreter, tmp}, args...)
	cmd, impErr := withImpersonation(cmd, impersonateUser)
	if impErr != nil {
		return &ExecResult{ReturnCode: 1, Stderr: impErr.Error()}
	}
	// env_prep_ms covers interpreter resolution + temp-file setup, mirroring
	// worker/executor.py's timings["env_prep_ms"] (Python's venv/interpreter
	// prep step) — measured up to but not including the actual run.
	envPrepMs := float64(time.Since(envPrepStart).Microseconds()) / 1000.0
	result := runCommand(ctx, cmd, env, workdir, onStdout, onStderr)
	result.EnvPrepMs = envPrepMs
	return result
}

func execPowershell(ctx context.Context, spec *ExecutorSpec, args []string, env map[string]string, workdir, impersonateUser string, onStdout, onStderr func(string)) *ExecResult {
	script := spec.Script
	if script == "" {
		return &ExecResult{ReturnCode: 1, Stderr: "powershell executor requires a non-empty script"}
	}

	shell := spec.Shell
	if shell == "" {
		shell = "pwsh"
	}

	cmd := append([]string{shell, "-NoProfile", "-Command", script}, args...)
	cmd, impErr := withImpersonation(cmd, impersonateUser)
	if impErr != nil {
		return &ExecResult{ReturnCode: 1, Stderr: impErr.Error()}
	}
	return runCommand(ctx, cmd, env, workdir, onStdout, onStderr)
}

// execSQL executes a SQL query by generating and running a small Python driver
// script (matching the Python worker strategy). The Go worker uses Python as
// the SQL execution bridge to avoid compiling heavy native DB drivers.
func execSQL(ctx context.Context, spec *ExecutorSpec, env map[string]string, onStdout, onStderr func(string)) *ExecResult {
	connURI := spec.ConnectionURI
	if connURI == "" {
		return &ExecResult{ReturnCode: 1, Stderr: "sql executor requires connection_uri or credential_ref"}
	}
	query := spec.Query
	if strings.TrimSpace(query) == "" {
		return &ExecResult{ReturnCode: 1, Stderr: "sql executor requires a non-empty query"}
	}

	dialect := spec.Dialect
	if dialect == "" {
		dialect = "postgres"
	}
	maxRows := spec.MaxRows
	if maxRows <= 0 {
		maxRows = 10000
	}
	autocommit := true
	if spec.Autocommit != nil {
		autocommit = *spec.Autocommit
	}

	var driverCode string
	if dialect == "mongodb" {
		database := spec.Database
		driverCode = fmt.Sprintf(
			"import json, sys\n"+
				"try:\n"+
				"    from pymongo import MongoClient\n"+
				"except ImportError:\n"+
				"    print('pymongo is not installed on this worker', file=sys.stderr); sys.exit(1)\n"+
				"client = MongoClient(%q)\n"+
				"db = client[%q] if %q else client.get_default_database()\n"+
				"result = db.command(%q)\n"+
				"print(json.dumps(result, default=str))\n",
			connURI, database, database, query,
		)
	} else {
		var queryBlock string
		if !autocommit {
			queryBlock = fmt.Sprintf(
				"    trans = conn.begin()\n"+
					"    try:\n"+
					"        result = conn.execute(text(%q))\n"+
					"        try:\n"+
					"            rows = [dict(r._mapping) for r in result]\n"+
					"            truncated = len(rows) > %d\n"+
					"            rows = rows[:%d]\n"+
					"            print(json.dumps({\"rows\": rows, \"row_count\": len(rows), \"truncated\": truncated}, default=str))\n"+
					"        except Exception:\n"+
					"            print(json.dumps({\"rows\": [], \"row_count\": 0, \"truncated\": False, \"message\": \"query executed (no result set)\"}, default=str))\n"+
					"        trans.commit()\n"+
					"    except Exception as e:\n"+
					"        trans.rollback()\n"+
					"        raise\n",
				query, maxRows, maxRows,
			)
		} else {
			queryBlock = fmt.Sprintf(
				"    result = conn.execute(text(%q))\n"+
					"    try:\n"+
					"        rows = [dict(r._mapping) for r in result]\n"+
					"        truncated = len(rows) > %d\n"+
					"        rows = rows[:%d]\n"+
					"        print(json.dumps({\"rows\": rows, \"row_count\": len(rows), \"truncated\": truncated}, default=str))\n"+
					"    except Exception:\n"+
					"        print(json.dumps({\"rows\": [], \"row_count\": 0, \"truncated\": False, \"message\": \"query executed (no result set)\"}, default=str))\n",
				query, maxRows, maxRows,
			)
		}
		driverCode = fmt.Sprintf(
			"import json, sys\n"+
				"try:\n"+
				"    from sqlalchemy import create_engine, text\n"+
				"except ImportError:\n"+
				"    print('sqlalchemy is not installed on this worker', file=sys.stderr); sys.exit(1)\n"+
				"engine = create_engine(%q)\n"+
				"with engine.connect() as conn:\n"+
				"%s",
			connURI, queryBlock,
		)
	}

	interpreter := findPython()
	if interpreter == "" {
		return &ExecResult{ReturnCode: 1, Stderr: "no python interpreter found to run SQL driver script"}
	}

	tmp, err := writeTempFile("hydra-sql-", ".py", driverCode)
	if err != nil {
		return &ExecResult{ReturnCode: 1, Stderr: fmt.Sprintf("failed to write SQL driver script: %v", err)}
	}
	defer os.Remove(tmp)

	return runCommand(ctx, []string{interpreter, tmp}, env, "", onStdout, onStderr)
}

// execHTTP performs an HTTP request and returns the response.
func execHTTP(ctx context.Context, spec *ExecutorSpec, onStdout, onStderr func(string)) *ExecResult {
	targetURL := spec.URL
	if targetURL == "" {
		return &ExecResult{ReturnCode: 1, Stderr: "http executor requires a non-empty url"}
	}

	method := strings.ToUpper(spec.Method)
	if method == "" {
		method = "GET"
	}

	timeoutSec := spec.TimeoutSeconds
	if timeoutSec <= 0 {
		timeoutSec = 30
	}

	var bodyReader io.Reader
	if spec.Body != "" {
		bodyReader = strings.NewReader(spec.Body)
	}

	req, err := http.NewRequestWithContext(ctx, method, targetURL, bodyReader)
	if err != nil {
		return &ExecResult{ReturnCode: 1, Stderr: fmt.Sprintf("failed to build request: %v", err)}
	}
	for k, v := range spec.Headers {
		req.Header.Set(k, v)
	}

	client := &http.Client{Timeout: time.Duration(timeoutSec) * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return &ExecResult{ReturnCode: 1, Stderr: fmt.Sprintf("http request failed: %v", err)}
	}
	defer resp.Body.Close()

	respBody, _ := io.ReadAll(resp.Body)
	respHeaders := make(map[string]string)
	for k := range resp.Header {
		respHeaders[k] = resp.Header.Get(k)
	}

	result := map[string]interface{}{
		"status":  resp.StatusCode,
		"headers": respHeaders,
		"body":    string(respBody),
	}
	resultJSON, _ := json.Marshal(result)
	resultStr := string(resultJSON)

	if onStdout != nil {
		onStdout(resultStr)
	}

	expectedStatus := spec.ExpectedStatus
	if len(expectedStatus) == 0 {
		expectedStatus = []int{200}
	}
	statusOK := false
	for _, s := range expectedStatus {
		if s == resp.StatusCode {
			statusOK = true
			break
		}
	}
	if !statusOK {
		return &ExecResult{ReturnCode: 1, Stdout: resultStr, Stderr: fmt.Sprintf("unexpected status %d", resp.StatusCode)}
	}

	return &ExecResult{ReturnCode: 0, Stdout: resultStr}
}

// ---------------------------------------------------------------------------
// Impersonation / Kerberos
// ---------------------------------------------------------------------------

// withImpersonation wraps cmd with sudo if impersonateUser is set.
func withImpersonation(cmd []string, user string) ([]string, error) {
	if user == "" {
		return cmd, nil
	}
	switch runtime.GOOS {
	case "linux", "darwin":
		return append([]string{"sudo", "-n", "-u", user, "--"}, cmd...), nil
	default:
		return nil, fmt.Errorf("impersonation not supported on %s; configure the worker service to run as the target user", runtime.GOOS)
	}
}

// kerberosInit runs kinit to bootstrap Kerberos authentication.
func kerberosInit(ctx context.Context, kerberos map[string]string, user string, env map[string]string) error {
	principal := kerberos["principal"]
	keytab := kerberos["keytab"]
	if principal == "" || keytab == "" {
		return nil
	}
	cmd := []string{"kinit", "-kt", keytab, principal}
	if user != "" {
		var err error
		cmd, err = withImpersonation(cmd, user)
		if err != nil {
			return err
		}
	}
	result := runCommand(ctx, cmd, env, "", nil, nil)
	if result.ReturnCode != 0 {
		return fmt.Errorf("kerberos init failed: %s", result.Stderr)
	}
	return nil
}

// ---------------------------------------------------------------------------
// Core subprocess runner
// ---------------------------------------------------------------------------

// Conventional exit codes for signals.
const (
	exitCodeTimeout  = 137 // SIGKILL
	exitCodeCanceled = 130 // SIGINT
)

// runCommand executes a command with context-based timeout, streaming
// stdout/stderr lines via callbacks, and returns the aggregated result.
func runCommand(ctx context.Context, cmdArgs []string, env map[string]string, workdir string, onStdout, onStderr func(string)) *ExecResult {
	if len(cmdArgs) == 0 {
		return &ExecResult{ReturnCode: 1, Stderr: "empty command"}
	}

	c := exec.CommandContext(ctx, cmdArgs[0], cmdArgs[1:]...)

	// Merge environment: start with current process env, overlay extras.
	c.Env = mergeOSEnv(env)

	if workdir != "" {
		c.Dir = workdir
	}

	stdoutPipe, err := c.StdoutPipe()
	if err != nil {
		return &ExecResult{ReturnCode: 1, Stderr: fmt.Sprintf("stdout pipe: %v", err)}
	}
	stderrPipe, err := c.StderrPipe()
	if err != nil {
		return &ExecResult{ReturnCode: 1, Stderr: fmt.Sprintf("stderr pipe: %v", err)}
	}

	if err := c.Start(); err != nil {
		return &ExecResult{ReturnCode: 1, Stderr: fmt.Sprintf("start: %v", err)}
	}

	var stdoutBuf, stderrBuf strings.Builder
	var wg sync.WaitGroup
	wg.Add(2)

	go func() {
		defer wg.Done()
		scanner := bufio.NewScanner(stdoutPipe)
		for scanner.Scan() {
			line := scanner.Text()
			stdoutBuf.WriteString(line)
			stdoutBuf.WriteByte('\n')
			if onStdout != nil {
				onStdout(line)
			}
		}
	}()

	go func() {
		defer wg.Done()
		scanner := bufio.NewScanner(stderrPipe)
		for scanner.Scan() {
			line := scanner.Text()
			stderrBuf.WriteString(line)
			stderrBuf.WriteByte('\n')
			if onStderr != nil {
				onStderr(line)
			}
		}
	}()

	wg.Wait()
	err = c.Wait()

	rc := 0
	if err != nil {
		var exitErr *exec.ExitError
		if errors.As(err, &exitErr) {
			rc = exitErr.ExitCode()
		} else if ctx.Err() == context.DeadlineExceeded {
			rc = exitCodeTimeout
			stderrBuf.WriteString("process killed: timeout exceeded\n")
		} else if ctx.Err() == context.Canceled {
			rc = exitCodeCanceled
			stderrBuf.WriteString("process killed: canceled\n")
		} else {
			rc = 1
			stderrBuf.WriteString(fmt.Sprintf("exec error: %v\n", err))
		}
	}

	return &ExecResult{
		ReturnCode: rc,
		Stdout:     stdoutBuf.String(),
		Stderr:     stderrBuf.String(),
	}
}

// ---------------------------------------------------------------------------
// Capability / shell detection (used during worker registration)
// ---------------------------------------------------------------------------

// DetectCapabilities returns the list of executor types this worker supports.
func DetectCapabilities() []string {
	caps := []string{"shell", "external"}

	if findPython() != "" {
		caps = append(caps, "python")
		// SQL executor uses Python as a bridge — only advertise if Python is available.
		caps = append(caps, "sql")
	}
	if findPowershell() != "" {
		caps = append(caps, "powershell")
	}
	if runtime.GOOS == "windows" {
		caps = append(caps, "batch")
	}
	// HTTP executor uses Go's stdlib — always available.
	caps = append(caps, "http")
	// Sensor executor is always advertised, mirroring the Python worker
	// (its HTTP sensor path always works via stdlib; an SQL-type sensor on
	// a worker without Python/sqlalchemy fails at runtime the same way the
	// SQL executor itself would — that asymmetry already exists in Python
	// today, so this replicates it rather than papering over it here).
	caps = append(caps, "sensor")
	return caps
}

// DetectShells returns the list of shell interpreters available on this system.
func DetectShells() []string {
	isWindows := runtime.GOOS == "windows"
	bashPath := strings.TrimSpace(os.Getenv("HYDRA_SHELL_PATH"))
	if bashPath == "" {
		bashPath = "/bin/bash"
	}
	type probe struct {
		name string
		cmd  []string
	}

	var candidates []probe
	if isWindows {
		candidates = []probe{
			{"bash", []string{"bash", "--version"}},
			{"cmd", []string{"cmd", "/c", "echo ok"}},
			{"powershell", []string{"powershell", "-Command", "echo ok"}},
			{"pwsh", []string{"pwsh", "-Command", "echo ok"}},
		}
	} else {
		candidates = []probe{
			{"bash", []string{bashPath, "--version"}},
			{"sh", []string{"/bin/sh", "--version"}},
			{"pwsh", []string{"pwsh", "-Command", "echo ok"}},
		}
	}

	var found []string
	for _, c := range candidates {
		if probeCmd(c.cmd) {
			found = append(found, c.name)
		}
	}
	return found
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

// buildEnv merges executor-level env vars and job params into a single map.
// Params are prefixed with HYDRA_PARAM_ to avoid collisions.
func buildEnv(executorEnv, params map[string]string) map[string]string {
	merged := make(map[string]string, len(executorEnv)+len(params))
	for k, v := range executorEnv {
		merged[k] = v
	}
	for k, v := range params {
		merged["HYDRA_PARAM_"+k] = v
	}
	return merged
}

// mergeOSEnv returns os.Environ() with the extra key=value pairs overlaid.
func mergeOSEnv(extra map[string]string) []string {
	base := os.Environ()
	if len(extra) == 0 {
		return base
	}
	// Index existing vars for fast override.
	idx := make(map[string]int, len(base))
	for i, entry := range base {
		if k, _, ok := strings.Cut(entry, "="); ok {
			idx[k] = i
		}
	}
	for k, v := range extra {
		if i, exists := idx[k]; exists {
			base[i] = k + "=" + v
		} else {
			base = append(base, k+"="+v)
		}
	}
	return base
}

// tempDir returns the configured scratch directory for executor temp files.
// Returns "" (OS default) when HYDRA_TEMP_DIR is not set.
func tempDir() string {
	return strings.TrimSpace(os.Getenv("HYDRA_TEMP_DIR"))
}

// writeTempFile creates a temporary file with the given prefix, suffix, and
// content, returning its path. The caller is responsible for removal.
// Honours HYDRA_TEMP_DIR for non-containerized environments.
func writeTempFile(prefix, suffix, content string) (string, error) {
	f, err := os.CreateTemp(tempDir(), prefix+"*"+suffix)
	if err != nil {
		return "", err
	}
	path := f.Name()
	if _, err := f.WriteString(content); err != nil {
		f.Close()
		os.Remove(path)
		return "", err
	}
	if err := f.Close(); err != nil {
		os.Remove(path)
		return "", err
	}
	// Make script files executable.
	if err := os.Chmod(path, 0700); err != nil {
		log.Printf("[executor] chmod warning: %v", err)
	}
	return path, nil
}

// findPython returns the first available Python interpreter or "".
// Honours HYDRA_PYTHON_PATH for non-containerized environments.
func findPython() string {
	if configured := strings.TrimSpace(os.Getenv("HYDRA_PYTHON_PATH")); configured != "" {
		if probeCmd([]string{configured, "--version"}) {
			return configured
		}
	}
	for _, interp := range []string{"python3", "python"} {
		if probeCmd([]string{interp, "--version"}) {
			return interp
		}
	}
	return ""
}

// findPowershell returns the first available PowerShell binary or "".
func findPowershell() string {
	for _, ps := range []string{"pwsh", "powershell"} {
		if probeCmd([]string{ps, "-Command", "echo ok"}) {
			return ps
		}
	}
	return ""
}

// probeCmd runs a command with a short timeout and returns true if it exits 0.
func probeCmd(args []string) bool {
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	cmd := exec.CommandContext(ctx, args[0], args[1:]...)
	cmd.Stdout = nil
	cmd.Stderr = nil
	return cmd.Run() == nil
}
