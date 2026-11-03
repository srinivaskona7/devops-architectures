---
title: Registries, tags and digests
minutes: 45
objectives:
  - Explain how a registry stores and serves images using the OCI distribution API
  - Choose a tagging strategy and pin deployments by digest
  - Push to and pull from Amazon ECR and GitHub Container Registry including lifecycle cleanup
---
A registry is where CI puts images and where clusters pull them from. Tag discipline and registry hygiene decide whether you can answer the question "exactly what is running in production".

@concept How a registry works
@plain
A registry is an HTTP server that stores image manifests and layer blobs, addressed by repository name and by digest. Docker Hub, ECR, GHCR, Harbor and Quay all speak the same OCI Distribution API.
@problem
Machines that build an image are rarely the machines that run it. You need a shared, access controlled store that transfers only missing layers.
@does
- `docker push` uploads each missing layer blob (`/v2/<repo>/blobs/uploads/`), then the manifest (`/v2/<repo>/manifests/<tag>`).
- `docker pull` fetches the manifest, then only layers not already cached locally.
- Authentication is a token flow: a `401` response names the auth realm, the client gets a bearer token and retries.
- Layer blobs are deduplicated by digest within a registry.
@diagram seq
caption: What docker pull does over HTTPS
actors: ["Docker or containerd|client|app", "Registry|ECR, GHCR, Hub|cp", "Auth service|token endpoint|ext"]
steps:
  - "0>1: GET manifest | req"
  - "1>0: 401 with realm | bad"
  - "0>2: request token with credentials | tls"
  - "2>0: bearer token | resp"
  - "0>1: GET manifest with token | tls"
  - "1>0: manifest lists layer digests | resp"
  - "0>1: GET only missing blobs | req"
@h See it
```bash title="Talk to a registry directly" lab
TOKEN=$(curl -s "https://auth.docker.io/token?service=registry.docker.io&scope=repository:library/alpine:pull" | python3 -c 'import sys,json; print(json.load(sys.stdin)["token"])')
curl -s -H "Authorization: Bearer $TOKEN" -H "Accept: application/vnd.oci.image.index.v1+json" \
  https://registry-1.docker.io/v2/library/alpine/manifests/3.20 | python3 -m json.tool | head -20
```
@end

@concept Tags are mutable, digests are not
@plain
A tag is a label that a push can move to different content. A digest is the SHA-256 of the manifest, so it names exactly one set of bytes.
@problem
If production uses `shop-api:1.4` and someone re-pushes that tag, pods created after the push run different code than pods created before, with no change in Git.
@does
- Tags are good for humans and promotion (`1.4.2`, `main`, `prod`).
- Digests are good for deploys: `shop-api@sha256:ab12...` cannot change.
- Immutable tags (an ECR and GHCR option) make re-pushing an existing tag fail.
- In Kubernetes, `image: repo:tag@sha256:...` uses the digest and shows the tag for humans.
@diagram cmp
caption: Tag versus digest
cards:
  - {h: "Tag", kind: warn, items: ["Moves when re-pushed", "Readable such as 1.4.2", "latest is just a tag", "Use for discovery"]}
  - {h: "Digest", kind: ok, items: ["Content hash, never moves", "Unreadable sha256", "Proves what ran", "Use for deployment and signing"]}
@h Resolve and pin
```bash title="Find the digest behind a tag" lab
docker buildx imagetools inspect nginx:1.27-alpine --format '{{json .Manifest.Digest}}'
docker pull nginx:1.27-alpine | grep -i digest
docker image inspect nginx:1.27-alpine --format '{{index .RepoDigests 0}}'
```
:::warn
Only the digest of the image index is stable across architectures. A digest from `docker inspect` on an arm64 laptop can be a platform manifest and differ from the index digest in CI. Always take the digest from the registry after the push.
:::
@check
Why deploy by digest even when you also keep a version tag? || The digest cannot be re-pointed, so the cluster, an audit and a signature all refer to the same bytes.
@end

@concept A tagging strategy
@plain
Pick a small set of tag types and give each a meaning. Every build gets a unique immutable tag; moving tags are promotion pointers.
@problem
Teams that tag only `latest` cannot roll back, and teams that tag randomly cannot find what is in production.
@does
- Unique per build: Git SHA, `sha-3f9c2ab` (always).
- Release: semantic version `1.4.2` for a Git tag (immutable).
- Moving pointers: `main`, `staging`, `prod` only if you must; prefer GitOps changing a digest in Git.
- Never rely on `latest` for deployment.
- `docker/metadata-action` in GitHub Actions generates these tags and OCI labels.
@diagram flow
caption: Promotion by retagging, not rebuilding
numbered: true
nodes:
  - "Build once|sha-3f9c2ab|app"
  - "Test and scan|same digest|info"
  - "Retag 1.4.2|registry side, no rebuild|ok"
  - "Deploy|digest in Git|cp"
@h Retag without rebuilding
```bash title="Promote an image" lab
docker buildx imagetools create -t ghcr.io/acme/shop-api:1.4.2 ghcr.io/acme/shop-api:sha-3f9c2ab
docker buildx imagetools inspect ghcr.io/acme/shop-api:1.4.2 | head -5
```
@end

@concept Amazon ECR
@plain
ECR is AWS's private registry. Access is controlled by IAM, and a login token is valid for 12 hours.
@problem
Credentials in CI and clusters must be short lived and scoped, and images must be scanned and cleaned up automatically.
@does
- Repository URI: `<account>.dkr.ecr.<region>.amazonaws.com/<repo>`.
- Login uses `aws ecr get-login-password`. EKS nodes pull through the node IAM role (`AmazonEC2ContainerRegistryReadOnly`).
- Settings per repository: `imageTagMutability=IMMUTABLE`, scan on push, encryption (AES-256 or KMS).
- Lifecycle policies expire old images; pull through cache mirrors Docker Hub and others; replication copies across regions.
@diagram flow
caption: CI pushes, cluster pulls, both through IAM
nodes:
  - "CI role|ecr:PutImage via OIDC|ext"
  - "ECR repository|immutable tags, scan on push|cp"
  - "Node role|ecr:GetDownloadUrlForLayer|env"
  - "Pod|image pulled by containerd|ok"
@h Create, login, push
```bash title="ECR workflow" lab
REGION=eu-west-1; ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
REPO=shop-api; REG=$ACCOUNT.dkr.ecr.$REGION.amazonaws.com
aws ecr create-repository --repository-name $REPO --image-tag-mutability IMMUTABLE \
  --image-scanning-configuration scanOnPush=true --region $REGION
aws ecr get-login-password --region $REGION | docker login --username AWS --password-stdin $REG
docker tag shop-api:dev $REG/$REPO:sha-$(git rev-parse --short HEAD)
docker push $REG/$REPO:sha-$(git rev-parse --short HEAD)
```
```json title="Lifecycle policy that expires untagged images after 7 days and keeps 20"
{
  "rules": [
    {"rulePriority": 1, "description": "expire untagged", "selection": {"tagStatus": "untagged", "countType": "sinceImagePushed", "countUnit": "days", "countNumber": 7}, "action": {"type": "expire"}},
    {"rulePriority": 2, "description": "keep last 20", "selection": {"tagStatus": "any", "countType": "imageCountMoreThan", "countNumber": 20}, "action": {"type": "expire"}}
  ]
}
```
@end

@concept GitHub Container Registry (GHCR)
@plain
GHCR (`ghcr.io`) stores images next to your code and uses GitHub identities and permissions. In Actions, the built in `GITHUB_TOKEN` can push.
@problem
Maintaining separate registry credentials for each pipeline is toil and a leak risk.
@does
- Image name must be lowercase: `ghcr.io/<owner>/<repo>`.
- Workflow needs `permissions: packages: write`.
- The label `org.opencontainers.image.source` links the package to its repository and inherits permissions.
- Packages are private by default; make public deliberately.
- Pulling from a cluster needs an `imagePullSecret` with a token that has `read:packages`.
@diagram flow
caption: GitHub Actions to GHCR to cluster
nodes:
  - "Workflow|GITHUB_TOKEN|app"
  - "ghcr.io package|linked to the repo|cp"
  - "imagePullSecret|read:packages token|warn"
  - "Cluster|pulls the image|ok"
@h Workflow
```yaml title=".github/workflows/build.yml"
name: build
on:
  push:
    branches: [main]
permissions:
  contents: read
  packages: write
jobs:
  image:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@v4
      - uses: docker/setup-buildx-action@v3
      - uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - uses: docker/metadata-action@v5
        id: meta
        with:
          images: ghcr.io/${{ github.repository }}
          tags: |
            type=sha
            type=semver,pattern={{version}}
      - uses: docker/build-push-action@v6
        with:
          context: .
          push: true
          tags: ${{ steps.meta.outputs.tags }}
          labels: ${{ steps.meta.outputs.labels }}
```
```bash title="Create a pull secret for Kubernetes" lab
kubectl create secret docker-registry ghcr-pull --docker-server=ghcr.io \
  --docker-username="$GH_USER" --docker-password="$GH_READ_PACKAGES_TOKEN" -n shop
```
@end

@concept Pull rate limits, mirrors and private registries
@plain
Public registries throttle anonymous pulls. Large cluster scale-out events can hit those limits and leave pods in ImagePullBackOff.
@problem
A node autoscaling event pulls the same base image on twenty nodes at once from one NAT IP, and Docker Hub starts returning 429.
@does
- Docker Hub limits anonymous pulls per IP and free authenticated accounts per user (the numbers change, check current terms).
- Mirror base images into ECR (pull through cache or a copy job) and reference your copy in Dockerfiles.
- Self-hosted options: Harbor, Nexus, Artifactory, or `registry:2` for tests.
- Use `imagePullPolicy: IfNotPresent` with immutable tags to avoid needless pulls.
@diagram flow
caption: Pull through cache protects from limits
nodes:
  - "Node|requests the image|env"
  - "ECR pull through cache|stores a copy|cp"
  - "Docker Hub|only on a cache miss|ext"
@h Debug a pull failure
```bash title="Common ImagePullBackOff checks" lab
kubectl describe pod mypod | sed -n '/Events/,$p' | tail -8
docker pull ghcr.io/acme/shop-api:sha-3f9c2ab               # works from your laptop?
docker manifest inspect ghcr.io/acme/shop-api:sha-3f9c2ab >/dev/null && echo exists
aws ecr describe-images --repository-name shop-api --image-ids imageTag=sha-3f9c2ab
```
@end
