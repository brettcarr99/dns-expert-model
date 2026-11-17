# Self-Hosted Runner & launchd Setup

## Mac mini self-hosted runner (Tier B)

The nightly.yml workflow requires a runner with label `dns-expert-mini` registered on the Mac mini.

### Register the runner

```bash
# Step 1: get a registration token (expires in 1 hour)
gh api --method POST /repos/brettcarr99/dns-expert-model/actions/runners/registration-token --jq .token

# Step 2: download the latest runner for macOS arm64
mkdir -p ~/actions-runner && cd ~/actions-runner
RUNNER_VERSION=$(gh api /repos/actions/runner/releases/latest --jq '.tag_name' | tr -d 'v')
curl -o actions-runner-osx-arm64.tar.gz -L \
  "https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/actions-runner-osx-arm64-${RUNNER_VERSION}.tar.gz"
tar xzf actions-runner-osx-arm64.tar.gz

# Step 3: configure (replace TOKEN with output of step 1)
./config.sh \
  --url https://github.com/brettcarr99/dns-expert-model \
  --token TOKEN \
  --name dns-expert-mini \
  --labels dns-expert-mini,self-hosted,macOS,arm64 \
  --unattended \
  --replace

# Step 4: install as a launchd service and start
./svc.sh install
./svc.sh start
```

### Verify runner is registered

```bash
gh api /repos/brettcarr99/dns-expert-model/actions/runners --jq '.runners[] | {name, status, labels: [.labels[].name]}'
```

## launchd plist for nightly sync (independent of GitHub Actions)

The plist is NOT committed to git (it contains absolute paths).
It lives at: `~/Library/LaunchAgents/com.dns-expert.nightly-sync.plist`

### Load / manage

```bash
# Load (registers with launchd, starts at next scheduled time)
launchctl load ~/Library/LaunchAgents/com.dns-expert.nightly-sync.plist

# Check it is registered
launchctl list | grep dns-expert

# Manual test run
launchctl start com.dns-expert.nightly-sync

# View logs
tail -f ~/dns-experts/logs/nightly-sync.log

# Unload
launchctl unload ~/Library/LaunchAgents/com.dns-expert.nightly-sync.plist
```

### Schedule
Fires at **02:00 local time** daily. Runs `sync_rfcs.py` → updates `corpus_manifest.json`.
The GitHub Actions nightly workflow (02:00 UTC) handles eval + re-encrypt + release.

## Security notes

- `nightly.yml` does **not** include a `pull_request:` trigger — self-hosted runners must never execute untrusted fork code.
- The only allowed triggers are `schedule`, `workflow_dispatch`, and `push` to `main`.
