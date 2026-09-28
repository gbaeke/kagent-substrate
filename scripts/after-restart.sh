#!/usr/bin/env bash
# Run after a laptop reboot / Docker restart. The kind node comes back and every pod
# restarts, but Substrate's gVisor worker pods keep stale actor networking: the router
# resumes actors and then times out connecting to them ("Connect: deadline has elapsed"),
# and kagent answers KAGENT_SEND_NOT_ACCEPTED. Recycling the workers fixes it; actors that
# were resumed during the broken window end up CRASHED and are reverted to their last snapshot.
set -euo pipefail
source "$(dirname "$0")/env.sh"
K="kubectl --context $KCTX"
echo "waiting for the API server..."; until $K get --raw /readyz >/dev/null 2>&1; do sleep 3; done
$K wait node --all --for=condition=Ready --timeout=5m
# Deployment status is stale right after a restart, so wait on the pods themselves.
for ns in kube-system ate-system kagent; do
  until [ -z "$($K -n $ns get pods --no-headers 2>/dev/null | grep -v Completed | awk '{split($2,a,"/"); if (a[1]!=a[2] || $3!="Running") print}')" ]; do sleep 5; done
  echo "$ns ready"
done
want=$($K -n kagent get workerpool kagent-default -o jsonpath='{.spec.replicas}')
$K -n kagent delete pod -l ate.dev/worker-pool --wait=true
until [ "$($K -n kagent get pods -l ate.dev/worker-pool --no-headers 2>/dev/null | grep -c ' 1/1 .*Running')" -ge "$want" ]; do sleep 3; done
echo "workers recycled"
kubectl-ate --context "$KCTX" get actors -A | awk '/ACTOR_STATE_CRASHED/{print $1, $2}' | while read -r space name; do
  echo "reverting crashed actor $space/$name"; kubectl-ate --context "$KCTX" revert actor "$name" -a "$space"
done
kubectl-ate --context "$KCTX" get workers
