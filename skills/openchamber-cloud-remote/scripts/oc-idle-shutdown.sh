#!/bin/sh
# Stop this VM after a period with no SSH sessions. Provider is explicit in
# /etc/oc-remote.conf, written by install-idle-shutdown.sh.
set -eu

IDLE_SECONDS=${OC_IDLE_SECONDS:-1800}
IDLE_FILE=${OC_IDLE_FILE:-/var/tmp/oc-idle-since}
LOG=${OC_IDLE_LOG:-/var/log/oc-idle-shutdown.log}
CONFIG=${OC_IDLE_CONFIG:-/etc/oc-remote.conf}
GRACE_SECONDS=300

log() {
  printf '%s %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*" >> "$LOG"
}

provider=${OC_CLOUD_PROVIDER:-}
if [ -z "$provider" ] && [ -f "$CONFIG" ]; then
  # Written by the installer with mode 0644, contains only the provider name.
  # shellcheck source=/dev/null
  . "$CONFIG"
  provider=${OC_CLOUD_PROVIDER:-}
fi
case "$provider" in
  azure | gcp | aws) ;;
  *)
    log "no valid OC_CLOUD_PROVIDER in $CONFIG; not stopping the VM"
    exit 1
    ;;
esac

# Give cloud-init and OpenChamber's first setup time to finish after a cold start.
uptime_raw=$(awk '{print $1}' /proc/uptime)
uptime_seconds=${uptime_raw%%.*}
case "$uptime_seconds" in
  '' | *[!0-9]*) uptime_seconds=0 ;;
esac
if [ "$uptime_seconds" -lt "$GRACE_SECONDS" ]; then
  log 'skipping: uptime under 5 minutes'
  exit 0
fi

users=$(who | wc -l | tr -d '[:space:]')
connections=$(ss -tnH state established '( dport = :22 or sport = :22 )' 2>/dev/null | wc -l | tr -d '[:space:]')

if [ "$users" -gt 0 ] || [ "$connections" -gt 0 ]; then
  rm -f "$IDLE_FILE"
  log "SSH active ($users sessions, $connections connections); resetting idle timer"
  exit 0
fi

if [ ! -f "$IDLE_FILE" ]; then
  date +%s > "$IDLE_FILE"
  log 'no SSH sessions; starting idle timer'
  exit 0
fi

now=$(date +%s)
idle_for=$((now - $(cat "$IDLE_FILE")))
if [ "$idle_for" -lt "$IDLE_SECONDS" ]; then
  log "idle for ${idle_for}s; waiting"
  exit 0
fi

response_file=''
trap 'if [ -n "$response_file" ]; then rm -f "$response_file"; fi' 0 HUP INT TERM

case "$provider" in
  azure)
    # Deallocate is the only Azure power state that stops compute billing.
    token=$(curl -fsS -H Metadata:true \
      'http://169.254.169.254/metadata/identity/oauth2/token?api-version=2018-02-01&resource=https%3A%2F%2Fmanagement.azure.com%2F' \
      | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')
    resource_id=$(curl -fsS -H Metadata:true \
      'http://169.254.169.254/metadata/instance/compute/resourceId?api-version=2021-02-01&format=text')
    response_file=$(mktemp "${TMPDIR:-/tmp}/oc-stop-response.XXXXXX")
    status=$(curl -sS -o "$response_file" -w '%{http_code}' -X POST \
      -H "Authorization: Bearer $token" -H 'Content-Length: 0' \
      "https://management.azure.com${resource_id}/deallocate?api-version=2024-07-01") || status=000
    if [ "$status" = '202' ] || [ "$status" = '200' ]; then
      rm -f "$IDLE_FILE"
      log "idle for ${idle_for}s; Azure accepted deallocate (HTTP $status)"
    else
      log "deallocate failed (HTTP $status): $(cat "$response_file")"
    fi
    ;;
  gcp)
    token=$(curl -fsS -H 'Metadata-Flavor: Google' \
      'http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token' \
      | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')
    project=$(curl -fsS -H 'Metadata-Flavor: Google' \
      'http://metadata.google.internal/computeMetadata/v1/project/project-id')
    zone=$(curl -fsS -H 'Metadata-Flavor: Google' \
      'http://metadata.google.internal/computeMetadata/v1/instance/zone' | sed 's|.*/||')
    instance=$(curl -fsS -H 'Metadata-Flavor: Google' \
      'http://metadata.google.internal/computeMetadata/v1/instance/name')
    response_file=$(mktemp "${TMPDIR:-/tmp}/oc-stop-response.XXXXXX")
    status=$(curl -sS -o "$response_file" -w '%{http_code}' -X POST \
      -H "Authorization: Bearer $token" -H 'Content-Length: 0' \
      "https://compute.googleapis.com/compute/v1/projects/${project}/zones/${zone}/instances/${instance}/stop") || status=000
    if [ "$status" = '200' ] || [ "$status" = '202' ]; then
      rm -f "$IDLE_FILE"
      log "idle for ${idle_for}s; GCP accepted stop (HTTP $status)"
    else
      log "stop failed (HTTP $status): $(cat "$response_file")"
    fi
    ;;
  aws)
    # The bundled AWS CLI is installed by cloud-init; IMDSv2 supplies region/id.
    imds_token=$(curl -fsS -X PUT -H 'X-aws-ec2-metadata-token-ttl-seconds: 60' \
      'http://169.254.169.254/latest/api/token')
    region=$(curl -fsS -H "X-aws-ec2-metadata-token: $imds_token" \
      'http://169.254.169.254/latest/dynamic/instance-identity/document' \
      | python3 -c 'import json,sys; print(json.load(sys.stdin)["region"])')
    instance_id=$(curl -fsS -H "X-aws-ec2-metadata-token: $imds_token" \
      'http://169.254.169.254/latest/meta-data/instance-id')
    response_file=$(mktemp "${TMPDIR:-/tmp}/oc-stop-response.XXXXXX")
    if aws ec2 stop-instances --region "$region" --instance-ids "$instance_id" >"$response_file" 2>&1; then
      rm -f "$IDLE_FILE"
      log "idle for ${idle_for}s; AWS accepted stop for $instance_id"
    else
      log "AWS stop-instances failed: $(cat "$response_file")"
    fi
    ;;
esac
