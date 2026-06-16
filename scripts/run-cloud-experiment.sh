#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NAMESPACE="${NAMESPACE:-default}"
SCENARIO="${SCENARIO:-cloud-run}"
RUN_ID="${RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)}"
RESULTS_ROOT="${RESULTS_ROOT:-${ROOT_DIR}/results}"
RUN_DIR="${RESULTS_ROOT}/${SCENARIO}/${RUN_ID}"
BASE_URL="${BASE_URL:-http://invoice-pdf-api-service.${NAMESPACE}.svc.cluster.local}"
LOAD_PROFILE="${LOAD_PROFILE:-hpa}"
HPA_RATES="${HPA_RATES:-12,14,16,14,12}"
HPA_LEVEL_DURATION="${HPA_LEVEL_DURATION:-3m}"
HPA_LEVEL_DURATIONS="${HPA_LEVEL_DURATIONS:-}"
CAPACITY_RATES="${CAPACITY_RATES:-10,12,14,16,18,20}"
CAPACITY_LEVEL_DURATION="${CAPACITY_LEVEL_DURATION:-3m}"
CAPACITY_LEVEL_DURATIONS="${CAPACITY_LEVEL_DURATIONS:-}"
COLLECT_INTERVAL="${COLLECT_INTERVAL:-5}"
JOB_TIMEOUT="${JOB_TIMEOUT:-20m}"
RESULT_HOLD_SECONDS="${RESULT_HOLD_SECONDS:-60}"
KEEP_JOB="${KEEP_JOB:-false}"
JOB_NAME="k6-load-generator"

duration_to_seconds() {
  local value="$1"
  if [[ "${value}" =~ ^([0-9]+)(s|m|h)$ ]]; then
    local amount="${BASH_REMATCH[1]}"
    local unit="${BASH_REMATCH[2]}"
    case "${unit}" in
      s) echo "${amount}" ;;
      m) echo $((amount * 60)) ;;
      h) echo $((amount * 3600)) ;;
    esac
    return
  fi
  echo "ERROR: unsupported duration '${value}'; use s, m, or h" >&2
  exit 1
}

wait_for_results() {
  local timeout_seconds
  timeout_seconds="$(duration_to_seconds "${JOB_TIMEOUT}")"
  local deadline=$((SECONDS + timeout_seconds))

  while (( SECONDS < deadline )); do
    local pod_name phase failed
    pod_name="$(
      kubectl get pods -n "${NAMESPACE}" \
        -l job-name="${JOB_NAME}" \
        -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true
    )"
    if [[ -z "${pod_name}" ]]; then
      sleep 5
      continue
    fi

    phase="$(
      kubectl get pod "${pod_name}" -n "${NAMESPACE}" \
        -o jsonpath='{.status.phase}' 2>/dev/null || true
    )"
    failed="$(
      kubectl get job "${JOB_NAME}" -n "${NAMESPACE}" \
        -o jsonpath='{.status.failed}' 2>/dev/null || true
    )"

    if kubectl exec -n "${NAMESPACE}" "${pod_name}" -- \
      test -f /results/k6-exit-status >/dev/null 2>&1; then
      return 0
    fi

    if [[ "${phase}" == "Failed" || "${failed:-0}" -ge 1 ]]; then
      return 1
    fi
    sleep 5
  done
  return 1
}

for command in kubectl python3; do
  if ! command -v "${command}" >/dev/null 2>&1; then
    echo "ERROR: ${command} is not installed or not in PATH" >&2
    exit 1
  fi
done

mkdir -p "${RUN_DIR}"

cat >"${RUN_DIR}/metadata.txt" <<EOF
run_id=${RUN_ID}
scenario=${SCENARIO}
runner=kubernetes-job
load_profile=${LOAD_PROFILE}
base_url=${BASE_URL}
namespace=${NAMESPACE}
hpa_rates=${HPA_RATES}
hpa_level_duration=${HPA_LEVEL_DURATION}
hpa_level_durations=${HPA_LEVEL_DURATIONS}
capacity_rates=${CAPACITY_RATES}
capacity_level_duration=${CAPACITY_LEVEL_DURATION}
capacity_level_durations=${CAPACITY_LEVEL_DURATIONS}
result_hold_seconds=${RESULT_HOLD_SECONDS}
started_utc=$(date -u --iso-8601=seconds)
EOF

kubectl get deployment,hpa,pods -n "${NAMESPACE}" -o wide \
  >"${RUN_DIR}/cluster-before.txt" 2>&1 || true
kubectl get events -n "${NAMESPACE}" --sort-by=.lastTimestamp \
  >"${RUN_DIR}/events-before.txt" 2>&1 || true

python3 "${ROOT_DIR}/scripts/collect-k8s-metrics.py" \
  --output "${RUN_DIR}/k8s-metrics.csv" \
  --namespace "${NAMESPACE}" \
  --selector "app=invoice-pdf-api" \
  --interval "${COLLECT_INTERVAL}" \
  >"${RUN_DIR}/collector-console.txt" 2>&1 &
COLLECTOR_PID=$!

cleanup_collector() {
  if kill -0 "${COLLECTOR_PID}" >/dev/null 2>&1; then
    kill -INT "${COLLECTOR_PID}" >/dev/null 2>&1 || true
    wait "${COLLECTOR_PID}" || true
  fi
}

cleanup() {
  cleanup_collector
  if [[ "${KEEP_JOB}" != "true" ]]; then
    kubectl delete job "${JOB_NAME}" -n "${NAMESPACE}" \
      --ignore-not-found --wait=false >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT INT TERM

sleep 10
if ! kill -0 "${COLLECTOR_PID}" >/dev/null 2>&1; then
  wait "${COLLECTOR_PID}" || true
  echo "ERROR: Kubernetes metrics collector stopped before the test" >&2
  exit 1
fi

kubectl create configmap k6-load-test \
  --from-file=load-test.js="${ROOT_DIR}/k6/load-test.js" \
  -n "${NAMESPACE}" \
  --dry-run=client -o yaml |
  kubectl apply -f -

kubectl create configmap k6-runtime \
  --from-literal=BASE_URL="${BASE_URL}" \
  --from-literal=LOAD_PROFILE="${LOAD_PROFILE}" \
  --from-literal=HPA_RATES="${HPA_RATES}" \
  --from-literal=HPA_LEVEL_DURATION="${HPA_LEVEL_DURATION}" \
  --from-literal=HPA_LEVEL_DURATIONS="${HPA_LEVEL_DURATIONS}" \
  --from-literal=CAPACITY_RATES="${CAPACITY_RATES}" \
  --from-literal=CAPACITY_LEVEL_DURATION="${CAPACITY_LEVEL_DURATION}" \
  --from-literal=CAPACITY_LEVEL_DURATIONS="${CAPACITY_LEVEL_DURATIONS}" \
  --from-literal=RESULT_HOLD_SECONDS="${RESULT_HOLD_SECONDS}" \
  --from-literal=ENFORCE_THRESHOLDS=false \
  -n "${NAMESPACE}" \
  --dry-run=client -o yaml |
  kubectl apply -f -

kubectl delete job "${JOB_NAME}" -n "${NAMESPACE}" \
  --ignore-not-found --wait=true >/dev/null
kubectl apply -n "${NAMESPACE}" -f "${ROOT_DIR}/k8s/k6-job.yaml"

set +e
wait_for_results
RESULT_STATUS=$?
set -e

POD_NAME="$(
  kubectl get pods -n "${NAMESPACE}" \
    -l job-name="${JOB_NAME}" \
    -o jsonpath='{.items[0].metadata.name}'
)"
if [[ -z "${POD_NAME}" ]]; then
  echo "ERROR: k6 Job did not create a Pod" >&2
  exit 1
fi

kubectl logs -n "${NAMESPACE}" "${POD_NAME}" \
  >"${RUN_DIR}/k6-console.txt" 2>&1 || true

K6_STATUS=1
if [[ "${RESULT_STATUS}" -eq 0 ]]; then
  K6_STATUS="$(
    kubectl exec -n "${NAMESPACE}" "${POD_NAME}" -- \
      cat /results/k6-exit-status 2>/dev/null || echo 1
  )"
fi

COPY_STATUS=0
if [[ "${RESULT_STATUS}" -eq 0 ]]; then
  kubectl cp \
    "${NAMESPACE}/${POD_NAME}:/results/k6-points.json" \
    "${RUN_DIR}/k6-points.json" || COPY_STATUS=$?
  kubectl cp \
    "${NAMESPACE}/${POD_NAME}:/results/k6-summary.json" \
    "${RUN_DIR}/k6-summary.json" || COPY_STATUS=$?
else
  COPY_STATUS=1
fi

sleep 15
cleanup_collector

kubectl get deployment,hpa,pods -n "${NAMESPACE}" -o wide \
  >"${RUN_DIR}/cluster-after.txt" 2>&1 || true
kubectl get events -n "${NAMESPACE}" --sort-by=.lastTimestamp \
  >"${RUN_DIR}/events-after.txt" 2>&1 || true
kubectl get pods -n "${NAMESPACE}" -l app=invoice-pdf-api -o json \
  >"${RUN_DIR}/pods-after.json" 2>&1 || true

printf 'finished_utc=%s\nresult_wait_status=%s\nk6_exit_status=%s\ncopy_status=%s\n' \
  "$(date -u --iso-8601=seconds)" "${RESULT_STATUS}" "${K6_STATUS}" "${COPY_STATUS}" \
  >>"${RUN_DIR}/metadata.txt"

PLOT_STATUS=0
if [[ "${COPY_STATUS}" -eq 0 ]]; then
  python3 "${ROOT_DIR}/scripts/plot-experiment.py" \
    --k6 "${RUN_DIR}/k6-points.json" \
    --k8s "${RUN_DIR}/k8s-metrics.csv" \
    --output-dir "${RUN_DIR}/charts" \
    --label "${SCENARIO} - ${RUN_ID}" || PLOT_STATUS=$?
else
  PLOT_STATUS=1
fi
printf 'plot_exit_status=%s\n' "${PLOT_STATUS}" >>"${RUN_DIR}/metadata.txt"

echo "Experiment artifacts: ${RUN_DIR}"

if [[ "${RESULT_STATUS}" -ne 0 || "${K6_STATUS}" -ne 0 || "${COPY_STATUS}" -ne 0 ]]; then
  echo "ERROR: cloud experiment did not complete cleanly" >&2
  exit 1
fi
