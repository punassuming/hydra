import json
import sys
import urllib.request


def main():
    url = "http://localhost:8000/jobs/"
    job = {
        "name": "test-echo",
        "user": "rich",
        "affinity": {"os": ["linux"], "tags": [], "allowed_users": ["rich"]},
        "executor": {"type": "shell", "script": "echo 'hello world'", "shell": "bash"},
        "timeout": 10,
        "retries": 0,
    }
    if len(sys.argv) > 1:
        # Load from file if provided
        with open(sys.argv[1], "r", encoding="utf-8") as f:
            job = json.load(f)
    data = json.dumps(job).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req) as resp:
        print(resp.status, resp.read().decode())


if __name__ == "__main__":
    main()
