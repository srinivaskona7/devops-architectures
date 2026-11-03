---
title: TLS and certificates with openssl and ACME
minutes: 45
objectives:
  - Read a certificate and verify a chain with openssl
  - Create a private key, a certificate request and a private CA for testing
  - Obtain and renew certificates automatically with ACME
  - Diagnose the common certificate errors
---
Certificates fail on a predictable date and the error messages are cryptic. These concepts give you the tools to inspect, issue and automate them. Output formats differ slightly between OpenSSL 1.1, 3.x and LibreSSL (the macOS default), so check `openssl version`.

@concept What is inside a certificate
@plain
An X.509 certificate is a signed statement: "this public key belongs to these names, valid between these dates, issued by this authority".
@problem
Clients need a way to trust a key for a server they have never met. Signatures by a trusted authority make that possible.
@does
- Fields that matter: Subject, Issuer, validity dates, Subject Alternative Names (SAN), key usage, and the signature.
- Modern clients check the **SAN** list for the hostname and ignore the old Common Name.
- A **chain** links the leaf to an intermediate to a root that is in the client's trust store. Servers must send the leaf plus intermediates.
@diagram flow
caption: A chain of trust
nodes:
  - "Root CA|in the trust store|cp"
  - "Intermediate CA|signed by the root|info"
  - "Leaf certificate|your server name|app"
@h Look inside
```bash title="Decode a live certificate" lab
echo | openssl s_client -connect example.com:443 -servername example.com 2>/dev/null \
  | openssl x509 -noout -subject -issuer -dates -ext subjectAltName 2>/dev/null \
  || echo "your openssl lacks -ext; use: openssl x509 -noout -text | grep -A1 'Alternative'"
echo | openssl s_client -connect example.com:443 -servername example.com -showcerts 2>/dev/null | grep -E '^( [0-9] s:|   i:)'
```
@check
Which field does the browser match the hostname against? || The Subject Alternative Name list.
@end

@concept Keys and certificate signing requests
@plain
You generate a private key locally and a **CSR**, a request containing the public key and the names you want. The CA signs it and returns the certificate. The private key never travels.
@problem
If the CA generated your key, they would also have a copy of it.
@does
- Use ECDSA P-256 or RSA 2048 or larger. Keep key files readable only by the service (`chmod 600`).
- Provide SANs in the request, not only a Common Name.
- Keep the key when renewing only if policy allows; rotating keys on renewal is better practice.
@diagram flow
caption: Request and issuance
numbered: true
nodes:
  - "Generate key|stays on your host|app"
  - "Create CSR|public key and names|info"
  - "CA validates|you control the names|cp"
  - "Certificate|returned, install with key|ok"
@h Create them
```bash title="Key and CSR with SANs" lab
cd /tmp && openssl ecparam -name prime256v1 -genkey -noout -out shop.key
openssl req -new -key shop.key -subj "/CN=shop.example.internal" \
  -addext "subjectAltName=DNS:shop.example.internal,DNS:shop" -out shop.csr
openssl req -in shop.csr -noout -subject -verify
chmod 600 shop.key && ls -l shop.key
```
@check
Which file must never be sent to the CA? || The private key.
@end

@concept A private CA for test and internal use
@plain
For labs and internal services you can act as your own CA: create a root key and certificate, then sign leaf certificates and add the root to the machines that must trust it.
@problem
Public CAs will not issue for internal names like `shop.example.internal`, and self-signed leaf certificates train people to click through warnings.
@does
- The root key is the crown jewel. In production keep it offline or in an HSM and use an intermediate for issuing.
- Clients must trust the root: copy to the OS trust store or pass `--cacert`.
- Kubernetes tools such as cert-manager (CA issuer) and Vault PKI automate this.
@diagram layers
caption: Roles in a private PKI
layers:
  - {label: "Offline", nodes: ["Root CA|signs intermediates only|cp"]}
  - {label: "Online", nodes: ["Issuing CA|signs service certificates|info"]}
  - {label: "Services", nodes: ["shop|leaf|app", "billing|leaf|app"]}
@h Sign a leaf
```bash title="Mini CA" lab
cd /tmp
openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -nodes -days 365 \
  -keyout ca.key -out ca.crt -subj "/CN=Lab Root CA"
printf "subjectAltName=DNS:shop.example.internal\nbasicConstraints=CA:FALSE\n" > leaf.ext
openssl x509 -req -in shop.csr -CA ca.crt -CAkey ca.key -CAcreateserial -days 90 -extfile leaf.ext -out shop.crt
openssl verify -CAfile ca.crt shop.crt
```
:::warn
Never reuse a lab CA in production, and never add one to a shared trust store.
:::
@check
How does a client trust the leaf from the mini CA? || Add ca.crt to its trust store or point the client at it explicitly.
@end

@concept Verifying chains and serving them
@plain
Many outages are "works in my browser, fails in curl". The server sent only the leaf and the browser fetched the missing intermediate, but other clients do not.
@problem
Incomplete chains cause errors such as "unable to get local issuer certificate".
@does
- Serve the full chain: leaf first, then intermediates (the file called fullchain.pem).
- `openssl verify -untrusted intermediates.pem leaf.pem` tests a chain offline.
- `openssl s_client -showcerts` shows what the server really sends.
@diagram cmp
caption: Complete versus incomplete chains
cards:
  - {h: "Leaf only", kind: bad, items: ["Browsers may recover", "curl and Java fail"]}
  - {h: "Leaf plus intermediate", kind: ok, items: ["All clients can build the chain to a trusted root"]}
@h Check
```bash title="Test with and without chain" lab
openssl verify -CAfile /etc/ssl/cert.pem /tmp/shop.crt 2>&1 | head -2        # fails: lab CA not trusted
openssl verify -CAfile /tmp/ca.crt /tmp/shop.crt
curl -sv https://example.com -o /dev/null 2>&1 | grep -E 'SSL certificate verify|issuer'
```
@check
What does "unable to get local issuer certificate" usually mean? || The client cannot build a path to a trusted root, often a missing intermediate.
@end

@concept ACME and Let's Encrypt
@plain
**ACME** is a protocol that lets software prove control of a domain to a CA and receive a certificate automatically. Let's Encrypt is the best known free CA using it.
@problem
Manually buying and installing certificates leads to expiry outages. Lifetimes are also being shortened across the industry, so automation is mandatory.
@does
- **HTTP-01**: place a token at `/.well-known/acme-challenge/` on port 80. Cannot issue wildcards.
- **DNS-01**: create a TXT record `_acme-challenge.name`. Works for wildcards and hosts without public HTTP.
- Clients: certbot, acme.sh, Caddy (built in), cert-manager in Kubernetes.
- Use the staging endpoint while testing to avoid rate limits. Check the current Let's Encrypt documentation for limits and lifetimes.
@diagram seq
caption: HTTP-01 challenge
actors: ["Client|certbot or cert-manager|app", "CA|Let's Encrypt|ext", "Web server|port 80|env"]
steps:
  - "0>1: order for shop.example.com | req"
  - "1>0: token to publish | req"
  - "0>2: publish token file | req"
  - "1>2: fetch the token | req"
  - "1>0: certificate issued | resp"
@h Use it
```bash title="certbot with the staging CA" nocheck
sudo certbot certonly --webroot -w /var/www/html -d shop.example.com --staging
sudo certbot renew --dry-run
systemctl list-timers | grep -i certbot
```
```yaml title="cert-manager ClusterIssuer for Let's Encrypt staging"
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-staging
spec:
  acme:
    server: https://acme-staging-v02.api.letsencrypt.org/directory
    email: ops@example.com
    privateKeySecretRef:
      name: letsencrypt-staging-key
    solvers:
      - http01:
          ingress:
            ingressClassName: nginx
```
@check
Which challenge supports wildcard names? || DNS-01.
@end

@concept Monitoring expiry and renewal
@plain
Automation fails silently: a DNS token expires, a firewall blocks port 80. Alert on days remaining, not on renewal job success alone.
@problem
The first sign of failure is a customer seeing a browser warning.
@does
- Alert at 21 days and page at 7 days, assuming renewal begins at 30 days before expiry.
- Blackbox exporter exposes `probe_ssl_earliest_cert_expiry`; cert-manager exposes `certmanager_certificate_expiration_timestamp_seconds`.
- Test the real endpoint, including load balancers and CDNs, not only the file on disk.
@diagram flow
caption: Layered expiry checks
nodes:
  - "Renewal job|certbot or cert-manager|app"
  - "Metrics|days until expiry|info"
  - "Alert|21 days warn, 7 days page|warn"
  - "Probe endpoint|what clients really see|ok"
@h Alert rule
```yaml title="Prometheus rule for expiring certificates"
groups:
  - name: certs
    rules:
      - alert: CertificateExpiringSoon
        expr: (probe_ssl_earliest_cert_expiry - time()) / 86400 < 21
        for: 1h
        labels: {severity: warning}
        annotations:
          summary: "Certificate for {{ $labels.instance }} expires in under 21 days"
```
```bash title="Shell check" lab
openssl x509 -checkend $((21*86400)) -noout -in /tmp/shop.crt && echo "valid for 21 more days" || echo "expires within 21 days"
```
@end

@concept Common errors and mutual TLS
@plain
Most certificate errors are one of five: expired, wrong name, unknown issuer, wrong time on the client, or protocol mismatch. **Mutual TLS** adds a client certificate so both sides prove identity.
@problem
Without a systematic reading of the error you waste hours regenerating certificates that were never the problem.
@does
- Expired: check `notAfter`. Name mismatch: compare the URL to the SAN. Unknown issuer: chain or missing root. Clock skew: check `date` on the client.
- mTLS: the server requests a client certificate and checks it against its own CA. Service meshes (Istio, Linkerd) automate it between pods.
- Test mTLS with `curl --cert client.crt --key client.key --cacert ca.crt`.
@diagram cmp
caption: Error to cause
cards:
  - {h: "certificate has expired", kind: bad, items: ["Check notAfter", "Check client clock too"]}
  - {h: "hostname mismatch", kind: warn, items: ["URL not in SAN", "Check SNI and virtual host"]}
  - {h: "unknown ca", kind: info, items: ["Missing intermediate or root", "Add CA to trust store"]}
@h Quick triage
```bash title="Triage script" lab
host=example.com
echo | openssl s_client -connect "$host:443" -servername "$host" 2>&1 | grep -E 'Verify return code|verify error'
echo | openssl s_client -connect "$host:443" -servername "$host" 2>/dev/null | openssl x509 -noout -enddate
date -u
```
:::tip
Always pass `-servername`. Without SNI a shared endpoint returns a default certificate for a different name.
:::
@check
What does mutual TLS add? || The client also presents a certificate, so the server can authenticate it.
@end
