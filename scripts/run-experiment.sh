#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOAD_PROFILE="${LOAD_PROFILE:-capacity}"
SCENARIO="${SCENARIO:-fixed}"
NAMESPACE="${NAMESPACE:-default}"
SELECTOR="${SELECTOR:-app=invoice-pdf-api}"
RUN_ID="${RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)}"
RESULTS_ROOT="${RESULTS_ROOT:-${ROOT_DIR}/results}"
RUN_DIR="${RESULTS_ROOT}/${SCENARIO}/${RUN_ID}"
COLLECT_INTERVAL="${COLLECT_INTERVAL:-5}"

if [[ -z "${BASE_URL:-}" ]]; then
  echo "ERROR: BASE_URL is required, for example http://EXTERNAL_IP" >&2
  exit 1
fi

for command in k6 kubectl python3; do
  if ! command -v "${command}" >/dev/null 2>&1; then
    echo "ERROR: ${command} is not installed or not in PATH" >&2
    exit 1
  fi
done

mkdir -p "${RUN_DIR}"

cat >"${RUN_DIR}/metadata.txt" <<EOF
run_id=${RUN_ID}
scenario=${SCENARIO}
load_profile=${LOAD_PROFILE}
base_url=${BASE_URL}
namespace=${NAMESPACE}
selector=${SELECTOR}
capacity_rates=${CAPACITY_RATES:-10,20,40,60,80,100,120}
capacity_level_duration=${CAPACITY_LEVEL_DURATION:-1m}
hpa_rates=${HPA_RATES:-5,10,15,20,25,15,5}
hpa_level_duration=${HPA_LEVEL_DURATION:-3m}
max_vus_floor=${MAX_VUS:-0}
automatic_max_vus=rate-x6
started_utc=$(date -u --iso-8601=seconds)
EOF

kubectl get deployment,hpa,pods -n "${NAMESPACE}" -o wide \
  >"${RUN_DIR}/cluster-before.txt" 2>&1 || true
kubectl get events -n "${NAMESPACE}" --sort-by=.lastTimestamp \
  >"${RUN_DIR}/events-before.txt" 2>&1 || true

python3 "${ROOT_DIR}/scripts/collect-k8s-metrics.py" \
  --output "${RUN_DIR}/k8s-metrics.csv" \
  --namespace "${NAMESPACE}" \
  --selector "${SELECTOR}" \
  --interval "${COLLECT_INTERVAL}" \
  >"${RUN_DIR}/collector-console.txt" 2>&1 &
COLLECTOR_PID=$!

cleanup() {
  if kill -0 "${COLLECTOR_PID}" >/dev/null 2>&1; then
    kill -INT "${COLLECTOR_PID}" >/dev/null 2>&1 || true
    wait "${COLLECTOR_PID}" || true
  fi
}
trap cleanup EXIT INT TERM

sleep 10
if ! kill -0 "${COLLECTOR_PID}" >/dev/null 2>&1; then
  wait "${COLLECTOR_PID}" || true
  echo "ERROR: Kubernetes collector stopped before k6 started" >&2
  echo "See ${RUN_DIR}/collector-console.txt" >&2
  exit 1
fi

set +e
LOAD_PROFILE="${LOAD_PROFILE}" \
BASE_URL="${BASE_URL}" \
k6 run \
  --out "json=${RUN_DIR}/k6-points.json" \
  --summary-export "${RUN_DIR}/k6-summary.json" \
  "${ROOT_DIR}/k6/load-test.js" \
  2>&1 | tee "${RUN_DIR}/k6-console.txt"
K6_STATUS=${PIPESTATUS[0]}
set -e

sleep 15
cleanup
trap - EXIT INT TERM

kubectl get deployment,hpa,pods -n "${NAMESPACE}" -o wide \
  >"${RUN_DIR}/cluster-after.txt" 2>&1 || true
kubectl get events -n "${NAMESPACE}" --sort-by=.lastTimestamp \
  >"${RUN_DIR}/events-after.txt" 2>&1 || true
kubectl get pods -n "${NAMESPACE}" -l "${SELECTOR}" -o json \
  >"${RUN_DIR}/pods-after.json" 2>&1 || true

python3 "${ROOT_DIR}/scripts/plot-experiment.py" \
  --k6 "${RUN_DIR}/k6-points.json" \
  --k8s "${RUN_DIR}/k8s-metrics.csv" \
  --output-dir "${RUN_DIR}/charts" \
  --label "${SCENARIO} - ${LOAD_PROFILE} - ${RUN_ID}"

printf 'finished_utc=%s\nk6_exit_status=%s\n' \
  "$(date -u --iso-8601=seconds)" "${K6_STATUS}" \
  >>"${RUN_DIR}/metadata.txt"

echo "Experiment artifacts: ${RUN_DIR}"
exit "${K6_STATUS}"
