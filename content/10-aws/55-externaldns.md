---
title: ExternalDNS and Route 53 automation
minutes: 40
objectives:
  - Explain how ExternalDNS turns Ingress and Service hostnames into Route 53 records
  - Install it with least privilege IAM and ownership TXT records
  - Use policies, filters and weighted records for safe automation and migrations
---
Creating an ALB is automatic; pointing `shop.example.com` at it is usually not. ExternalDNS closes that gap by watching Kubernetes resources and writing DNS records.

@concept What ExternalDNS does
@plain
ExternalDNS is a controller that reads hostnames from Ingress, Service and Gateway resources and creates matching records in a DNS provider such as Route 53.
@problem
Manual DNS edits drift from the cluster, get forgotten when services are deleted, and block self-service deployments.
@does
- Watches sources (`ingress`, `service`, `gateway-httproute`, `crd`) and extracts hosts and targets.
- For an ALB it creates an **alias A/AAAA** record; for other targets it creates CNAME or A records.
- Writes a companion TXT record to mark ownership so it never edits records it did not create.
- Reconciles on an interval and on events; deleting the Ingress removes the record when `policy` allows deletes.
@diagram flow
caption: Hostname to record
numbered: true
nodes:
  - "Ingress host|shop.example.com|app"
  - "ExternalDNS|reads and diffs|cp"
  - "Route 53|alias and TXT records|ext"
  - "Clients|resolve to the ALB|ok"
@h Check what it manages
```bash title="Records ExternalDNS created" lab
ZONE=$(aws route53 list-hosted-zones-by-name --dns-name example.com --query 'HostedZones[0].Id' --output text)
aws route53 list-resource-record-sets --hosted-zone-id "$ZONE" \
  --query "ResourceRecordSets[?contains(Name,'shop')].[Name,Type,AliasTarget.DNSName]" --output table
kubectl -n external-dns logs deploy/external-dns --tail=20
```
@check
Why does ExternalDNS write TXT records? || They mark ownership so it only changes records it created.
@end

@concept IAM permissions
@plain
ExternalDNS needs to list hosted zones and change record sets, and nothing else. Scope the permissions to the zones it manages.
@problem
A controller with `route53:*` on all zones could redirect your whole domain if compromised.
@does
- `route53:ChangeResourceRecordSets` on the specific hosted zone ARN.
- `route53:ListHostedZones`, `ListHostedZonesByName`, `ListResourceRecordSets`, `ListTagsForResource` on `*` (read only).
- Attach the role with Pod Identity or IRSA to the `external-dns` service account.
- For cross-account zones, assume a role in the DNS account with `--aws-assume-role`.
@diagram layers
caption: Permission scoping
layers:
  - {label: "Read", nodes: ["List zones and records|all zones|info"]}
  - {label: "Write", nodes: ["ChangeResourceRecordSets|only zone Z123|warn"]}
  - {label: "Identity", nodes: ["Pod Identity or IRSA|service account external-dns|ok"]}
@h Policy
```json title="ExternalDNS IAM policy"
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["route53:ChangeResourceRecordSets"],
      "Resource": ["arn:aws:route53:::hostedzone/Z0123456789ABCDEFGHIJ"]
    },
    {
      "Effect": "Allow",
      "Action": [
        "route53:ListHostedZones",
        "route53:ListHostedZonesByName",
        "route53:ListResourceRecordSets",
        "route53:ListTagsForResource"
      ],
      "Resource": ["*"]
    }
  ]
}
```
@check
Which action needs to be restricted to a zone ARN? || ChangeResourceRecordSets, because it modifies records.
@end

@concept Installing and configuring
@plain
Install via the official Helm chart and set the provider, domain filters, policy and TXT owner ID.
@problem
Default settings may take over records from other clusters sharing a zone.
@does
- `provider: aws`, `domainFilters` limit zones, `zoneIdFilters` pin to a zone ID.
- `txtOwnerId` must be unique per cluster so two clusters do not overwrite each other.
- `policy: upsert-only` never deletes; `sync` also deletes. Start with `upsert-only` until trusted.
- `sources` choose what to watch, `interval` the reconcile period.
@diagram cmp
caption: Policy modes
cards:
  - {h: "upsert-only", kind: ok, items: ["Create and update", "Safe default"]}
  - {h: "sync", kind: warn, items: ["Also deletes records", "Needs unique owner id"]}
  - {h: "create-only", kind: info, items: ["Never updates", "Good for audits"]}
@h Helm values
```yaml title="values.yaml for the external-dns chart"
provider:
  name: aws
env:
  - name: AWS_DEFAULT_REGION
    value: us-east-1
domainFilters:
  - example.com
policy: upsert-only
registry: txt
txtOwnerId: shop-prod
sources:
  - ingress
  - service
serviceAccount:
  create: true
  name: external-dns
```
```bash title="Install" nocheck
helm repo add external-dns https://kubernetes-sigs.github.io/external-dns/
helm upgrade --install external-dns external-dns/external-dns -n external-dns --create-namespace -f values.yaml
```
@check
Why must txtOwnerId be unique per cluster? || Otherwise one cluster may overwrite or delete records that another cluster owns.
@end

@concept Annotations, private zones and split horizon
@plain
Annotations on a Service or Ingress add hostnames, TTLs and per-record settings. Public and private hosted zones can both exist for the same name.
@problem
Internal clients should resolve internal load balancers while the internet resolves public ones.
@does
- `external-dns.alpha.kubernetes.io/hostname` sets names on a Service (Ingress reads hosts from rules).
- `external-dns.alpha.kubernetes.io/ttl` sets the TTL.
- Run two ExternalDNS instances with `--aws-zone-type=public` and `--aws-zone-type=private`, selecting Ingresses by `ingressClass` or annotation filter.
- Private zones attach to VPCs; resolution only works from associated VPCs.
@diagram flow
caption: Split horizon
nodes:
  - "Internet client|public zone|ext"
  - "Public ALB|internet-facing|cp"
  - "Internal client|private zone|app"
  - "Internal ALB|private IPs|env"
@h Service example
```yaml title="Service with hostname and TTL"
apiVersion: v1
kind: Service
metadata:
  name: payments
  namespace: shop
  annotations:
    external-dns.alpha.kubernetes.io/hostname: payments.internal.example.com
    external-dns.alpha.kubernetes.io/ttl: "60"
    service.beta.kubernetes.io/aws-load-balancer-scheme: internal
    service.beta.kubernetes.io/aws-load-balancer-nlb-target-type: ip
spec:
  type: LoadBalancer
  loadBalancerClass: service.k8s.aws/nlb
  selector:
    app: payments
  ports:
    - port: 443
      targetPort: 9090
```
@check
How can one cluster serve both public and private names? || Run separate ExternalDNS instances filtered to public and private zones.
@end

@concept Weighted records for migrations
@plain
ExternalDNS supports Route 53 routing policies through annotations, so you can send 10 percent of traffic to a new cluster.
@problem
Cutting over a whole hostname at once is risky, and DNS TTL makes rollback slow.
@does
- Annotations `external-dns.alpha.kubernetes.io/aws-weight` and `set-identifier` create weighted records.
- Each cluster sets its own weight for the same name; Route 53 splits answers proportionally.
- Lower TTL days before a cutover (for example 60 seconds).
- Failover and latency policies are also available for DR designs (check the provider docs for annotations).
@diagram flow
caption: Gradual cutover
nodes:
  - "Old cluster|weight 90|cp"
  - "New cluster|weight 10|info"
  - "Increase|50 then 100|warn"
  - "Retire old|weight 0|ok"
@h Annotations
```yaml title="Weighted record on the new cluster"
metadata:
  annotations:
    external-dns.alpha.kubernetes.io/aws-weight: "10"
    external-dns.alpha.kubernetes.io/set-identifier: green-cluster
    external-dns.alpha.kubernetes.io/ttl: "60"
```
@check
What must differ between two weighted records of the same name? || The set identifier.
@end

@concept Troubleshooting ExternalDNS
@plain
Most problems are IAM, filters or ownership conflicts, and the controller log shows which.
@problem
Records do not appear, or they flip between clusters.
@does
- `AccessDenied` in the log → fix the role or the zone ARN.
- No records created → domain filter does not match, wrong ingress class, or the Ingress has no address yet (ALB not provisioned).
- "Skipping record: owned by another" → another owner ID holds the TXT record; remove it or change the owner.
- Add `--log-level=debug` and `--dry-run` while testing.
@diagram flow
caption: Debug order
nodes:
  - "Ingress has address?|ALB ready|info"
  - "Domain filter matches?|zone|warn"
  - "IAM allows?|role|bad"
  - "TXT owner ok?|no conflicts|ok"
@h Check
```bash title="Diagnose" lab
kubectl get ingress -A
kubectl -n external-dns logs deploy/external-dns | grep -i -E 'error|denied|skip|owner' | tail
dig +short shop.example.com
```
@check
What first checks apply when a record is missing? || The Ingress must have an address, the domain must match filters, IAM must allow the change, and no other owner must hold the record.
@end
