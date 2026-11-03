---
title: cert-manager and TLS certificates
minutes: 45
objectives:
  - Choose between ACM, cert-manager with Let's Encrypt and a private CA
  - Configure issuers with DNS-01 validation through Route 53
  - Rotate and monitor certificates inside the cluster
---
TLS certificates expire. Automating issuance and renewal removes a whole class of outages. On AWS you have two main tools: ACM for load balancers and cert-manager for certificates that live inside the cluster.
@concept ACM versus cert-manager
@plain
AWS Certificate Manager (ACM) issues free public certificates that attach to ALB, NLB (TLS listener), CloudFront and API Gateway. You cannot export the private key. cert-manager creates certificates as Kubernetes Secrets that pods can mount.
@problem
Some TLS endpoints are pods themselves (mTLS, webhooks, ingress controllers such as NGINX or Istio gateways) and need a key in the cluster.
@does
- ACM public certs auto-renew when DNS validation records remain in place.
- cert-manager supports ACME (Let's Encrypt), a private CA, Vault, and AWS Private CA via a plugin.
- Use ACM at the edge when an ALB terminates TLS; use cert-manager for in-cluster TLS and mTLS.
- ACM Private CA issues certificates for internal use at an hourly CA fee.
@diagram cmp
caption: Where each fits
cards:
  - {h: "ACM", kind: ok, items: ["Free public certs", "ALB, NLB, CloudFront", "Key never leaves AWS"]}
  - {h: "cert-manager", kind: app, items: ["Secrets in the cluster", "Ingress controllers, mTLS", "Many issuers"]}
@choose Pick a certificate source
ACM | an ALB or CloudFront terminates TLS | the pod itself needs the private key
cert-manager with Let's Encrypt | in-cluster ingress or a webhook needs public trust | you cannot use DNS-01 or HTTP-01 at all
cert-manager with private CA | internal mTLS between services | clients cannot trust your private root
@h Request an ACM certificate
```bash title="DNS validated ACM certificate" nocheck
aws acm request-certificate --domain-name shop.example.com \
  --subject-alternative-names "*.shop.example.com" --validation-method DNS
aws acm describe-certificate --certificate-arn arn:aws:acm:us-east-1:111122223333:certificate/11111111-2222-3333-4444-555555555555 \
  --query 'Certificate.DomainValidationOptions[0].ResourceRecord'
```
@check
Can you export the private key of an ACM public certificate? || No; it stays inside AWS-integrated services.
@end

@concept Installing cert-manager
@plain
cert-manager runs as three deployments (controller, webhook, cainjector) and adds CRDs: `Issuer`, `ClusterIssuer`, `Certificate`, `CertificateRequest`.
@problem
Without a controller, renewing certificates means cron jobs and manual secret updates.
@does
- Install with Helm and `crds.enabled=true` (older charts use `installCRDs`).
- A `Certificate` resource names the DNS names, issuer and target Secret.
- The controller renews at two thirds of the lifetime by default (configurable with `renewBefore`).
- Ingress annotations (`cert-manager.io/cluster-issuer`) create certificates automatically from Ingress TLS sections.
@diagram flow
caption: From Certificate to Secret
numbered: true
nodes:
  - "Certificate|names and issuer|app"
  - "CertificateRequest|CSR|info"
  - "Issuer|ACME, CA|ext"
  - "Secret|tls.crt, tls.key|ok"
@h Install
```bash title="Helm install" nocheck
helm repo add jetstack https://charts.jetstack.io && helm repo update
helm upgrade --install cert-manager jetstack/cert-manager -n cert-manager --create-namespace \
  --set crds.enabled=true
kubectl -n cert-manager get pods
```
@check
When does cert-manager renew by default? || At two thirds of the certificate lifetime.
@end

@concept ACME DNS-01 with Route 53
@plain
DNS-01 proves domain ownership by creating a TXT record. It works for wildcard names and for clusters not reachable from the internet.
@problem
HTTP-01 needs a public endpoint on port 80, which many clusters do not have, and it cannot issue wildcard certificates.
@does
- A `ClusterIssuer` with the ACME server URL and a Route 53 solver.
- cert-manager needs `route53:ChangeResourceRecordSets` on the zone and `route53:GetChange`, `ListHostedZonesByName`; give it a Pod Identity or IRSA role.
- Use the Let's Encrypt **staging** endpoint while testing to avoid rate limits.
- Certificates last 90 days (check current CA policy); renewal is automatic.
@diagram seq
caption: DNS-01 challenge
actors: ["cert-manager|controller|cp", "Let's Encrypt|ACME|ext", "Route 53|DNS|info"]
steps:
  - "0>1: order for shop.example.com | req"
  - "1>0: challenge token | resp"
  - "0>2: create TXT _acme-challenge | tls"
  - "1>2: check TXT | req"
  - "1>0: certificate issued | resp"
@h ClusterIssuer
```yaml title="Let's Encrypt with Route 53"
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-prod
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    email: platform@example.com
    privateKeySecretRef:
      name: letsencrypt-prod-key
    solvers:
      - dns01:
          route53:
            region: us-east-1
            hostedZoneID: Z0123456789ABCDEFGHIJ
---
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: shop-tls
  namespace: shop
spec:
  secretName: shop-tls
  dnsNames:
    - shop.example.com
  issuerRef:
    name: letsencrypt-prod
    kind: ClusterIssuer
```
@check
Why use the staging ACME server first? || It has far higher rate limits, so configuration mistakes do not lock you out.
@end

@concept Private CA for internal mTLS
@plain
A private CA issues certificates your own services trust. cert-manager can run a self-signed root in the cluster or call AWS Private CA.
@problem
Service-to-service encryption needs certificates with short lifetimes and automated rotation, which a public CA does not provide for internal names.
@does
- A `selfSigned` issuer creates a root; a `ca` issuer signs leaf certificates from it.
- Short lifetimes (24 hours to 90 days) reduce exposure; use `duration` and `renewBefore`.
- `aws-privateca-issuer` plugin issues from AWS Private CA with IAM controlled access.
- A service mesh (Istio, Linkerd) usually manages workload mTLS itself; use cert-manager for the mesh root if required.
@diagram flow
caption: Internal CA chain
nodes:
  - "Self-signed issuer|bootstrap|plain"
  - "Root CA certificate|isCA true|cp"
  - "CA issuer|signs leaves|info"
  - "Service certs|90 days, auto renew|ok"
@h Manifests
```yaml title="Self-signed root and CA issuer"
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: selfsigned
spec:
  selfSigned: {}
---
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: internal-root
  namespace: cert-manager
spec:
  isCA: true
  commonName: internal-root
  secretName: internal-root
  privateKey:
    algorithm: ECDSA
    size: 256
  issuerRef:
    name: selfsigned
    kind: ClusterIssuer
---
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: internal-ca
spec:
  ca:
    secretName: internal-root
```
@check
Why prefer short certificate lifetimes? || Compromised keys expire quickly and automation makes rotation cheap.
@end

@concept Monitoring and troubleshooting
@plain
Certificates fail quietly: a renewal error shows up only on expiry day. Watch cert-manager's status and metrics.
@problem
Expiry outages are common and entirely preventable.
@does
- `kubectl get certificate -A` shows READY state; `kubectl describe certificate` and `certificaterequest`, `order`, `challenge` show why issuance fails.
- Prometheus metric `certmanager_certificate_expiration_timestamp_seconds` supports alerts such as "expires in less than 14 days".
- Common failures: DNS-01 IAM denied, wrong hosted zone, rate limits, webhook not ready after install.
- `cmctl status certificate` and `cmctl renew` assist operations.
@diagram flow
caption: Debug chain
nodes:
  - "Certificate|Ready false|warn"
  - "CertificateRequest|approved?|info"
  - "Order and Challenge|ACME state|app"
  - "Fix IAM or DNS|retry|ok"
@h Commands
```bash title="Find the failing step" lab
kubectl get certificate -A
kubectl -n shop describe certificate shop-tls | tail -20
kubectl -n shop get certificaterequest,order,challenge
kubectl -n cert-manager logs deploy/cert-manager --tail=30
```
```yaml title="Prometheus alert rule"
groups:
  - name: certs
    rules:
      - alert: CertificateExpiringSoon
        expr: (certmanager_certificate_expiration_timestamp_seconds - time()) < 14 * 24 * 3600
        for: 1h
        labels:
          severity: warning
        annotations:
          summary: "Certificate {{ $labels.name }} expires in less than 14 days"
```
@check
Which metric helps alert on expiry? || certmanager_certificate_expiration_timestamp_seconds.
@end
