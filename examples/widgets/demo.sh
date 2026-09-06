#!/usr/bin/env bash
# Run from the repository root. Requires uv, Docker, kind, kubectl and openssl.
set -euo pipefail
export CLOUDCOIL_NAMESPACE=widgets
uv sync --group dev
if [ ! -d .build/widgets-models ]; then
  uv run --no-sync python tools/generate_kubernetes.py --version 1.37.0 --output .build/widgets-models
fi
uv pip install --no-deps .build/widgets-models
docker build -f examples/widgets/Dockerfile -t widgets:local .
if ! kind get clusters | rg -qx cloudcoil-widgets; then
  kind create cluster --name cloudcoil-widgets --image kindest/node:v1.37.0
fi
# Never depend on whichever kubectl context happened to be selected before this demo.
export KUBECONFIG="$(mktemp)"
kind get kubeconfig --name cloudcoil-widgets > "$KUBECONFIG"
kind load docker-image widgets:local --name cloudcoil-widgets
kubectl create namespace widgets --dry-run=client -o yaml | kubectl apply -f -
tls_dir=$(mktemp -d)
trap 'rm -rf "$tls_dir"; rm -f "$KUBECONFIG"' EXIT
openssl req -x509 -newkey rsa:2048 -nodes -days 7 -subj /CN=widgets-demo-ca \
  -keyout "$tls_dir/ca.key" -out "$tls_dir/ca.crt" \
  -addext 'basicConstraints=critical,CA:TRUE' 2>/dev/null
openssl req -newkey rsa:2048 -nodes -subj /CN=widgets.widgets.svc \
  -keyout "$tls_dir/tls.key" -out "$tls_dir/tls.csr" 2>/dev/null
printf 'subjectAltName=DNS:widgets.widgets.svc\nextendedKeyUsage=serverAuth\n' > "$tls_dir/extensions"
openssl x509 -req -in "$tls_dir/tls.csr" -CA "$tls_dir/ca.crt" -CAkey "$tls_dir/ca.key" \
  -CAcreateserial -days 7 -out "$tls_dir/tls.crt" -extfile "$tls_dir/extensions" 2>/dev/null
kubectl -n widgets create secret tls widgets-tls --cert="$tls_dir/tls.crt" --key="$tls_dir/tls.key" \
  --dry-run=client -o yaml | kubectl apply -f -
uv run --no-sync python examples/widget_operator.py install --image widgets:local --ca-file "$tls_dir/ca.crt"
kubectl -n widgets apply -f examples/widgets/widget.yaml
kubectl -n widgets wait widget/hello --for=jsonpath='{.status.phase}'=Ready --timeout=180s
kubectl -n widgets create configmap widget-policy --from-literal=maxLength=10 \
  --dry-run=client -o yaml | kubectl apply -f -
if denial=$(kubectl -n widgets patch widget hello --type merge \
  -p '{"spec":{"message":"This exceeds the namespace policy"}}' --dry-run=server 2>&1); then
  printf 'Expected admission to reject the overlong message\n' >&2
  exit 1
fi
printf '%s\n' "$denial" | rg 'Namespace policy limits messages to 10 characters'
kubectl -n widgets delete configmap widget-policy
kubectl -n widgets get widgets,configmaps,deployments,services
printf '\nTry: kubectl --context kind-cloudcoil-widgets -n widgets port-forward svc/hello 8080:80\n'
