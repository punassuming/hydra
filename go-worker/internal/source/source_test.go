package source

import (
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

// TestStripCredentials verifies that stripCredentials rewrites the origin
// remote so a token injected by injectToken does not remain in
// dest/.git/config once the network operation that needed it is done.
func TestStripCredentials(t *testing.T) {
	dir := t.TempDir()
	if out, err := exec.Command("git", "init", "-q", dir).CombinedOutput(); err != nil {
		t.Fatalf("git init failed: %s", string(out))
	}

	dirtyURL := "https://x-oauth-token:super-secret-token@github.com/example/repo.git"
	cleanURL := "https://github.com/example/repo.git"

	addCmd := exec.Command("git", "remote", "add", "origin", dirtyURL)
	addCmd.Dir = dir
	if out, err := addCmd.CombinedOutput(); err != nil {
		t.Fatalf("git remote add failed: %s", string(out))
	}

	if err := stripCredentials(dir, cleanURL); err != nil {
		t.Fatalf("stripCredentials returned error: %v", err)
	}

	configPath := filepath.Join(dir, ".git", "config")
	data, err := os.ReadFile(configPath)
	if err != nil {
		t.Fatalf("failed to read .git/config: %v", err)
	}
	config := string(data)

	if strings.Contains(config, "super-secret-token") {
		t.Fatalf(".git/config still contains the token after stripCredentials:\n%s", config)
	}
	if !strings.Contains(config, cleanURL) {
		t.Fatalf(".git/config does not contain the clean URL after stripCredentials:\n%s", config)
	}
}

// TestInjectTokenThenStripCredentials exercises the full round trip: inject
// a token the way FetchGit does, then strip it, confirming the two halves
// compose correctly.
func TestInjectTokenThenStripCredentials(t *testing.T) {
	dir := t.TempDir()
	if out, err := exec.Command("git", "init", "-q", dir).CombinedOutput(); err != nil {
		t.Fatalf("git init failed: %s", string(out))
	}

	repoURL := "https://github.com/example/repo.git"
	token := "super-secret-token"
	dirtyURL := injectToken(repoURL, token)

	if !strings.Contains(dirtyURL, token) {
		t.Fatalf("expected injectToken to embed the token, got: %s", dirtyURL)
	}

	addCmd := exec.Command("git", "remote", "add", "origin", dirtyURL)
	addCmd.Dir = dir
	if out, err := addCmd.CombinedOutput(); err != nil {
		t.Fatalf("git remote add failed: %s", string(out))
	}

	if err := stripCredentials(dir, repoURL); err != nil {
		t.Fatalf("stripCredentials returned error: %v", err)
	}

	data, err := os.ReadFile(filepath.Join(dir, ".git", "config"))
	if err != nil {
		t.Fatalf("failed to read .git/config: %v", err)
	}
	config := string(data)

	if strings.Contains(config, token) {
		t.Fatalf(".git/config still contains the token after the inject+strip round trip:\n%s", config)
	}
}
