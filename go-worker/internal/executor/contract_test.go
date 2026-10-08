package executor

import (
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"testing"
)

// The fixture is shared with the Python worker (tests/test_param_env_contract.py)
// so both implementations of "params -> environment variables" stay identical.
func TestBuildEnv_MatchesSharedContract(t *testing.T) {
	path := filepath.Join("..", "..", "..", "tests", "fixtures", "param_env_contract.json")
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read contract fixture: %v", err)
	}
	var fixture struct {
		Cases []struct {
			Name        string            `json:"name"`
			ExecutorEnv map[string]string `json:"executor_env"`
			Params      map[string]string `json:"params"`
			ExpectedEnv map[string]string `json:"expected_env"`
		} `json:"cases"`
	}
	if err := json.Unmarshal(raw, &fixture); err != nil {
		t.Fatalf("parse contract fixture: %v", err)
	}
	if len(fixture.Cases) == 0 {
		t.Fatal("contract fixture has no cases")
	}
	for _, c := range fixture.Cases {
		t.Run(c.Name, func(t *testing.T) {
			got := buildEnv(c.ExecutorEnv, c.Params)
			if !reflect.DeepEqual(got, c.ExpectedEnv) {
				t.Errorf("buildEnv = %v, want %v", got, c.ExpectedEnv)
			}
		})
	}
}
