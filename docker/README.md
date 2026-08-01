# Local Docker run

The Compose service exposes Mucha Science only on the host loopback interface at
<http://127.0.0.1:8787>. The process listens on `0.0.0.0` only inside the
container so Docker can forward that loopback-only host port.

## Build and start

```sh
docker build -t mucha-science:local .
docker compose up -d
curl -fsS http://127.0.0.1:8787/api/health
curl -fsS http://127.0.0.1:8787/api/packs
```

`docker compose up -d` can also build the image when it is absent because the
service includes a `build` definition.

Stop and remove the service container and network with:

```sh
docker compose down
```

The named volume `mucha-science-data` is mounted at `/data`. It retains the
ledger, domain packs, and generated artifacts across container replacement in
`/data/ledger`, `/data/packs`, and `/data/artifacts`. Docker initializes a new
volume's packs from those included in the image. `docker compose down` preserves
the volume; use `docker compose down --volumes` only when intentionally deleting
all local Mucha Science data.

No Supabase or PostgreSQL service is included: this single-user local app uses
its local ledger and artifact files, so an external database would add an
unnecessary networked state dependency.

## Record the image identity

Obtain the immutable digest of the exact local image with:

```sh
docker image inspect --format '{{.Id}}' mucha-science:local
```

Record that `sha256:...` value as `container_digest` when configuring an
external-tool adapter. The product's `AdapterInvocation` is implemented by
[`InvocationRecord`](../src/tools_ext/contract.py), whose `tool` mapping carries
this digest; the invocation writer populates `tool["container_digest"]` in
[`src/tools_ext/invoker.py`](../src/tools_ext/invoker.py). This binds each
adapter invocation to the image that actually ran it rather than to the mutable
`mucha-science:local` tag.
