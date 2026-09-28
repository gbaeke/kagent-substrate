#!/usr/bin/env bash
# Check prerequisites and download the pinned CLI tools into ./bin (nothing is installed system-wide).
set -euo pipefail
source "$(dirname "$0")/env.sh"

missing=0
for t in docker curl jq openssl tar; do
  command -v "$t" >/dev/null || { echo "missing prerequisite: $t"; missing=1; }
done
[ "$missing" -eq 0 ] || exit 1
docker info >/dev/null 2>&1 || { echo "docker is installed but not running (or you lack permission)"; exit 1; }

OS=$(uname -s | tr '[:upper:]' '[:lower:]')
ARCH=$(uname -m); case "$ARCH" in x86_64) ARCH=amd64 ;; aarch64|arm64) ARCH=arm64 ;; esac
mkdir -p "$POC_DIR/bin"; cd "$POC_DIR/bin"

get() { # name url
  if [ -x "$1" ] && [ -f ".$1.version" ] && [ "$(cat ".$1.version")" = "$2" ]; then return; fi
  echo "downloading $1"; curl -fsSL -o "$1.tmp" "$2" && chmod +x "$1.tmp" && mv "$1.tmp" "$1" && echo "$2" > ".$1.version"
}
get kind        "https://github.com/kubernetes-sigs/kind/releases/download/${KIND_VERSION}/kind-${OS}-${ARCH}"
get kubectl     "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/${OS}/${ARCH}/kubectl"
get kubectl-ate "https://github.com/kagent-dev/substrate/releases/download/v${SUBSTRATE_VERSION}/kubectl-ate-${OS}-${ARCH}"
helm_url="https://get.helm.sh/helm-${HELM_VERSION}-${OS}-${ARCH}.tar.gz"
if ! [ -x helm ] || [ "$(cat .helm.version 2>/dev/null)" != "$helm_url" ]; then
  echo "downloading helm"; curl -fsSL "$helm_url" | tar xz --strip-components=1 "${OS}-${ARCH}/helm" && echo "$helm_url" > .helm.version
fi
./kind version; ./kubectl version --client | head -1; ./helm version --short; ./kubectl-ate --version
