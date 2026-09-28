#!/usr/bin/env bash
# Install Agent Substrate the way kagent's CI does (.github/workflows/ci.yaml @ v1.0.0-alpha5).
set -euo pipefail
source "$(dirname "$0")/env.sh"
K="kubectl --context $KCTX"
CHART=oci://ghcr.io/kagent-dev/substrate/helm

helm --kube-context "$KCTX" upgrade --install substrate-crds $CHART/substrate-crds \
  --version "$SUBSTRATE_VERSION" --namespace ate-system --create-namespace --wait

# First pass: pods will wait on secrets created in the next step, so no --wait here.
helm --kube-context "$KCTX" upgrade --install substrate $CHART/substrate \
  --version "$SUBSTRATE_VERSION" --namespace ate-system \
  --set 'credentialProvider.namespacePolicies[0].atespace=kagent' \
  --set 'credentialProvider.namespacePolicies[0].allowedNamespaces[0]=kagent'

# CA + JWT pools (kubectl-ate runs locally and writes Secrets).
$K create namespace podcertificate-controller-system --dry-run=client -o yaml | $K apply -f -
make_ca() { $K -n "$3" get secret "$1" >/dev/null 2>&1 || kubectl-ate --context "$KCTX" admin make-ca-pool --ca-id=1 --name="$1" --secret-namespace="$3" $2; }
make_ca service-dns-ca-pool  ""                     podcertificate-controller-system
make_ca pod-identity-ca-pool ""                     podcertificate-controller-system
make_ca actor-id-ca-pool     ""                     ate-system
make_ca egress-mitm-ca-pool  "--key-type=ECDSAP256" ate-system
$K -n ate-system get secret actor-id-jwt-pool >/dev/null 2>&1 || \
  kubectl-ate --context "$KCTX" admin make-jwt-pool --key-id=1 --name=actor-id-jwt-pool --secret-namespace=ate-system

# kubectl-ate exits 0 slightly before the secret is readable.
for _ in $(seq 1 60); do $K get secret actor-id-ca-pool -n ate-system >/dev/null 2>&1 && break; sleep 2; done

actor_id_ca_root="$($K get secret actor-id-ca-pool -n ate-system -o jsonpath='{.data.pool}' \
  | base64 --decode | jq -r '.CAs[0].RootCertificateDER' | base64 --decode | openssl x509 -inform der -outform pem)"
$K create secret generic actor-id-ca-certs -n ate-system --from-literal=ca.crt="$actor_id_ca_root" \
  --dry-run=client -o yaml | $K apply -f -

issuer="$($K get --raw /.well-known/openid-configuration | jq -r .issuer)"
$K create configmap ate-api-authentication -n ate-system --from-literal=authentication.yaml="actorIdentityJWTProvider: kubernetes
jwtProviders:
- name: kubernetes
  issuer: ${issuer}
  audiences: [api.ate-system.svc]
  certificateAuthorityFile: /var/run/secrets/kubernetes.io/serviceaccount/ca.crt
  discoveryTokenFile: /var/run/secrets/kubernetes.io/serviceaccount/token
" --dry-run=client -o yaml | $K apply -f -

# Second pass now that everything it mounts exists.
helm --kube-context "$KCTX" upgrade substrate $CHART/substrate --version "$SUBSTRATE_VERSION" \
  --namespace ate-system --reuse-values --wait --timeout 10m
$K get pods -n ate-system
