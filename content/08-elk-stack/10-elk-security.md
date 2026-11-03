---
title: Securing the Elastic Stack
minutes: 45
objectives:
  - Enable TLS and authentication across nodes, collectors and Kibana
  - Use API keys, roles and audit logging with least privilege
  - Protect sensitive data in logs and the snapshot repository
---
Logs contain tokens, personal data and the details attackers want. An open Elasticsearch has repeatedly been the cause of public data leaks, so security is not optional.

@concept Threats to a logging platform
@plain
A logging cluster is a rich target: it stores everything your systems say, it accepts data from many hosts, and it can be searched and deleted through an API.
@problem
Teams often secure applications and forget that the log store holds copies of their secrets and user data.
@does
- Exposure: an Elasticsearch port open to the internet without authentication.
- Data leakage: passwords, tokens and personal data written into logs.
- Tampering: an attacker with a compromised host deletes or alters logs to hide tracks.
- Over-broad access: every developer a superuser.
@diagram cmp
caption: Threats and answers
cards:
  - {h: "Exposure", kind: bad, items: ["Open port 9200", "Fix with TLS, auth, private network"]}
  - {h: "Sensitive data", kind: warn, items: ["Secrets in log lines", "Fix with masking and field security"]}
  - {h: "Tampering", kind: bad, items: ["Delete or edit logs", "Fix with write-only agent keys, snapshots"]}
  - {h: "Over-access", kind: warn, items: ["Everyone superuser", "Fix with roles and SSO"]}
@end

@concept TLS and authentication by default
@plain
Since Elasticsearch 8, security is on by default: the first start generates certificates and a password for the `elastic` user. Transport (between nodes) and HTTP (clients) are encrypted with TLS.
@problem
Plain-text traffic can be read or modified on the network, and unauthenticated access means anyone reachable can read and delete.
@does
- `xpack.security.enabled: true`, `xpack.security.transport.ssl` and `xpack.security.http.ssl` are enabled with auto-generated certificates on first start of a self-managed install.
- ECK manages the CA and per-node certificates for you; you can replace the HTTP certificate with your own (cert-manager).
- Clients (Filebeat, Kibana, Logstash) must trust the CA: set `ssl.certificate_authorities`.
- Never disable security to "make it work"; fix the certificate trust instead.
@diagram flow
caption: Trust chain
nodes:
  - "CA certificate|trusted by clients|cp"
  - "Node certificates|signed by CA|info"
  - "Filebeat and Kibana|verify the chain|app"
  - "Encrypted session|ok|ok"
@h Test the CA trust
```bash title="Verify TLS" lab
curl --cacert ca.crt -u elastic:$ES_PASSWORD https://es.example.internal:9200/
openssl s_client -connect es.example.internal:9200 -CAfile ca.crt </dev/null 2>/dev/null | grep -E "Verify return|subject"
```
@end

@concept API keys and least privilege for collectors
@plain
An API key is a credential tied to a role descriptor. Give each collector its own key that can only write to its own data streams.
@problem
If Filebeat on a compromised host holds the `elastic` superuser password, an attacker can read and delete every log.
@does
- Create a role with `create_doc` (and `auto_configure` or `create_index` when needed) on `logs-*` only; no read and no delete.
- Create an API key with that role descriptor; rotate on a schedule; revoke when a host is retired.
- Store keys in Kubernetes Secrets; inject as environment variables.
- Per-environment keys limit the blast radius.
@diagram flow
caption: Write-only collector
nodes:
  - "Filebeat|API key, create_doc only|env"
  - "Elasticsearch|logs-* data streams|cp"
  - "Attacker on host|cannot read or delete|bad"
@h Create the key
```json
{
  "name": "filebeat-prod-cluster-a",
  "expiration": "90d",
  "role_descriptors": {
    "filebeat_writer": {
      "cluster": ["monitor", "read_ilm"],
      "indices": [
        {
          "names": ["logs-*-prod", "filebeat-*"],
          "privileges": ["auto_configure", "create_doc", "view_index_metadata"]
        }
      ]
    }
  }
}
```
:::note
Send with `POST _security/api_key`. Required privileges can differ by Beat version; check the current Filebeat documentation.
:::
@end

@concept Roles, document and field level security
@plain
Roles combine cluster, index and application privileges. **Document level security** limits which documents a role sees; **field level security** limits which fields.
@problem
A single log stream contains data from several teams and fields such as email addresses that many users should not see.
@does
- Row filter example: role query `{"term": {"kubernetes.namespace": "payments"}}`.
- Hide `user.email` and `client.ip` from general viewers.
- Pair with Kibana spaces so the interface matches the data access.
- Check effective privileges with `GET _security/user/_privileges` and the has-privileges API.
@diagram layers
caption: Narrowing access in layers
layers:
  - {label: "Index", nodes: ["logs-* read|which indices|info"]}
  - {label: "Document", nodes: ["namespace is payments|which rows|warn"]}
  - {label: "Field", nodes: ["except user.email|which columns|bad"]}
@h Role with document and field security
```json
{
  "indices": [
    {
      "names": ["logs-*"],
      "privileges": ["read"],
      "query": { "term": { "kubernetes.namespace": "payments" } },
      "field_security": { "grant": ["*"], "except": ["user.email", "client.ip"] }
    }
  ]
}
```
@end

@concept SSO with SAML or OIDC
@plain
People should log in with your corporate identity provider, not with local Elasticsearch passwords. Elasticsearch supports SAML, OpenID Connect, LDAP and more as realms.
@problem
Local accounts bypass joiner and leaver processes, MFA and central audit.
@does
- Configure a realm in `elasticsearch.yml` (or ECK `auth` section) and a Kibana provider.
- Role mappings translate IdP groups or claims into Elasticsearch roles.
- SSO realms may need a paid licence tier; check current subscription levels.
- Keep one break-glass local admin in a sealed Secret.
@diagram flow
caption: Group to role
nodes:
  - "Corporate IdP|SAML or OIDC|ext"
  - "Elasticsearch realm|validates assertion|cp"
  - "Role mapping|group payments-dev to payments-reader|warn"
  - "Kibana session|ok|ok"
@end

@concept Audit logging and masking sensitive data
@plain
Audit logging records who accessed or changed what in the cluster. Separately, you should stop secrets and personal data from entering logs.
@problem
After an incident you must prove who read data, and regulators expect personal data to be minimised.
@does
- `xpack.security.audit.enabled: true` writes events such as authentication failures and access denied (licence dependent); ship the audit log to a separate cluster so a compromise cannot erase it.
- Mask at the source first: application loggers, then agent processors (`drop_fields`, `script`), then ingest `redact` or `gsub` processors.
- The `redact` ingest processor can replace Grok patterns (for example email addresses) with a marker.
- Test the pipeline with `_simulate` using real sample lines.
@diagram flow
caption: Defence in depth for sensitive data
nodes:
  - "App logger|do not log it|app"
  - "Agent|drop_fields|env"
  - "Ingest pipeline|redact processor|warn"
  - "Stored log|masked|ok"
@h Redact processor
```json
{
  "processors": [
    {
      "redact": {
        "field": "message",
        "patterns": ["%{EMAILADDRESS:EMAIL}", "%{IP:IP_ADDRESS}"],
        "ignore_missing": true
      }
    },
    {
      "gsub": {
        "field": "message",
        "pattern": "(?i)(authorization: bearer )[a-z0-9._-]+",
        "replacement": "$1[REDACTED]",
        "ignore_missing": true
      }
    }
  ]
}
```
:::note
Send with `PUT _ingest/pipeline/mask-pii`. The redact processor needs a suitable licence in some versions; check the current docs.
:::
@end

@concept Network and snapshot security
@plain
Keep the cluster on private networks, limit who can reach ports 9200 and 9300, and protect the snapshot bucket as strictly as the cluster.
@problem
A good cluster configuration is undone by a world-readable S3 bucket holding the snapshots.
@does
- Kubernetes: ClusterIP services, NetworkPolicies allowing only Kibana, collectors and Logstash to reach 9200; Ingress with TLS for Kibana only.
- AWS: private subnets, security groups on 9200/9300/5601, no public IPs.
- S3 snapshot bucket: block public access, SSE-KMS encryption, bucket policy limited to the IRSA role, object lock or versioning for tamper resistance (check repository compatibility with versioning).
- Keep Elasticsearch and plugin versions patched; subscribe to Elastic security announcements.
@diagram layers
caption: Layers of network protection
layers:
  - {label: "Edge", nodes: ["Ingress with TLS and SSO|Kibana only|info"]}
  - {label: "Cluster", nodes: ["NetworkPolicy|9200 from collectors only|warn", "Private subnets|no public IPs|warn"]}
  - {label: "Backup", nodes: ["S3 bucket|KMS, no public access, scoped role|ok"]}
@h NetworkPolicy
```yaml title="networkpolicy.yaml"
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: es-allow-clients
  namespace: logging
spec:
  podSelector:
    matchLabels:
      elasticsearch.k8s.elastic.co/cluster-name: logs
  policyTypes: [Ingress]
  ingress:
    - from:
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: kibana
        - podSelector:
            matchLabels:
              beat.k8s.elastic.co/name: filebeat
        - podSelector:
            matchLabels:
              elasticsearch.k8s.elastic.co/cluster-name: logs
      ports:
        - port: 9200
        - port: 9300
```
@end
