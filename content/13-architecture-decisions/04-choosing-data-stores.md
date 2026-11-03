---
title: Choosing data stores
minutes: 55
objectives:
  - Match data shape and access pattern to a store type
  - Explain consistency, transactions and the CAP trade-off in plain terms
  - Plan sizing, backups and migration for the chosen store
---
Data outlives code. The store you pick shapes cost, speed and risk for years, and is one of the hardest decisions to reverse.

@concept Start from the access pattern
@plain
Describe how the data is read and written before naming a database. Shape, volume, and query style decide the store.
@problem
Choosing by popularity gives a store that cannot answer your questions efficiently.
@does
- List the top queries, their frequency, expected latency and whether they need joins or aggregations.
- Estimate sizes: rows or items, bytes each, growth per month, read to write ratio.
- Note consistency needs: must a read always see the last write?
- Note retention and compliance rules.
@diagram flow
caption: Questions to the store
numbered: true
nodes:
  - "Shape|rows, documents, events, files|plain"
  - "Queries|by key, ad hoc, analytical|info"
  - "Scale|size and request rate|warn"
  - "Consistency|strict or eventual|app"
  - "Store type|candidate list|ok"
@h Estimate the size
Example: 2 million orders per year, 3 KB each, kept 5 years. 2,000,000 x 3 KB x 5 = 30,000,000 KB, about 30 GB before indexes. That fits one managed relational instance comfortably, so scale alone does not justify a distributed store.
@check
Does 30 GB need a distributed database? || No, a single managed relational instance handles it.
@end

@concept Relational databases
@plain
Tables with rows, a schema, SQL and transactions that keep related changes together.
@problem
Business data such as orders, payments and inventory needs correctness and flexible queries.
@does
- ACID transactions: all or nothing, consistent, isolated, durable.
- Joins and ad hoc queries without planning every question in advance.
- Scale up first, then add read replicas. Sharding is costly and should be a late resort.
- Default choice for most business applications.
@diagram layers
caption: Scaling a relational store
layers:
  - {label: "Step 1", nodes: ["Bigger instance|vertical|ok"]}
  - {label: "Step 2", nodes: ["Read replicas|offload reads|info"]}
  - {label: "Step 3", nodes: ["Cache|hot data|app"]}
  - {label: "Step 4", nodes: ["Partition or shard|complex|warn"]}
@h A transaction
```sql title="transfer.sql" nocheck
BEGIN;
UPDATE accounts SET balance = balance - 100 WHERE id = 1;
UPDATE accounts SET balance = balance + 100 WHERE id = 2;
COMMIT;
```
@check
What does a transaction guarantee? || Related changes happen together or not at all.
@end

@concept Key-value and document stores
@plain
Items are fetched by key with predictable speed, often with a flexible structure.
@problem
Very high request rates and global scale are hard for a single relational instance.
@does
- Examples: DynamoDB, Cosmos DB, Firestore, MongoDB.
- Model the table around queries. Joins and ad hoc filters are limited or absent.
- Watch hot keys: a popular partition key throttles.
- Great for sessions, carts, user profiles, device state.
@diagram cmp
caption: Relational versus key-value
cards:
  - {h: "Relational", kind: info, items: ["Flexible queries", "Strong transactions", "Scales up first"]}
  - {h: "Key-value", kind: app, items: ["Fast by key", "Scales out", "Design for known queries"]}
@h Hot key arithmetic
If one partition handles 1,000 writes per second and a viral item gets 5,000 writes per second, that key alone needs 5 times the partition's capacity, so it throttles regardless of total table capacity. Spread the key, for example by adding a suffix 0 to 9.
@check
Why does a hot key throttle even on a big table? || One key maps to one partition with fixed capacity.
@end

@concept Caches, search and analytics stores
@plain
Specialised stores for speed, text search, and large analytical scans.
@problem
A general database is poor at sub-millisecond reads, full-text queries and scanning billions of rows.
@does
- Cache (Redis, Memcached): copies of hot data, expiry, never the only copy.
- Search (OpenSearch, Elasticsearch): text relevance, filters, facets. Fed from the main store.
- Warehouse (Redshift, BigQuery, Synapse or Fabric): columnar scans for reports.
- Time series and metrics stores for observability data.
@diagram flow
caption: One source of truth, several derived stores
nodes:
  - "Primary database|truth|ok"
  - "Change stream|events|info"
  - "Cache|fast reads|app"
  - "Search index|text queries|app"
  - "Warehouse|reports|app"
@check
Which store is the source of truth? || The primary database, others are derived copies.
@end

@concept Object, file and block storage
@plain
Not every byte belongs in a database. Files go in object storage, shared files in file systems, VM disks in block storage.
@problem
Large binaries in a database bloat it, slow backups and cost far more per gigabyte.
@does
- Store images, documents and exports in object storage. Keep only the key and metadata in the database.
- Use file storage for apps that need a shared POSIX or SMB folder.
- Use block storage for databases on VMs and for boot disks.
- Lifecycle rules move cold objects to cheaper tiers.
@diagram layers
caption: Match storage to access
layers:
  - {label: "Objects", nodes: ["Images and logs|HTTP, cheap|ok"]}
  - {label: "Files", nodes: ["Shared folders|NFS or SMB|info"]}
  - {label: "Blocks", nodes: ["VM disks|low latency|warn"]}
@h Cost illustration
10 TB at an example 0.023 per GB-month in object storage is 10,240 x 0.023 = 235.52 per month. The same volume on block storage at an example 0.08 per GB-month is 10,240 x 0.08 = 819.20. Prices are examples only.
```python title="storage_cost.py"
gb = 10 * 1024
print(round(gb * 0.023, 2), round(gb * 0.08, 2))
```
@check
Where should user-uploaded photos live? || In object storage, with only the key in the database.
@end

@concept Consistency, CAP and transactions
@plain
When data is copied to several places, you must choose between always seeing the latest write and staying available during a network split.
@problem
Distributed databases advertise features, but the guarantees differ, and wrong assumptions cause lost updates.
@does
- **Strong consistency**: a read after a write sees the write. Costs latency across regions.
- **Eventual consistency**: replicas converge soon. Reads may be stale.
- CAP: during a partition you choose consistency or availability.
- Make writes idempotent, and use conditional writes or version numbers to avoid lost updates.
@diagram seq
caption: A stale read from a replica
actors: ["Client|app|app", "Primary|writes|ok", "Replica|reads|info"]
steps:
  - "0>1: write order 42 | req"
  - "1>0: ok | resp"
  - "0>2: read order 42 | req"
  - "note 2..2: replication lag, not yet there"
  - "2>0: not found | bad"
@choose Reads after writes
Read from primary | you need the latest value | read load is huge
Read from replica | stale is acceptable | the user just wrote and expects to see it
Strongly consistent global store | cross-region correctness matters | latency budget is tight
@check
What does eventual consistency allow? || Reads that are briefly stale until replicas catch up.
@end

@concept Backup, recovery and migration of data
@plain
A store is only as good as its restore. Plan backups, restore tests and how to move later.
@problem
Teams discover on the worst day that backups were missing, corrupt or too slow to restore.
@does
- Automated backups plus point-in-time recovery where available. Check retention defaults.
- Restore into a separate environment on a schedule and time it. That time is your real RTO.
- Cross-region or cross-account copies for disaster recovery.
- Migrations: dual write or change data capture, verify counts and checksums, then cut over.
@diagram flow
caption: Zero-downtime migration outline
numbered: true
nodes:
  - "Copy|bulk load to new store|info"
  - "Sync|change data capture|app"
  - "Verify|counts and checksums|warn"
  - "Cut over|switch reads, then writes|ok"
  - "Retire|keep old read-only first|plain"
@check
How do you learn your real recovery time? || By timing a restore test.
@end

@concept Decision guide
@plain
A short guide from need to store type.
@problem
A long list of products hides the few real decisions.
@does
- Business records with relationships: managed relational.
- Known key lookups at huge scale: key-value or document.
- Files: object storage.
- Reports over history: warehouse, or serverless SQL over object storage.
- Hot reads: cache in front of the source of truth.
@diagram flow
caption: From need to store
nodes:
  - "Transactions and joins|managed relational|ok"
  - "Key lookups at scale|key-value|app"
  - "Large files|object storage|info"
  - "Analytics|warehouse|cp"
@choose Pick a store
Managed relational | most business apps, up to a few TB | you need millions of writes per second by key
Key-value or document | known access by key, huge scale | you need ad hoc joins
Warehouse | reports over history | you need single-row transactions
Self-run database | special engine or extension | nobody can operate backups and failover
@check
What is the safest default for a new business app? || A managed relational database.
@end
