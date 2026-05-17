# API Failure Injection

Testing tool to intercept Anthropic API calls and return a chosen http status code.

Uses mitmproxy to intercept http requests.

## Usage

1. Start the sidecar
    - `docker compose -f docker-compose.mitm.yml up -d`
1. Extract the CA cert (once per sidecar lifetime)
    - `docker cp mitm-sidecar:/home/mitmproxy/.mitmproxy/mitmproxy-ca-cert.pem <app>/secrets/mitmproxy-ca.crt`
1. Configure the consuming app to route through the proxy and trust the cert
    - `HTTPS_PROXY=http://host.docker.internal:8080`
    - `NODE_EXTRA_CA_CERTS=/path/inside/container/to/mitmproxy-ca.crt`
    - bind-mount the cert into the agent container at that path
1. Set the injection policy
    - `curl 'http://localhost:8080/__reset__?n=3'` — return 500 on next 3 calls
    - `curl 'http://localhost:8080/__reset__?n=2&status=503'` — override status
    - `curl http://localhost:8080/__state__` — read current counter + policy
1. Run the consuming app
1. Stop the sidecar
    - `docker compose -f docker-compose.mitm.yml down`

## Command

```bash
docker compose -f docker-compose.mitm.yml up -d
docker compose -f docker-compose.mitm.yml down

docker compose restart

# obtain the public certificate
docker cp mitm-sidecar:/home/mitmproxy/.mitmproxy/mitmproxy-ca-cert.pem ./mitmproxy-ca.crt

curl http://localhost:8080/__state__
curl 'http://localhost:8080/__reset__?n=3'
curl 'http://localhost:8080/__reset__?n=2&status=503'
```
