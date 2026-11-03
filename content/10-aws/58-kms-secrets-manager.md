---
title: KMS and Secrets Manager
minutes: 45
objectives:
  - Explain envelope encryption and choose between AWS managed and customer managed keys
  - Write key policies and grants that separate administrators from users
  - Store, rotate and retrieve secrets with Secrets Manager and Parameter Store
---
Encryption keys and secrets are the most sensitive objects in an account. KMS holds the keys; Secrets Manager holds credentials and uses KMS to protect them.

@concept Envelope encryption
@plain
KMS never encrypts your large data directly. It encrypts a small **data key**; the data key encrypts your data. You store the encrypted data key beside the data.
@problem
Sending gigabytes to a key service is slow and expensive, and you do not want plaintext keys saved anywhere.
@does
- `GenerateDataKey` returns a plaintext data key and the same key encrypted under a KMS key.
- The service encrypts data with the plaintext key, discards it, and stores the encrypted copy.
- To read, the service calls `Decrypt` on the encrypted data key (KMS checks the key policy and IAM) and decrypts the data locally.
- S3, EBS, RDS, EKS secrets and Secrets Manager all use this pattern.
@diagram seq
caption: Writing an encrypted object
actors: ["Service|S3 or EBS|app", "KMS|key in HSM|cp"]
steps:
  - "0>1: GenerateDataKey | req"
  - "1>0: plaintext key and encrypted key | resp"
  - "note 0..0: encrypt data, drop plaintext key"
  - "0>1: later Decrypt encrypted key | tls"
  - "1>0: plaintext key if policy allows | resp"
@h Try it
```bash title="Create a key and encrypt a small value" lab
KEY=$(aws kms create-key --description "shop demo" --query KeyMetadata.KeyId --output text)
aws kms create-alias --alias-name alias/shop-demo --target-key-id "$KEY"
aws kms encrypt --key-id alias/shop-demo --plaintext fileb://<(printf 'hello') \
  --query CiphertextBlob --output text > cipher.b64
base64 --decode < cipher.b64 > cipher.bin
aws kms decrypt --ciphertext-blob fileb://cipher.bin --query Plaintext --output text | base64 --decode
```
@check
Why use data keys instead of sending data to KMS? || KMS limits request size and rate; a local data key encrypts bulk data quickly and KMS protects only the small key.
@end

@concept Key types and rotation
@plain
KMS keys come as AWS owned, AWS managed (`aws/s3`), or customer managed keys (CMKs). You get full control only with customer managed keys.
@problem
Default keys cannot be shared across accounts, disabled on demand, or given a custom policy, so they fail many compliance requirements.
@does
- **AWS managed keys** rotate automatically (yearly) and cost nothing per key, but policy is fixed.
- **Customer managed keys** have your own key policy, aliases, tags, optional automatic rotation (a period between 90 and 2560 days; check the current limits) and per-key monthly cost plus request charges.
- Rotation keeps the same key ID; older key material stays to decrypt old data.
- Symmetric keys (AES-256-GCM) are standard; asymmetric and HMAC keys exist for signing and verification.
- Multi-Region keys share key material across Regions for DR and global tables.
@diagram cmp
caption: Which key
cards:
  - {h: "AWS owned", kind: info, items: ["Invisible to you", "No control or audit"]}
  - {h: "AWS managed", kind: app, items: ["aws/rds, aws/ebs", "Auto rotation, fixed policy"]}
  - {h: "Customer managed", kind: ok, items: ["Your policy and tags", "Cross-account sharing", "Monthly fee"]}
@h Enable rotation
```bash title="Rotate a CMK yearly" nocheck
aws kms enable-key-rotation --key-id alias/shop-demo --rotation-period-in-days 365
aws kms get-key-rotation-status --key-id alias/shop-demo
```
@check
Does rotation change the key ID? || No; the key ID and ARN stay the same and old material is retained for decryption.
@end

@concept Key policies and grants
@plain
Every KMS key has a **key policy**, and it is the primary access control. IAM policies only work if the key policy allows IAM to control the key.
@problem
Without a clear split, the people who administer keys can also decrypt all data, and an admin leaving takes knowledge with them.
@does
- The default statement lets the account root enable IAM policies for the key.
- Separate statements: **key administrators** (create, disable, schedule deletion) versus **key users** (Encrypt, Decrypt, GenerateDataKey).
- `kms:ViaService` limits use to a specific service (for example only via RDS in us-east-1).
- **Grants** give temporary, narrow permissions to AWS services such as EBS.
- Schedule deletion has a 7 to 30 day wait; deleting a key makes data unrecoverable.
@diagram layers
caption: Separation of duties
layers:
  - {label: "Key policy", nodes: ["Admins|manage lifecycle, no Decrypt|warn", "Users|Encrypt and Decrypt|ok", "Services|via grants|info"]}
  - {label: "Guardrails", nodes: ["kms:ViaService|only from RDS|cp", "Encryption context|bind to resource|cp"]}
@h Policy
```json title="Key policy for the shop RDS key"
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "EnableIAM",
      "Effect": "Allow",
      "Principal": {"AWS": "arn:aws:iam::111122223333:root"},
      "Action": "kms:*",
      "Resource": "*"
    },
    {
      "Sid": "AllowUseViaRds",
      "Effect": "Allow",
      "Principal": {"AWS": "arn:aws:iam::111122223333:role/ShopDbRole"},
      "Action": ["kms:Encrypt", "kms:Decrypt", "kms:GenerateDataKey*", "kms:DescribeKey"],
      "Resource": "*",
      "Condition": {"StringEquals": {"kms:ViaService": "rds.us-east-1.amazonaws.com"}}
    }
  ]
}
```
:::danger
Never remove the account root statement from a key policy unless you are certain another principal can administer it; an unmanageable key cannot be repaired without AWS Support.
:::
@check
What does kms:ViaService do? || It restricts key use to requests made through the named AWS service.
@end

@concept Secrets Manager basics
@plain
Secrets Manager stores credentials, API keys and certificates as versioned secrets, encrypted with KMS, with fine-grained IAM and optional automatic rotation.
@problem
Hard-coded passwords in code, environment files or Terraform state leak and are never rotated.
@does
- A secret holds a string or JSON, with staging labels `AWSCURRENT`, `AWSPREVIOUS`, `AWSPENDING`.
- Pay per secret per month plus per 10,000 API calls (check current pricing).
- Resource policies allow cross-account access; replication copies a secret to other Regions.
- Retrieval via SDK, CLI, ESO, CSI driver or Lambda extension; cache values in the client to cut cost and latency.
- RDS and Aurora can create and rotate the master secret for you (`--manage-master-user-password`).
@diagram flow
caption: App retrieving a secret
nodes:
  - "Pod role|Pod Identity or IRSA|app"
  - "Secrets Manager|GetSecretValue|cp"
  - "KMS|Decrypt|ext"
  - "App|uses credential|ok"
@h CLI
```bash title="Create, read and update a secret" lab
aws secretsmanager create-secret --name shop/api-key --secret-string '{"key":"CHANGE_ME"}'
aws secretsmanager get-secret-value --secret-id shop/api-key --query SecretString --output text
aws secretsmanager put-secret-value --secret-id shop/api-key --secret-string '{"key":"NEW_VALUE"}'
aws secretsmanager describe-secret --secret-id shop/api-key --query VersionIdsToStages
```
@check
Which staging label marks the active version? || AWSCURRENT.
@end

@concept Rotation with Lambda
@plain
Rotation is a Lambda function that runs four steps: create a pending secret, set it in the database, test it, then finish by promoting it to current.
@problem
Manual rotation is skipped. Automated rotation limits exposure from leaked credentials.
@does
- AWS provides rotation templates for RDS, Aurora, Redshift, DocumentDB; custom Lambdas cover anything else.
- **Single user** strategy changes one user's password (short window of failures); **alternating users** keeps two users and swaps them (no downtime).
- The Lambda needs network access to the database and to Secrets Manager (VPC endpoint).
- Applications must re-read the secret on authentication failures or on a short cache TTL.
@diagram flow
caption: The four rotation steps
numbered: true
nodes:
  - "createSecret|new pending version|info"
  - "setSecret|apply to database|app"
  - "testSecret|log in with it|warn"
  - "finishSecret|AWSCURRENT moves|ok"
@h Schedule
```bash title="Rotate every 30 days" nocheck
aws secretsmanager rotate-secret --secret-id shop/db \
  --rotation-lambda-arn arn:aws:lambda:us-east-1:111122223333:function:SecretsManagerRDSPostgreSQLRotationMultiUser \
  --rotation-rules ScheduleExpression="rate(30 days)"
```
@check
Which rotation strategy avoids downtime? || Alternating users, because one valid user always remains while the other changes.
@end

@concept Parameter Store versus Secrets Manager
@plain
Systems Manager Parameter Store holds configuration and, with SecureString, small secrets. It is cheaper but lacks built-in rotation.
@problem
Not every value is a secret. Paying Secrets Manager prices for feature flags and endpoints wastes money.
@does
- Standard parameters are free (up to a quota); advanced parameters cost more and allow larger values and policies.
- `SecureString` encrypts with KMS. Paths like `/shop/prod/db/host` allow hierarchical IAM.
- Use Parameter Store for configuration and non-rotating secrets; Secrets Manager for credentials that rotate or need cross-account and replication.
- Parameter Store can also reference Secrets Manager secrets by path `/aws/reference/secretsmanager/<name>`.
@diagram cmp
caption: Choosing a store
cards:
  - {h: "Parameter Store", kind: info, items: ["Cheap or free", "Config and simple secrets", "No built-in rotation"]}
  - {h: "Secrets Manager", kind: ok, items: ["Rotation, replication", "Cross-account policies", "Per secret price"]}
@h Use
```bash title="Parameter Store basics" nocheck
aws ssm put-parameter --name /shop/prod/db/host --type String --value shop-db.example.internal
aws ssm put-parameter --name /shop/prod/feature-key --type SecureString --value CHANGE_ME
aws ssm get-parameters-by-path --path /shop/prod --with-decryption --recursive
```
@check
When choose Secrets Manager over Parameter Store? || When you need automatic rotation, replication or cross-account sharing of credentials.
@end
