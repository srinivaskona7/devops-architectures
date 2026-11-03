---
title: Managed databases on Azure
minutes: 55
objectives:
  - Choose between Azure SQL, Flexible Server, Cosmos DB and Redis for a workload
  - Create a private PostgreSQL Flexible Server with high availability
  - Connect applications with Entra authentication instead of passwords where supported
---
Azure offers a managed engine for every data shape. For the Shop app the important ones are PostgreSQL and Redis, but you should know the whole family.

@concept The database map
@plain
Relational, document and cache engines are all offered as managed services with backups, patching and high availability handled for you.
@problem
Running databases yourself on VMs or in Kubernetes means owning backups, failover and upgrades.
@does
- **AWS equivalent**: RDS (SQL Server, PostgreSQL, MySQL), DynamoDB and DocumentDB, ElastiCache.
- **Main difference**: Azure SQL is a first-party engine family (SQL Database, Managed Instance), while PostgreSQL and MySQL use **Flexible Server**. Single Server is retired. Cosmos DB is multi-model with several APIs.
- Pick by engine compatibility first, then by scale and latency.
@diagram cmp
caption: Service per workload
cards:
  - {h: "Relational", kind: app, items: ["Azure SQL Database", "SQL Managed Instance", "PostgreSQL Flexible", "MySQL Flexible"]}
  - {h: "NoSQL", kind: info, items: ["Cosmos DB", "Table storage"]}
  - {h: "Cache", kind: warn, items: ["Azure Cache for Redis", "Azure Managed Redis"]}
@choose Pick a store
PostgreSQL Flexible Server | open source SQL, extensions, lift from RDS PostgreSQL | you need SQL Server features
Azure SQL Database | SQL Server code, elastic pools, serverless | you need OS-level access or full SQL Agent
Cosmos DB | global writes, single digit ms at scale, flexible schema | you need joins and ad hoc SQL reporting
Redis | caches, sessions, queues with low latency | you need durable system of record
@end

@concept PostgreSQL Flexible Server
@plain
**Flexible Server** runs PostgreSQL as a managed VM-backed service with zone-redundant high availability, automatic backups and a choice between public access and private VNet integration.
@problem
You need a production PostgreSQL with failover and backups without administering instances.
@does
- **AWS equivalent**: RDS for PostgreSQL (and Aurora PostgreSQL only partly; Azure has no Aurora clone).
- **Main difference**: compute tiers are Burstable, General Purpose and Memory Optimized; storage is separate. **Private access** injects the server into a delegated subnet with a private DNS zone, so it has no public endpoint. HA can be zone redundant or same zone with a standby.
- Backups are automatic with point-in-time restore (retention 7 to 35 days).
- Extensions are allow-listed via the `azure.extensions` parameter.
@diagram layers
caption: HA layout
layers:
  - {label: "Zone 1", nodes: ["Primary|reads and writes|app"]}
  - {label: "Zone 2", nodes: ["Standby|synchronous replica|info"]}
  - {label: "Network", nodes: ["Delegated subnet|private only|cp", "Private DNS zone|privatelink.postgres|cp"]}
@h Create a private server
```bash title="Flexible Server" lab
az postgres flexible-server create -g rg-shop-prod -n pg-shop-prod -l westeurope \
  --tier GeneralPurpose --sku-name Standard_D2ds_v5 --storage-size 128 --version 16 \
  --vnet vnet-shop --subnet snet-pg --private-dns-zone privatelink.postgres.database.azure.com \
  --high-availability ZoneRedundant --zone 1 --standby-zone 2 \
  --microsoft-entra-auth Enabled --password-auth Enabled --admin-user shopadmin --admin-password "$PG_ADMIN_PASSWORD"
az postgres flexible-server db create -g rg-shop-prod -s pg-shop-prod -d shop
```
:::note
Check `az postgres flexible-server create --help` for the current parameter names; some flags have been renamed across CLI versions.
:::
@check
Does private access give a Flexible Server a public endpoint? || No. It is reachable only through the VNet and its private DNS.
@end

@concept Entra authentication to PostgreSQL
@plain
Instead of a password, the application asks Entra for a token and sends it as the PostgreSQL password.
@problem
Database passwords end up in secrets, get rotated rarely and are shared between people.
@does
- **AWS equivalent**: RDS IAM database authentication.
- **Main difference**: the Entra administrator is set on the server, then roles are created for managed identities with `pgaadauth_create_principal`. Token lifetime is around an hour, so the client must refresh it for each new connection.
- Works with workload identity from AKS; the pod holds no secret.
- Keep one break-glass password admin stored in Key Vault.
@diagram seq
caption: Token as password
actors: ["Pod|workload identity|app", "Entra ID|token endpoint|ext", "PostgreSQL|Flexible Server|env"]
steps:
  - "0>1: request token for ossrdbms scope | req"
  - "1>0: access token | resp"
  - "0>2: connect, token as password | tls"
  - "2>0: session | resp"
@h Get a token and connect
```bash title="psql with Entra token" lab
export PGPASSWORD=$(az account get-access-token --resource-type oss-rdbms --query accessToken -o tsv)
psql "host=pg-shop-prod.postgres.database.azure.com dbname=shop user=alice@contoso.com sslmode=require"
```
```sql title="Create a role for a managed identity" nocheck
SELECT * FROM pgaadauth_create_principal('id-shop-api', false, false);
GRANT ALL ON DATABASE shop TO "id-shop-api";
```
@end

@concept Azure SQL Database and Managed Instance
@plain
**Azure SQL Database** is a fully managed SQL Server engine per database. **Managed Instance** is a near 100 percent compatible instance with SQL Agent and cross-database queries.
@problem
SQL Server workloads need managed HA and patching, but some applications need features that only a full instance has.
@does
- **AWS equivalent**: RDS for SQL Server.
- **Main difference**: purchase models are vCore (provisioned or serverless with auto-pause) and DTU. Elastic pools share compute across databases. Hyperscale scales storage to very large sizes with fast restores. Logical server holds firewall and Entra admin settings.
- Active geo-replication and failover groups give cross-region DR.
- Entra-only authentication can be enforced.
@diagram flow
caption: Logical server and databases
nodes:
  - "Logical server|firewall, Entra admin|cp"
  - "Database|vCore or serverless|app"
  - "Elastic pool|shared compute|info"
  - "Failover group|secondary region|ok"
@h Serverless database
```bash title="Azure SQL" lab
az sql server create -g rg-shop-prod -n sql-shop-prod -l westeurope --enable-ad-only-auth \
  --external-admin-principal-type Group --external-admin-name sg-dba --external-admin-sid "$GID"
az sql db create -g rg-shop-prod -s sql-shop-prod -n reports --edition GeneralPurpose --compute-model Serverless \
  --family Gen5 --capacity 2 --auto-pause-delay 60
```
@end

@concept MySQL Flexible Server
@plain
**MySQL Flexible Server** offers managed MySQL with the same deployment model as PostgreSQL Flexible Server.
@problem
Applications built for MySQL need managed backups, failover and scaling.
@does
- **AWS equivalent**: RDS for MySQL.
- **Main difference**: zone-redundant HA, private access in a delegated subnet, read replicas, and server parameters managed through Azure. Version support follows community end-of-life; check the current docs.
- The commands mirror PostgreSQL (`az mysql flexible-server ...`).
- Entra authentication is available.
@diagram flow
caption: Read scaling
nodes:
  - "App writes|primary|app"
  - "MySQL primary|HA standby|env"
  - "Read replica|async|info"
  - "Reporting app|reads|plain"
@h Create and add a replica
```bash title="MySQL" lab
az mysql flexible-server create -g rg-shop-prod -n my-shop-prod -l westeurope --tier GeneralPurpose --sku-name Standard_D2ds_v4 \
  --vnet vnet-shop --subnet snet-my --admin-user shopadmin --admin-password "$MY_ADMIN_PASSWORD"
az mysql flexible-server replica create -g rg-shop-prod --replica-name my-shop-ro --source-server my-shop-prod
```
@check
Which Azure MySQL deployment is retired, Flexible or Single Server? || Single Server.
@end

@concept Cosmos DB
@plain
**Cosmos DB** is a globally distributed NoSQL database with multiple APIs and tunable consistency, billed by throughput (RU/s) or serverless.
@problem
You need low-latency reads and writes near users in many regions with a flexible schema.
@does
- **AWS equivalent**: DynamoDB (and DocumentDB for the MongoDB API).
- **Main difference**: choose an API at account creation: NoSQL (native), MongoDB, Cassandra, Gremlin, Table, PostgreSQL. **Five consistency levels** from strong to eventual. Capacity modes: provisioned, autoscale, serverless.
- Data is partitioned by a **partition key** you choose; a poor key creates hot partitions.
- Turn off key auth and use RBAC data roles with Entra.
@diagram layers
caption: Cosmos hierarchy
layers:
  - {label: "Account", nodes: ["Regions and consistency|global settings|cp"]}
  - {label: "Database", nodes: ["Container|partition key and RU/s|info"]}
  - {label: "Items", nodes: ["JSON documents|logical partitions|app"]}
@h Create a NoSQL account
```bash title="Cosmos DB" lab
az cosmosdb create -g rg-shop-prod -n cosmos-shop-prod --locations regionName=westeurope failoverPriority=0 isZoneRedundant=true \
  --default-consistency-level Session --disable-key-based-metadata-write-access true
az cosmosdb sql database create -g rg-shop-prod -a cosmos-shop-prod -n shop
az cosmosdb sql container create -g rg-shop-prod -a cosmos-shop-prod -d shop -n carts --partition-key-path /userId --throughput 400
```
@check
What decides how Cosmos DB spreads data and load? || The partition key.
@end

@concept Azure Cache for Redis
@plain
A managed Redis service for caches, sessions and fast counters.
@problem
Running Redis with persistence and failover yourself is operational work, and caches must be fast and close to the app.
@does
- **AWS equivalent**: ElastiCache for Redis or Valkey, MemoryDB.
- **Main difference**: Microsoft is transitioning from the Azure Cache for Redis tiers (Basic, Standard, Premium, Enterprise) to **Azure Managed Redis**. Check the current docs before choosing a SKU for new work.
- Premium and above support VNet injection or private endpoints, zone redundancy and clustering.
- Supports Entra authentication in addition to access keys; use TLS port 6380 (or 10000 for Managed Redis).
@diagram flow
caption: Cache aside
nodes:
  - "API pod|checks cache first|app"
  - "Redis|private endpoint|cp"
  - "Hit|return fast|ok"
  - "Miss|read PostgreSQL then store|warn"
@h Create and test
```bash title="Redis" lab
az redis create -g rg-shop-prod -n redis-shop-prod -l westeurope --sku Premium --vm-size P1 --zones 1 2 3 --minimum-tls-version 1.2
az redis show -g rg-shop-prod -n redis-shop-prod --query '{host:hostName,port:sslPort,state:provisioningState}' -o json
```
:::warn
The Azure Cache for Redis service has a published retirement path for some tiers. Confirm the current lifecycle and use Azure Managed Redis for new designs if recommended.
:::
@end
