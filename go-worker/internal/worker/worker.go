// Package worker implements the main worker loop that registers with Redis
// and listens for jobs dispatched by the scheduler.
package worker

import (
	"context"
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"log"
	"net"
	"os"
	"os/user"
	"runtime"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"github.com/google/uuid"
	"github.com/redis/go-redis/v9"

	"github.com/punassuming/hydra/go-worker/internal/config"
	"github.com/punassuming/hydra/go-worker/internal/executor"
)

// Start registers the worker in Redis, starts the heartbeat and kill
// listener goroutines, and begins the job polling loop.
// It blocks until ctx is cancelled.
func Start(ctx context.Context, cfg *config.Config, rdb *redis.Client) error {
	if err := register(ctx, cfg, rdb); err != nil {
		return fmt.Errorf("worker registration failed: %w", err)
	}

	log.Printf("[worker] %s registered on domain %q (state=%s, concurrency=%d)",
		cfg.WorkerID, cfg.Domain, cfg.InitialState, cfg.MaxConcurrency)

	w := &workerState{
		cfg:       cfg,
		rdb:       rdb,
		activeIDs: make(map[string]struct{}),
		killChans: make(map[string]context.CancelFunc),
	}

	// Start background goroutines.
	go w.heartbeatLoop(ctx)
	go w.killListener(ctx)

	queueKey := fmt.Sprintf("job_queue:%s:%s", cfg.Domain, cfg.WorkerID)

	log.Printf("[worker] %s starting with max_concurrency=%d", cfg.WorkerID, cfg.MaxConcurrency)
	return w.pollLoop(ctx, queueKey)
}

// workerState holds the mutable runtime state shared between goroutines.
type workerState struct {
	cfg *config.Config
	rdb *redis.Client

	mu        sync.Mutex
	activeIDs map[string]struct{} // job_id -> struct{}
	running   int32               // atomic running count

	killMu    sync.Mutex
	killChans map[string]context.CancelFunc // run_id -> cancel
}

// ---------------------------------------------------------------------------
// Registration
// ---------------------------------------------------------------------------

// register writes the full worker metadata hash into Redis, matching the
// Python worker's register_worker().
func register(ctx context.Context, cfg *config.Config, rdb *redis.Client) error {
	key := fmt.Sprintf("workers:%s:%s", cfg.Domain, cfg.WorkerID)
	isRestart := rdb.Exists(ctx, key).Val() > 0

	hostname, _ := os.Hostname()
	ipAddr := resolveIP(hostname)
	subnet := ""
	if ipAddr != "" {
		parts := strings.Split(ipAddr, ".")
		if len(parts) >= 3 {
			subnet = strings.Join(parts[:3], ".")
		}
	}
	runUser := ""
	if u, err := user.Current(); err == nil {
		runUser = u.Username
	}
	tokenHash := fmt.Sprintf("%x", sha256.Sum256([]byte(cfg.DomainToken)))

	shells := executor.DetectShells()
	capabilities := executor.DetectCapabilities()

	fields := map[string]interface{}{
		"worker_id":        cfg.WorkerID,
		"os":               runtime.GOOS,
		"domain":           cfg.Domain,
		"tags":             strings.Join(cfg.Tags, ","),
		"allowed_users":    strings.Join(cfg.AllowedUsers, ","),
		"max_concurrency":  cfg.MaxConcurrency,
		"current_running":  0,
		"status":           "online",
		"state":            cfg.InitialState,
		"cpu_count":        runtime.NumCPU(),
		"go_version":       runtime.Version(),
		"cwd":              mustGetwd(),
		"hostname":         hostname,
		"ip":               ipAddr,
		"subnet":           subnet,
		"deployment_type":  cfg.DeploymentType,
		"run_user":         runUser,
		"shells":           strings.Join(shells, ","),
		"capabilities":     strings.Join(capabilities, ","),
		"domain_token_hash": tokenHash,
	}
	if err := rdb.HSet(ctx, key, fields).Err(); err != nil {
		return err
	}

	opType := "start"
	msg := "Worker process registered"
	if isRestart {
		opType = "restart"
		msg = "Worker process restarted and re-registered"
	}
	appendWorkerOp(ctx, rdb, cfg.Domain, cfg.WorkerID, opType, msg, map[string]interface{}{
		"max_concurrency": cfg.MaxConcurrency,
		"state":           cfg.InitialState,
		"hostname":        hostname,
		"run_user":        runUser,
		"pid":             os.Getpid(),
	})
	return nil
}

func ensureRegistration(ctx context.Context, cfg *config.Config, rdb *redis.Client) error {
	key := fmt.Sprintf("workers:%s:%s", cfg.Domain, cfg.WorkerID)
	exists, err := rdb.HExists(ctx, key, "domain_token_hash").Result()
	if err != nil {
		return err
	}
	if exists {
		return nil
	}
	return register(ctx, cfg, rdb)
}

// ---------------------------------------------------------------------------
// Heartbeat
// ---------------------------------------------------------------------------

func (w *workerState) heartbeatLoop(ctx context.Context) {
	const interval = 2 * time.Second
	sampleInterval := w.cfg.MetricsSampleSeconds
	// Ensure sample interval is never less than the heartbeat interval.
	if sampleInterval < interval.Seconds() {
		sampleInterval = interval.Seconds()
	}
	windowSec := w.cfg.MetricsWindowSeconds
	maxSamples := windowSec / int(sampleInterval)
	if maxSamples < 1 {
		maxSamples = 1
	}

	ticker := time.NewTicker(interval)
	defer ticker.Stop()

	var lastSampleAt float64

	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
		}

		now := float64(time.Now().UnixMilli()) / 1000.0

		// Update heartbeat sorted set.
		w.rdb.ZAdd(ctx, fmt.Sprintf("worker_heartbeats:%s", w.cfg.Domain), redis.Z{
			Score:  now,
			Member: w.cfg.WorkerID,
		})
		if err := ensureRegistration(ctx, w.cfg, w.rdb); err != nil {
			fmt.Printf("Worker registration refresh failed for %s: %v\n", w.cfg.WorkerID, err)
		}

		// Sync current_running + update job_running heartbeats.
		activeJobs := w.getActiveJobIDs()
		workerKey := fmt.Sprintf("workers:%s:%s", w.cfg.Domain, w.cfg.WorkerID)
		w.rdb.HSet(ctx, workerKey, "current_running", len(activeJobs))
		for _, jobID := range activeJobs {
			w.rdb.HSet(ctx, fmt.Sprintf("job_running:%s:%s", w.cfg.Domain, jobID), map[string]interface{}{
				"worker_id": w.cfg.WorkerID,
				"heartbeat": now,
			})
		}

		// Periodic metrics sampling.
		if now-lastSampleAt >= sampleInterval {
			metrics := collectMetrics()
			metrics["ts"] = now
			historyKey := fmt.Sprintf("worker_metrics:%s:%s:history", w.cfg.Domain, w.cfg.WorkerID)
			data, _ := json.Marshal(metrics)
			w.rdb.RPush(ctx, historyKey, string(data))
			w.rdb.LTrim(ctx, historyKey, int64(-maxSamples), -1)
			expiry := windowSec * 2
			if expiry < 3600 {
				expiry = 3600
			}
			w.rdb.Expire(ctx, historyKey, time.Duration(expiry)*time.Second)

			w.rdb.HSet(ctx, workerKey, map[string]interface{}{
				"process_count": metrics["process_count"],
				"memory_rss_mb": metrics["memory_rss_mb"],
				"metrics_ts":    now,
			})
			lastSampleAt = now
		}

		// Runs every tick regardless of the Redis calls above — proves the
		// loop goroutine is alive. Mirrors worker/utils/heartbeat.py's
		// _touch_heartbeat_file() in the Python worker.
		touchHeartbeatFile()
	}
}

const defaultHeartbeatFile = "/tmp/hydra_worker_heartbeat"

func heartbeatFilePath() string {
	if p := strings.TrimSpace(os.Getenv("WORKER_HEARTBEAT_FILE")); p != "" {
		return p
	}
	return defaultHeartbeatFile
}

// touchHeartbeatFile updates the local liveness file read by the container
// HEALTHCHECK / Kubernetes livenessProbe. It is intentionally independent of
// Redis reachability (which the heartbeat loop already tolerates) — a
// narrow "is this goroutine hung" signal, not a readiness check. Best-effort:
// a write failure must never take down the worker.
func touchHeartbeatFile() {
	_ = os.WriteFile(heartbeatFilePath(), []byte(strconv.FormatInt(time.Now().Unix(), 10)), 0o644)
}

// ---------------------------------------------------------------------------
// Kill listener
// ---------------------------------------------------------------------------

func (w *workerState) killListener(ctx context.Context) {
	pubsub := w.rdb.Subscribe(ctx, fmt.Sprintf("job_kill:%s", w.cfg.Domain))
	defer pubsub.Close()
	ch := pubsub.Channel()
	for {
		select {
		case <-ctx.Done():
			return
		case msg, ok := <-ch:
			if !ok {
				return
			}
			runID := strings.TrimSpace(msg.Payload)
			if runID == "" {
				continue
			}
			w.killMu.Lock()
			cancel, exists := w.killChans[runID]
			w.killMu.Unlock()
			if exists {
				log.Printf("[worker] killing run %s", runID)
				cancel()
			}
		}
	}
}

// ---------------------------------------------------------------------------
// Poll loop + job dispatch
// ---------------------------------------------------------------------------

func (w *workerState) pollLoop(ctx context.Context, queueKey string) error {
	// Semaphore for concurrency control.
	sem := make(chan struct{}, w.cfg.MaxConcurrency)

	log.Printf("[worker] listening on queue %q", queueKey)
	for {
		select {
		case <-ctx.Done():
			log.Printf("[worker] shutting down")
			return nil
		default:
		}

		result, err := w.rdb.BLPop(ctx, 2*time.Second, queueKey).Result()
		if err == redis.Nil {
			continue
		}
		if err != nil {
			if ctx.Err() != nil {
				return nil
			}
			log.Printf("[worker] BLPOP error: %v", err)
			time.Sleep(time.Second)
			continue
		}
		if len(result) < 2 {
			continue
		}

		var env executor.JobEnvelope
		if err := json.Unmarshal([]byte(result[1]), &env); err != nil {
			log.Printf("[worker] failed to decode job payload: %v", err)
			continue
		}

		bypassConcurrency := env.Job.BypassConcurrency
		if bypassConcurrency {
			go w.runJob(ctx, &env)
		} else {
			sem <- struct{}{}
			go func() {
				defer func() { <-sem }()
				w.runJob(ctx, &env)
			}()
		}
	}
}

// ---------------------------------------------------------------------------
// Job execution
// ---------------------------------------------------------------------------

func (w *workerState) runJob(ctx context.Context, env *executor.JobEnvelope) {
	jobID := env.JobID
	if jobID == "" {
		jobID = env.Job.ID
	}
	if jobID == "" {
		log.Printf("[worker] skipping envelope with no job_id")
		return
	}

	// Track active job.
	slot := int(atomic.AddInt32(&w.running, 1)) - 1
	w.mu.Lock()
	w.activeIDs[jobID] = struct{}{}
	w.mu.Unlock()
	w.rdb.SAdd(ctx, fmt.Sprintf("worker_running_set:%s:%s", w.cfg.Domain, w.cfg.WorkerID), jobID)
	w.rdb.HIncrBy(ctx, fmt.Sprintf("workers:%s:%s", w.cfg.Domain, w.cfg.WorkerID), "current_running", 1)

	runID := uuid.New().String()
	retriesRemaining := env.Job.Retries
	retryAttempt := env.RetryAttempt
	startedTS := float64(time.Now().UnixMilli()) / 1000.0

	var queueLatencyMs *float64
	if env.EnqueuedTS > 0 {
		lat := (startedTS - env.EnqueuedTS) * 1000.0
		if lat < 0 {
			lat = 0
		}
		queueLatencyMs = &lat
	}

	// Register a cancel context for kill support.
	jobCtx, jobCancel := context.WithCancel(ctx)
	w.killMu.Lock()
	w.killChans[runID] = jobCancel
	w.killMu.Unlock()

	defer func() {
		jobCancel()
		w.killMu.Lock()
		delete(w.killChans, runID)
		w.killMu.Unlock()
		w.rdb.Del(ctx, fmt.Sprintf("job_running:%s:%s", w.cfg.Domain, jobID))
		w.rdb.SRem(ctx, fmt.Sprintf("worker_running_set:%s:%s", w.cfg.Domain, w.cfg.WorkerID), jobID)
		w.rdb.HIncrBy(ctx, fmt.Sprintf("workers:%s:%s", w.cfg.Domain, w.cfg.WorkerID), "current_running", -1)
		atomic.AddInt32(&w.running, -1)
		w.mu.Lock()
		delete(w.activeIDs, jobID)
		w.mu.Unlock()
	}()

	// Set job_running hash.
	w.rdb.HSet(ctx, fmt.Sprintf("job_running:%s:%s", w.cfg.Domain, jobID), map[string]interface{}{
		"worker_id": w.cfg.WorkerID,
		"heartbeat": startedTS,
		"user":      env.Job.User,
		"domain":    w.cfg.Domain,
		"run_id":    runID,
	})

	scheduleMode := "immediate"
	var scheduleTick *string
	if env.Job.Schedule != nil {
		if env.Job.Schedule.Mode != "" {
			scheduleMode = env.Job.Schedule.Mode
		}
		scheduleTick = env.Job.Schedule.NextRunAt
	}
	execType := env.Job.Executor.Type
	if execType == "" {
		execType = "shell"
	}

	// Publish run_start event.
	w.publishRunEvent(ctx, map[string]interface{}{
		"type":                "run_start",
		"run_id":              runID,
		"job_id":              jobID,
		"user":                env.Job.User,
		"domain":              w.cfg.Domain,
		"worker_id":           w.cfg.WorkerID,
		"start_ts":            startedTS,
		"scheduled_ts":        orDefault(env.DispatchTS, startedTS),
		"slot":                slot,
		"attempt":             1,
		"retries_remaining":   retriesRemaining,
		"schedule_tick":       scheduleTick,
		"schedule_mode":       scheduleMode,
		"executor_type":       execType,
		"queue_latency_ms":    queueLatencyMs,
		"bypass_concurrency":  env.Job.BypassConcurrency,
	})

	appendWorkerOp(ctx, w.rdb, w.cfg.Domain, w.cfg.WorkerID, "run_exec",
		fmt.Sprintf("Executing job %s", jobID),
		map[string]interface{}{"run_id": runID, "job_id": jobID, "slot": slot})

	// Log streaming callback.
	streamLog := func(stream, chunk string) {
		if chunk == "" {
			return
		}
		payload := map[string]interface{}{
			"run_id":    runID,
			"job_id":    jobID,
			"worker_id": w.cfg.WorkerID,
			"domain":    w.cfg.Domain,
			"ts":        float64(time.Now().UnixMilli()) / 1000.0,
			"text":      chunk + "\n",
			"stream":    stream,
		}
		data, _ := json.Marshal(payload)
		channel := fmt.Sprintf("log_stream:%s:%s", w.cfg.Domain, runID)
		historyKey := channel + ":history"
		w.rdb.RPush(ctx, historyKey, string(data))
		w.rdb.LTrim(ctx, historyKey, -400, -1)
		w.rdb.Publish(ctx, channel, string(data))
		w.rdb.Expire(ctx, historyKey, time.Hour)
	}

	const artifactPrefix = "__HYDRA_ARTIFACT__:"

	// handleStdout intercepts artifact emission lines and emits run events,
	// passing all other lines through to the normal log stream.
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
					w.publishRunEvent(ctx, map[string]interface{}{
						"type":          "artifact_emitted",
						"run_id":        runID,
						"job_id":        jobID,
						"domain":        w.cfg.Domain,
						"artifact_name": artifactName,
						"metadata":      metadata,
					})
					return
				}
			}
			// Malformed artifact line — fall through to normal logging.
		}
		streamLog("stdout", line)
	}

	// Inject runtime params into executor env.
	if len(env.Params) > 0 {
		if env.Job.Executor.Env == nil {
			env.Job.Executor.Env = make(map[string]string)
		}
		for k, v := range env.Params {
			env.Job.Executor.Env[k] = v
		}
	}

	// Execute with retries.
	attempts := env.Job.Retries + 1
	if attempts < 1 {
		attempts = 1
	}
	var result *executor.ExecResult
	attemptsUsed := 0
	lastReason := ""
	success := false

	for i := 0; i < attempts; i++ {
		runStartTime := time.Now()
		result = executor.Execute(jobCtx, env,
			func(line string) { handleStdout(line) },
			func(line string) { streamLog("stderr", line) },
		)
		attemptsUsed++
		success, lastReason = evaluateCompletion(env.Job.Completion, result)
		if !success {
			continue
		}
		if fileOK, fileReason := evaluateFileCriteria(env.Job.Completion, runStartTime); !fileOK {
			success = false
			lastReason = fileReason
			streamLog("stderr", "[hydra] file validation failed: "+fileReason)
			continue
		}
		break
	}

	status := "success"
	if !success {
		status = "failed"
	}
	if lastReason == "" {
		lastReason = "criteria not met"
	}

	endTS := float64(time.Now().UnixMilli()) / 1000.0

	// Publish run_end event.
	w.publishRunEvent(ctx, map[string]interface{}{
		"type":                "run_end",
		"run_id":              runID,
		"job_id":              jobID,
		"user":                env.Job.User,
		"domain":              w.cfg.Domain,
		"worker_id":           w.cfg.WorkerID,
		"status":              status,
		"returncode":          result.ReturnCode,
		"stdout":              result.Stdout,
		"stderr":              result.Stderr,
		"attempt":             attemptsUsed,
		"completion_reason":   lastReason,
		"end_ts":              endTS,
		"slot":                slot,
		"retries_remaining":   retriesRemaining,
		"retry_attempt":       retryAttempt,
		"schedule_tick":       scheduleTick,
		"schedule_mode":       scheduleMode,
		"executor_type":       execType,
		"queue_latency_ms":    queueLatencyMs,
		"bypass_concurrency":  env.Job.BypassConcurrency,
		"start_ts":            startedTS,
		"scheduled_ts":        orDefault(env.DispatchTS, startedTS),
	})

	appendWorkerOp(ctx, w.rdb, w.cfg.Domain, w.cfg.WorkerID, "run_result",
		fmt.Sprintf("Job %s completed with status %s", jobID, status),
		map[string]interface{}{
			"run_id":            runID,
			"job_id":            jobID,
			"status":            status,
			"returncode":        result.ReturnCode,
			"attempt":           attemptsUsed,
			"completion_reason": lastReason,
		})

	if status == "failed" {
		log.Printf("[worker] job %s failed (rc=%d, reason=%s)", jobID, result.ReturnCode, lastReason)
	} else {
		log.Printf("[worker] job %s completed successfully", jobID)
	}
}

// ---------------------------------------------------------------------------
// Completion criteria
// ---------------------------------------------------------------------------

func evaluateCompletion(comp *executor.Completion, r *executor.ExecResult) (bool, string) {
	if comp == nil {
		if r.ReturnCode == 0 {
			return true, "criteria satisfied"
		}
		return false, fmt.Sprintf("exit code %d not in [0]", r.ReturnCode)
	}

	exitCodes := comp.ExitCodes
	if len(exitCodes) == 0 {
		exitCodes = []int{0}
	}
	found := false
	for _, c := range exitCodes {
		if c == r.ReturnCode {
			found = true
			break
		}
	}
	if !found {
		return false, fmt.Sprintf("exit code %d not in %v", r.ReturnCode, exitCodes)
	}

	for _, token := range comp.StdoutContains {
		if !strings.Contains(r.Stdout, token) {
			return false, fmt.Sprintf("stdout missing '%s'", token)
		}
	}
	for _, token := range comp.StdoutNotContains {
		if token != "" && strings.Contains(r.Stdout, token) {
			return false, fmt.Sprintf("stdout found forbidden '%s'", token)
		}
	}
	for _, token := range comp.StderrContains {
		if !strings.Contains(r.Stderr, token) {
			return false, fmt.Sprintf("stderr missing '%s'", token)
		}
	}
	for _, token := range comp.StderrNotContains {
		if token != "" && strings.Contains(r.Stderr, token) {
			return false, fmt.Sprintf("stderr found forbidden '%s'", token)
		}
	}
	return true, "criteria satisfied"
}

// evaluateFileCriteria checks file-existence and file-update-time criteria.
func evaluateFileCriteria(comp *executor.Completion, runStartTime time.Time) (bool, string) {
	if comp == nil {
		return true, "file criteria satisfied"
	}
	for _, path := range comp.RequireFileExists {
		if _, err := os.Stat(path); err != nil {
			return false, fmt.Sprintf("required file does not exist: %s", path)
		}
	}
	for _, path := range comp.RequireFileUpdatedSinceStart {
		info, err := os.Stat(path)
		if err != nil {
			return false, fmt.Sprintf("required file does not exist: %s", path)
		}
		if info.ModTime().Before(runStartTime) {
			return false, fmt.Sprintf("required file was not updated since job start: %s", path)
		}
	}
	return true, "file criteria satisfied"
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

func (w *workerState) getActiveJobIDs() []string {
	w.mu.Lock()
	defer w.mu.Unlock()
	ids := make([]string, 0, len(w.activeIDs))
	for id := range w.activeIDs {
		ids = append(ids, id)
	}
	return ids
}

func (w *workerState) publishRunEvent(ctx context.Context, event map[string]interface{}) {
	key := fmt.Sprintf("run_events:%s", w.cfg.Domain)
	data, _ := json.Marshal(event)
	w.rdb.RPush(ctx, key, string(data))
	w.rdb.Expire(ctx, key, 24*time.Hour)
}

func appendWorkerOp(ctx context.Context, rdb *redis.Client, domain, workerID, opType, message string, details map[string]interface{}) {
	event := map[string]interface{}{
		"ts":      float64(time.Now().UnixMilli()) / 1000.0,
		"type":    opType,
		"message": message,
		"details": details,
	}
	key := fmt.Sprintf("worker_ops:%s:%s", domain, workerID)
	data, _ := json.Marshal(event)
	rdb.RPush(ctx, key, string(data))
	rdb.LTrim(ctx, key, -1000, -1)
	rdb.Expire(ctx, key, 7*24*time.Hour)
}

func resolveIP(hostname string) string {
	addrs, err := net.LookupHost(hostname)
	if err != nil || len(addrs) == 0 {
		return ""
	}
	return addrs[0]
}

func mustGetwd() string {
	cwd, _ := os.Getwd()
	return cwd
}

func orDefault(v, def float64) float64 {
	if v > 0 {
		return v
	}
	return def
}
