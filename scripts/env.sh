# Shared settings for the PoC scripts. Source me: `source scripts/env.sh`
export POC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PATH="$POC_DIR/bin:$PATH"
export KIND_CLUSTER=${KIND_CLUSTER:-kagent-poc}   # override to run a second copy side by side
export KCTX=kind-$KIND_CLUSTER
export KIND_NODE_IMAGE=kindest/node:v1.35.0
# Matched pair: kagent v1.0.0-alpha5 pins substrate v0.3.0-alpha1 in go.mod + CI.
export SUBSTRATE_VERSION=0.3.0-alpha1
export KAGENT_VERSION=1.0.0-alpha5
export WORKER_POOL_REPLICAS=2
# Pinned CLI tools (downloaded into bin/ by scripts/00-tools.sh)
export KIND_VERSION=v0.33.0
export KUBECTL_VERSION=v1.35.9   # within skew of the 1.35 node
export HELM_VERSION=v4.3.0
# Local LLM served by Ollama inside the cluster (also set providers.ollama.model in cluster/kagent-values.yaml)
export OLLAMA_MODEL=qwen3:4b-instruct   # non-thinking; plain qwen3:4b overthinks (3k+ tokens per reply on CPU)
