---
title: Architecture scenarios part two
minutes: 60
objectives:
  - Design a data lake, multi-Region active-active, SaaS multi-tenant and hybrid architecture
  - Reason about data consistency, tenant isolation and connectivity trade-offs
  - Produce a decision record and a failure review for each design
---
The second set of four scenarios covers larger and more constrained designs. As before, numbers are worked explicitly and prices are left symbolic.

@concept Scenario 5 Data lake
@plain
Collect application logs, database exports and clickstream for analytics by many teams with access control.
@problem
Siloed exports and unmanaged buckets give no governance or shared catalog.
@does
- Ingest: Firehose for streams, DMS or exports for databases, S3 for files.
- Storage zones in S3: raw, cleaned, curated, with Parquet partitioned by date.
- Catalog and governance: Glue Data Catalog and Lake Formation (LF-tags for PII).
- Query: Athena for ad hoc, Redshift Serverless for heavy BI.
- Capacity: 500 GB per day raw; Parquet at about 4 to 1 compression gives roughly 125 GB per day curated, which is 125 x 365 = 45,625 GB, about 45.6 TB per year (measure your real ratio).
@diagram flow
caption: Lake
nodes:
  - "Sources|apps, DBs, streams|ext"
  - "Ingest|Firehose and DMS|info"
  - "S3 zones|raw, cleaned, curated|ok"
  - "Athena and BI|governed access|app"
@h Verify
```python title="lake.py"
raw_gb_day, ratio = 500, 4
curated = raw_gb_day / ratio
print(curated, curated * 365, curated * 365 / 1000)
```
@check
What gives column level access control on the lake? || Lake Formation grants and LF-tags.
@end

@concept Scenario 6 Multi-Region active-active
@plain
A global service must keep running if a whole Region fails and serve users from the nearest Region.
@problem
A single Region is a single failure domain, and cross-Region distance adds latency.
@does
- Traffic: Route 53 latency routing with health checks or Global Accelerator.
- Compute: identical stacks in two Regions, deployed from the same pipeline.
- Data: DynamoDB global tables (multi-writer, last writer wins) or Aurora Global Database (single writer, fast cross-Region replicas); choose by write pattern.
- Design for conflicts: use idempotent writes, per-user home Region, or CRDT-like merges.
- Test with FIS and game days; cost is roughly double plus replication transfer.
@diagram flow
caption: Two Regions
nodes:
  - "Users|global|ext"
  - "Global Accelerator|static IPs|cp"
  - "Region A stack|serves traffic|app"
  - "Region B stack|serves traffic|app"
  - "Global table|replicated data|ok"
@h Global table
```hcl title="global-table.tf"
resource "aws_dynamodb_table" "sessions" {
  name             = "sessions"
  billing_mode     = "PAY_PER_REQUEST"
  hash_key         = "id"
  stream_enabled   = true
  stream_view_type = "NEW_AND_OLD_IMAGES"
  attribute {
    name = "id"
    type = "S"
  }
  replica {
    region_name = "us-east-1"
  }
}
```
@check
What is the main data risk with multi-writer replication? || Conflicting concurrent writes to the same item; last writer wins unless you design around it.
@end

@concept Scenario 7 SaaS multi-tenant
@plain
A SaaS product serves hundreds of customers from shared infrastructure with strict data isolation and per-tenant billing.
@problem
Per-customer stacks do not scale operationally, while fully shared stacks risk cross-tenant leaks and noisy neighbours.
@does
- Models: **silo** (account or stack per tenant), **pool** (shared with tenant ID on every row), **bridge** (mix).
- Identity: Cognito or an IdP issues tokens with a `tenant_id` claim; the API uses it for every data access.
- Data isolation: DynamoDB with tenant ID as partition key prefix and IAM conditions via `dynamodb:LeadingKeys`, or schema/row-level security in PostgreSQL.
- Noisy neighbour control: usage plans, per-tenant throttles, and tenant-aware metrics.
- Cost attribution: tag where possible; otherwise allocate by usage metrics.
@diagram layers
caption: Tenant isolation
layers:
  - {label: "Identity", nodes: ["Token with tenant claim|Cognito or IdP|cp"]}
  - {label: "API", nodes: ["Gateway and throttle per tenant|usage plans|warn"]}
  - {label: "Data", nodes: ["Partition by tenant|leading keys condition|ok"]}
@h Leading keys condition
```json title="tenant-policy.json"
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:Query"],
    "Resource": "arn:aws:dynamodb:eu-west-1:111122223333:table/data",
    "Condition": {"ForAllValues:StringEquals": {"dynamodb:LeadingKeys": ["${aws:PrincipalTag/TenantId}"]}}
  }]
}
```
@check
What stops a tenant reading another tenant's items in DynamoDB? || An IAM LeadingKeys condition bound to the tenant identity, plus tenant checks in code.
@end

@concept Scenario 8 Hybrid with on-premises
@plain
Core databases stay in a data centre for now while new services run in AWS and must call them with low latency.
@problem
Moving everything at once is risky, but split systems need secure and reliable connectivity and shared identity.
@does
- Connectivity: two Direct Connect locations with a VPN backup into a Transit Gateway.
- DNS: Route 53 Resolver inbound and outbound endpoints.
- Identity: IAM Identity Center federated with the corporate IdP; AD Connector or Managed AD for Windows workloads.
- Data movement: DMS and DataSync; S3 as landing zone; Storage Gateway for file access.
- Plan the exit: dependencies mapped, then migrate in waves.
- Latency: a 60 km fibre path adds about 0.3 ms one way at 5 microseconds per km; measure real round trip times.
@diagram flow
caption: Hybrid
nodes:
  - "Data centre|databases and AD|ext"
  - "Direct Connect and VPN|redundant|cp"
  - "Transit Gateway|hub|info"
  - "AWS VPCs|new services|app"
@h Verify the latency arithmetic
```python title="latency.py"
km, us_per_km = 60, 5
one_way_ms = km * us_per_km / 1000
print(one_way_ms, one_way_ms * 2)
```
@end

@concept Choosing between the eight designs
@plain
Real systems combine patterns. Use the same questions to select which parts you need.
@problem
Copying a reference architecture whole imports complexity you do not need.
@does
- Start with the simplest scenario that meets requirements.
- Add multi-Region only for a measured business need; Multi-AZ covers most availability goals.
- Add silo tenancy only for compliance or very large customers.
- Add Direct Connect when VPN bandwidth or latency is insufficient.
- Revisit annually, and after every major incident.
@diagram cmp
caption: Complexity ladder
cards:
  - {h: "Simple", kind: ok, items: ["Static site", "Event pipeline"]}
  - {h: "Moderate", kind: info, items: ["Three tier", "Batch", "Data lake"]}
  - {h: "Complex", kind: warn, items: ["Multi-Region active-active", "Multi-tenant silo and pool", "Hybrid"]}
@choose Add complexity when
Multi-Region active-active | RTO of seconds across a Region failure is required | Multi-AZ already meets the SLO
Silo tenancy | contracts or regulation require isolation | tenants are small and numerous
Direct Connect | steady high bandwidth or strict latency | occasional small transfers
@check
When is multi-Region justified? || When a measured business need exceeds what Multi-AZ can deliver.
@end

@concept Failure review and decision records
@plain
End every design with a failure review and a written decision record.
@problem
Without a record, the reasons behind a design are lost and repeated debates follow.
@does
- Failure review table: component, failure, detection, impact, recovery.
- Decision record: context, options, decision, consequences, revisit trigger.
- Keep both in the repository next to the infrastructure code.
- Review after incidents and update.
@diagram flow
caption: Documentation loop
nodes:
  - "Design|diagram and numbers|app"
  - "Failure review|table|warn"
  - "Decision record|ADR in Git|info"
  - "Revisit|after incidents|ok"
@h Failure table as data
```yaml title="failure-review.yaml"
- component: Aurora writer
  failure: AZ outage
  detection: CloudWatch alarm and RDS events
  impact: writes pause for the failover time
  recovery: automatic failover to the reader
- component: Lambda consumer
  failure: poison message
  detection: DLQ depth alarm
  impact: one message delayed
  recovery: fix and redrive
```
@end
