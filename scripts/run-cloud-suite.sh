#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NAMESPACE="${NAMESPACE:-default}"
RUNS="${RUNS:-3}"
MODES="${MODES:-fixed,hpa}"
STABILIZATION_SECONDS="${STABILIZATION_SECONDS:-60}"
HPA_MANIFEST="${HPA_MANIFEST:-${ROOT_DIR}/k8s/hpa-300.yaml}"
HPA_RATES="${HPA_RATES:-12,14,16,14,12}"
HPA_LEVEL_DURATION="${HPA_LEVEL_DURATION:-3m}"
HPA_LEVEL_DURATIONS="${HPA_LEVEL_DURATIONS:-1m,3m,4m,2m,1m}"
SUITE_ID="${SUITE_ID:-$(date -u +%Y%m%dT%H%M%SZ)}"

if ! [[ "${RUNS}" =~ ^[1-9][0-9]*$ ]]; then
  echo "ERROR: RUNS must be a positive integer" >&2
  exit 1
fi

IFS=',' read -r -a MODES_ARRAY <<< "${MODES}"
if [[ "${#MODES_ARRAY[@]}" -eq 0 ]]; then
  echo "ERROR: MODES must contain fixed, hpa, or both" >&2
  exit 1
fi
for mode in "${MODES_ARRAY[@]}"; do
  if [[ "${mode}" != "fixed" && "${mode}" != "hpa" ]]; then
    echo "ERROR: unsupported mode '${mode}'; use fixed or hpa" >&2
    exit 1
  fi
done

wait_for_two_ready_pods() {
  kubectl rollout status deployment/invoice-pdf-api \
    -n "${NAMESPACE}" --timeout=180s

  local deadline=$((SECONDS + 180))
  while (( SECONDS < deadline )); do
    local desired ready
    desired="$(
      kubectl get deployment invoice-pdf-api -n "${NAMESPACE}" \
        -o jsonpath='{.spec.replicas}'
    )"
    ready="$(
      kubectl get deployment invoice-pdf-api -n "${NAMESPACE}" \
        -o jsonpath='{.status.readyReplicas}'
    )"
    if [[ "${desired:-0}" == "2" && "${ready:-0}" == "2" ]]; then
      echo "Deployment is 2/2 Ready; stabilizing for ${STABILIZATION_SECONDS}s"
      sleep "${STABILIZATION_SECONDS}"
      return
    fi
    sleep 5
  done

  echo "ERROR: deployment did not return to 2/2 Ready" >&2
  exit 1
}

prepare_mode() {
  local mode="$1"

  kubectl delete hpa invoice-pdf-api-hpa -n "${NAMESPACE}" \
    --ignore-not-found --wait=true >/dev/null
  kubectl scale deployment invoice-pdf-api \
    -n "${NAMESPACE}" --replicas=2 >/dev/null
  wait_for_two_ready_pods

  if [[ "${mode}" == "hpa" ]]; then
    kubectl apply -n "${NAMESPACE}" -f "${HPA_MANIFEST}"
    sleep 15
  fi
}

run_one() {
  local mode="$1"
  local round="$2"
  local scenario="${SUITE_ID}-${mode}-run${round}"

  echo
  echo "=== ${scenario}: ${HPA_RATES} RPS ==="
  prepare_mode "${mode}"

  NAMESPACE="${NAMESPACE}" \
  SCENARIO="${scenario}" \
  LOAD_PROFILE=hpa \
  HPA_RATES="${HPA_RATES}" \
  HPA_LEVEL_DURATION="${HPA_LEVEL_DURATION}" \
  HPA_LEVEL_DURATIONS="${HPA_LEVEL_DURATIONS}" \
  "${ROOT_DIR}/scripts/run-cloud-experiment.sh"
}

for ((round = 1; round <= RUNS; round++)); do
  if (( round % 2 == 1 )); then
    for mode in "${MODES_ARRAY[@]}"; do
      run_one "${mode}" "${round}"
    done
  else
    for ((index = ${#MODES_ARRAY[@]} - 1; index >= 0; index--)); do
      run_one "${MODES_ARRAY[index]}" "${round}"
    done
  fi
done

echo
echo "Suite completed: ${SUITE_ID}"
echo "Results are under ${ROOT_DIR}/results/${SUITE_ID}-*/"
