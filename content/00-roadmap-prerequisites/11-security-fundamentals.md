---
title: Security fundamentals
minutes: 40
objectives:
  - Apply least privilege to users, roles and workloads
  - Handle secrets without committing or logging them
  - Explain hashing versus encryption and choose correctly
  - Recognise the OWASP Top 10 categories and the defence for each
---
Security is a property of every system you build, not a separate team's job. These ideas apply to Linux, Kubernetes, AWS and pipelines alike.

@concept The CIA triad and threat thinking
@plain
Security protects three things: **confidentiality** (only the right people read data), **integrity** (data is not changed without notice) and **availability** (it works when needed).
@problem
Without naming what you protect and from whom, effort goes into whatever is easy rather than whatever is risky.
@does
- A **threat model** asks four questions: what are we building, what can go wrong, what will we do about it, did we do it well.
- STRIDE is a common checklist: spoofing, tampering, repudiation, information disclosure, denial of service, elevation of privilege.
- Defence in depth means several independent layers so one failure does not lose everything.
@diagram cmp
caption: The three goals and a typical control for each
cards:
  - {h: "Confidentiality", kind: info, items: ["Encryption", "Access control"]}
  - {h: "Integrity", kind: app, items: ["Hashes and signatures", "Audit logs"]}
  - {h: "Availability", kind: ok, items: ["Redundancy", "Rate limiting and backups"]}
@h Quick threat model
```yaml title="threat-model-sketch.yaml"
asset: customer order data in PostgreSQL
actors: [internet user, compromised pod, malicious insider]
threats:
  - {type: information disclosure, path: SQL injection on /orders, control: parameterised queries}
  - {type: elevation of privilege, path: pod uses node role, control: IRSA with least privilege}
  - {type: denial of service, path: unbounded requests, control: rate limit at the ingress}
```
@check
What does defence in depth mean? || Multiple independent controls, so one failure does not expose the asset.
@end

@concept Authentication, authorization and least privilege
@plain
**Authentication** proves who you are. **Authorization** decides what you may do. **Least privilege** gives only the permissions needed, for only as long as needed.
@problem
Broad permissions turn every leaked token or buggy script into a disaster. An administrator key in a CI job is a skeleton key waiting to be stolen.
@does
- Prefer roles with short-lived credentials over long-lived keys (AWS IAM roles, Kubernetes service accounts with IRSA, OIDC for CI).
- Start with nothing and add the specific actions and resources; review unused permissions.
- Require MFA for humans. Separate accounts or namespaces for production.
@diagram flow
caption: Narrowing a permission step by step
numbered: true
nodes:
  - "Start with deny|nothing allowed|bad"
  - "Add actions|only s3:GetObject|info"
  - "Scope resources|one bucket prefix|app"
  - "Add conditions|source VPC, MFA|cp"
  - "Review|remove unused access|ok"
@h A narrow policy
```json title="IAM policy granting read of one prefix"
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": ["s3:GetObject"],
    "Resource": "arn:aws:s3:::reports-bucket/daily/*"
  }]
}
```
:::warn
Avoid `"Action": "*"` and `"Resource": "*"` together. Use IAM Access Analyzer to see what a policy really allows.
:::
@end

@concept Secrets management
@plain
A **secret** is a credential: password, API key, token, private key. It must be stored, delivered and rotated without appearing in code, images, logs or chat.
@problem
Secrets committed to Git are copied to every clone and scanned for by attackers within minutes of a public push.
@does
- Keep secrets in a manager (AWS Secrets Manager, HashiCorp Vault, SAP Credential Store) and inject at runtime.
- Kubernetes Secrets are base64 encoded, not encrypted by default. Enable encryption at rest and prefer external secret operators.
- Rotate regularly and immediately after exposure. Give each service its own credential so you can revoke one.
@diagram flow
caption: Delivering a secret at runtime
nodes:
  - "Secret store|Vault or Secrets Manager|cp"
  - "Operator|syncs with identity|info"
  - "Pod|reads a mounted file or env|app"
  - "Rotation|new value on a schedule|ok"
@h Keep them out of Git
```bash title="Scan and prevent" nocheck
git secrets --scan 2>/dev/null || echo "install git-secrets or gitleaks"
gitleaks detect --source . --no-banner       # scans history for credentials
kubectl create secret generic db --from-literal=password="$(openssl rand -base64 24)" --dry-run=client -o yaml
echo 'cGFzc3dvcmQ=' | base64 -d              # base64 is encoding, not protection
```
@check
Is a Kubernetes Secret encrypted by default? || No, it is only base64 encoded unless encryption at rest is configured.
@end

@concept Hashing versus encryption
@plain
**Hashing** turns data into a fixed fingerprint and cannot be reversed. **Encryption** scrambles data so that someone with the key can recover it.
@problem
Storing passwords with reversible encryption means one key theft exposes every password. Using the wrong tool breaks the security goal.
@does
- Use hashes for integrity (SHA-256 of a download) and for password storage with a slow, salted algorithm such as bcrypt, scrypt or Argon2. Fast hashes like plain SHA-256 are wrong for passwords.
- Symmetric encryption (AES-GCM) uses one shared key. Asymmetric encryption and signatures (RSA, ECDSA, Ed25519) use a key pair.
- MD5 and SHA-1 are broken for security use.
@diagram cmp
caption: Which tool for which job
cards:
  - {h: "Hash", kind: info, items: ["One way", "Checksums, integrity", "Passwords need bcrypt or Argon2"]}
  - {h: "Symmetric encryption", kind: app, items: ["Same key both ways", "Fast, for bulk data"]}
  - {h: "Asymmetric", kind: ok, items: ["Public and private key", "Key exchange, signatures"]}
@h Try them
```bash title="Hash and encrypt" lab
echo -n "hello" | sha256sum                      # same input, same fingerprint
echo -n "hellp" | sha256sum                      # one letter changes everything
echo "top secret" | openssl enc -aes-256-cbc -pbkdf2 -salt -pass pass:demo123 -out /tmp/s.enc
openssl enc -d -aes-256-cbc -pbkdf2 -pass pass:demo123 -in /tmp/s.enc
```
```python title="Password hashing with the standard library" lab
import hashlib, os
salt = os.urandom(16)
h = hashlib.scrypt(b"correct horse", salt=salt, n=2**14, r=8, p=1)
print(len(h), "byte hash; the salt makes identical passwords differ")
```
@check
Why not store passwords with SHA-256? || It is fast, so attackers can test billions of guesses per second; use a slow salted function.
@end

@concept TLS and certificates in practice
@plain
TLS encrypts traffic between two parties, and certificates tie a public key to a name. Operators mostly deal with expiry, chains and renewal.
@problem
An expired or mismatched certificate takes a site down as completely as a crashed server, and it happens on a known date.
@does
- Use automated issuance (ACME, Let's Encrypt, cert-manager) and monitor days until expiry.
- Internal traffic should also be encrypted, optionally with mutual TLS in a service mesh.
- Disable old protocols; TLS 1.2 is the minimum for most policies, TLS 1.3 preferred.
@diagram flow
caption: Automatic certificate lifecycle
nodes:
  - "Request|cert-manager asks the CA|app"
  - "Challenge|prove domain control|info"
  - "Issue|certificate stored as Secret|ok"
  - "Renew|well before expiry|cp"
@h Check an expiry
```bash title="Days until a certificate expires" lab
host=example.com
end=$(echo | openssl s_client -connect $host:443 -servername $host 2>/dev/null | openssl x509 -noout -enddate | cut -d= -f2)
echo "expires: $end"
echo $(( ( $(date -d "$end" +%s 2>/dev/null || date -j -f "%b %d %T %Y %Z" "$end" +%s) - $(date +%s) ) / 86400 )) days left
```
@end

@concept The OWASP Top 10
@plain
OWASP publishes a ranked list of the most critical web application risks. The edition changes, so check the current list at owasp.org. The 2021 edition names these ten.
@problem
Teams repeat the same classes of mistakes. A shared list gives a common checklist for design, code review and testing.
@does
- A01 Broken access control: users act outside their rights. Enforce checks on the server for every request.
- A02 Cryptographic failures: weak or missing encryption. Use TLS and modern algorithms.
- A03 Injection: untrusted data becomes code (SQL, shell). Use parameterised queries.
- A04 Insecure design; A05 Security misconfiguration (default passwords, open buckets); A06 Vulnerable and outdated components (scan dependencies).
- A07 Identification and authentication failures; A08 Software and data integrity failures (unsigned updates, CI compromise); A09 Logging and monitoring failures; A10 Server side request forgery.
@diagram layers
caption: Where each risk is usually stopped
layers:
  - {label: "Design", nodes: ["A04 Insecure design|threat model|plain"]}
  - {label: "Code", nodes: ["A01 Access control|A03 Injection|app", "A07 Auth failures|A10 SSRF|app"]}
  - {label: "Build and run", nodes: ["A05 Misconfiguration|A06 Old components|env", "A08 Integrity|A09 Logging|env"]}
@h Injection, the classic
```python title="Unsafe versus safe query" lab
import sqlite3
db = sqlite3.connect(":memory:")
db.execute("create table users (name text, secret text)")
db.execute("insert into users values ('asha', 's3cret')")
evil = "x' OR '1'='1"
unsafe = db.execute(f"select * from users where name = '{evil}'").fetchall()
safe = db.execute("select * from users where name = ?", (evil,)).fetchall()
print("unsafe returns", unsafe)     # leaks every row
print("safe returns", safe)         # empty
```
@check
What is the standard fix for SQL injection? || Parameterised queries so data can never be interpreted as SQL.
@end

@concept Security in the pipeline and cluster
@plain
Shift checks left into code review and CI, and keep guards at run time in the cluster.
@problem
A scan done once before release finds nothing about the dependency published next week. A cluster with permissive defaults lets one compromised pod roam.
@does
- CI: dependency and image scanning (Trivy, Grype), secret scanning, static analysis, signed images and an SBOM.
- Cluster: run as non root, drop capabilities, read-only root filesystem, NetworkPolicy default deny, Pod Security Admission, minimal RBAC.
- Patch quickly: track CVEs for base images and rebuild regularly.
@diagram flow
caption: Controls from commit to runtime
nodes:
  - "Commit|secret scan|plain"
  - "Build|dependency and image scan|info"
  - "Sign|image signature and SBOM|app"
  - "Admit|policy checks in cluster|cp"
  - "Run|restricted pod, network policy|ok"
@h A restricted pod
```yaml title="Secure container settings"
apiVersion: v1
kind: Pod
metadata:
  name: shop
spec:
  securityContext:
    runAsNonRoot: true
    seccompProfile:
      type: RuntimeDefault
  containers:
    - name: app
      image: registry.example.com/shop:1.4.2
      securityContext:
        allowPrivilegeEscalation: false
        readOnlyRootFilesystem: true
        capabilities:
          drop: ["ALL"]
```
:::note
Pin images by version or digest, never by `latest`, so what you scanned is what runs.
:::
@end
