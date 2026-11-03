---
title: Databases for DevOps engineers
minutes: 45
objectives:
  - Write basic SQL to inspect and change data safely
  - Explain transactions and the ACID guarantees
  - Choose indexes and read a query plan
  - Design replication and backups with a recovery point and recovery time target
---
You will rarely design schemas, but you will be paged when the database is slow, full or lost. These concepts use PostgreSQL syntax; MySQL is similar but not identical, so check its documentation.

@concept Relational databases and tables
@plain
A relational database stores data in **tables** of rows and columns. Tables link to each other through keys. You talk to it in **SQL**.
@problem
Plain files cannot enforce rules such as "every order belongs to a real customer" or let many programs read and write at once without corrupting data.
@does
- A **primary key** uniquely identifies a row. A **foreign key** points at a row in another table and the database refuses broken links.
- Constraints (NOT NULL, UNIQUE, CHECK) reject bad data at the door.
- A server process owns the data files and applies access control per user and per table.
@diagram flow
caption: Two tables linked by a foreign key
nodes:
  - "customers|id (primary key), name, email|app"
  - "orders.customer_id|foreign key to customers.id|info"
  - "orders|id, customer_id, total, created_at|app"
@h Create and fill tables
```sql title="Schema and sample data" lab nocheck
CREATE TABLE customers (id serial PRIMARY KEY, name text NOT NULL, email text UNIQUE);
CREATE TABLE orders (
  id serial PRIMARY KEY,
  customer_id int NOT NULL REFERENCES customers(id),
  total numeric(10,2) NOT NULL CHECK (total >= 0),
  created_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO customers (name, email) VALUES ('Asha', 'asha@example.com'), ('Ben', 'ben@example.com');
INSERT INTO orders (customer_id, total) VALUES (1, 49.90), (1, 15.00), (2, 120.00);
```
```bash title="Run a throwaway PostgreSQL" nocheck lab
docker run -d --name pg -e POSTGRES_PASSWORD=devpass -p 5432:5432 postgres:16
docker exec -it pg psql -U postgres     # then paste the SQL above
```
@check
What does a foreign key prevent? || Creating a row that points to a parent row that does not exist, or deleting a parent that is still referenced.
@end

@concept SQL you need to read and run
@plain
Four statements cover most operational work: SELECT reads, INSERT adds, UPDATE changes and DELETE removes. A WHERE clause chooses which rows.
@problem
An UPDATE or DELETE without a WHERE clause changes every row. Many production data losses start with exactly that mistake.
@does
- `SELECT ... JOIN` combines tables; `GROUP BY` summarizes; `ORDER BY` and `LIMIT` shape output.
- Run the matching SELECT first to see how many rows an UPDATE will touch.
- Wrap risky changes in a transaction so you can roll back.
@diagram flow
caption: A safe habit for changing data
numbered: true
nodes:
  - "SELECT first|count the rows you will hit|info"
  - "BEGIN|open a transaction|app"
  - "UPDATE with WHERE|check the reported row count|warn"
  - "COMMIT or ROLLBACK|only commit if the count matches|ok"
@h Queries
```sql title="Read, join and change" lab nocheck
SELECT c.name, count(*) AS orders, sum(o.total) AS spent
FROM customers c JOIN orders o ON o.customer_id = c.id
GROUP BY c.name ORDER BY spent DESC;

BEGIN;
UPDATE orders SET total = total * 0.9 WHERE customer_id = 1;   -- expect 2 rows
-- psql prints UPDATE 2; if the number is wrong run ROLLBACK;
COMMIT;
```
:::danger
Never run a manual UPDATE or DELETE on production without a WHERE clause, a preceding SELECT and a transaction. Ask for a second pair of eyes.
:::
@end

@concept Transactions and ACID
@plain
A **transaction** groups several statements so they succeed or fail as one unit. ACID names the promises: Atomic, Consistent, Isolated, Durable.
@problem
A bank transfer is two updates. If the server dies between them, money disappears unless the database can undo or complete both.
@does
- **Atomic**: all or nothing.
- **Consistent**: constraints hold before and after.
- **Isolated**: concurrent transactions do not see each other's half-finished work; the level (read committed, repeatable read, serializable) decides how strictly.
- **Durable**: once committed, the change survives a crash because it was written to the write-ahead log first.
@diagram seq
caption: A transfer that is rolled back on failure
actors: ["App|client|app", "Database|PostgreSQL|cp"]
steps:
  - "0>1: BEGIN | req"
  - "0>1: debit account A | req"
  - "0>1: credit account B fails | bad"
  - "1>0: ROLLBACK, A is unchanged | resp"
@h Try it
```sql title="Atomic transfer" lab nocheck
CREATE TABLE accounts (id int PRIMARY KEY, balance numeric CHECK (balance >= 0));
INSERT INTO accounts VALUES (1, 100), (2, 50);
BEGIN;
UPDATE accounts SET balance = balance - 150 WHERE id = 1;   -- violates the CHECK
ROLLBACK;                                                   -- nothing changed
SELECT * FROM accounts;
```
@check
What makes a committed change survive a crash? || It is written to the write-ahead log and flushed to disk before the commit is acknowledged.
@end

@concept Indexes and query plans
@plain
An **index** is a sorted lookup structure, like the index of a book. It lets the database find rows without reading the whole table.
@problem
Without an index a query scans every row. That is fine at 1000 rows and a disaster at 100 million, and the symptom is high CPU and slow pages.
@does
- B-tree indexes serve equality and range searches. Each index speeds reads but slows writes and uses disk.
- `EXPLAIN` shows the plan; `EXPLAIN ANALYZE` runs it and shows real timings. Look for "Seq Scan" on big tables.
- Index the columns used in WHERE, JOIN and ORDER BY of frequent queries, not every column.
@diagram cmp
caption: Scan versus index lookup
cards:
  - {h: "Sequential scan", kind: warn, items: ["Reads every row", "Cost grows with table size"]}
  - {h: "Index scan", kind: ok, items: ["Walks a sorted tree", "Cost grows slowly with size", "Slower writes, more disk"]}
@h Read a plan
```sql title="Before and after an index" lab nocheck
EXPLAIN ANALYZE SELECT * FROM orders WHERE customer_id = 1;
CREATE INDEX CONCURRENTLY idx_orders_customer ON orders (customer_id);
EXPLAIN ANALYZE SELECT * FROM orders WHERE customer_id = 1;
```
:::tip
`CREATE INDEX CONCURRENTLY` avoids blocking writes on a busy PostgreSQL table. On a tiny test table the planner may still choose a scan, which is correct.
:::
@end

@concept Replication and high availability
@plain
Replication copies changes from a **primary** to one or more **replicas**. Replicas can serve reads and take over if the primary fails.
@problem
A single database server is a single point of failure, and one machine may not handle all reads.
@does
- **Asynchronous** replication is fast but a failover can lose the last few transactions (replication lag).
- **Synchronous** replication waits for a replica to confirm, so no committed data is lost, at the cost of latency.
- Reads from a replica can be stale. Do not read-after-write from a lagging replica.
- Managed services (Amazon RDS Multi-AZ, Aurora) automate failover; check current documentation for failover times.
@diagram flow
caption: Primary with replicas across zones
nodes:
  - "App|writes and reads|app"
  - "Primary|zone a, accepts writes|cp"
  - "Replica 1|zone b, standby|ok"
  - "Replica 2|zone c, read traffic|info"
@h Check lag
```sql title="PostgreSQL replication status" lab nocheck
-- on the primary
SELECT client_addr, state, sent_lsn, replay_lsn FROM pg_stat_replication;
-- on a replica
SELECT now() - pg_last_xact_replay_timestamp() AS replication_delay;
```
@check
What is the trade off of asynchronous replication? || Better latency, but a failover can lose transactions not yet copied.
@end

@concept Backups, RPO and RTO
@plain
A backup is a copy you can restore from. Two numbers set the design: **RPO** (how much data you can lose, measured in time) and **RTO** (how long recovery may take).
@problem
Replication copies mistakes instantly. A dropped table disappears from every replica within seconds, so only a backup rescues it.
@does
- **Logical** backups (`pg_dump`) export SQL or data, are portable and slow to restore on big databases.
- **Physical** backups copy data files plus WAL, allowing fast restore and point in time recovery.
- Follow 3-2-1: three copies, two media, one off site (another account or region).
- A backup is not proven until a restore has been tested.
@diagram cmp
caption: Logical versus physical backups
cards:
  - {h: "Logical dump", kind: info, items: ["pg_dump, mysqldump", "Portable across versions", "Slow restore at scale"]}
  - {h: "Physical base backup", kind: ok, items: ["Copies data files", "Fast restore", "Needed for PITR"]}
  - {h: "Snapshot", kind: app, items: ["Volume or RDS snapshot", "Quick to take", "Restore creates a new instance"]}
@h Dump and restore
```bash title="Logical backup and a restore test" lab nocheck
pg_dump -h localhost -U postgres -Fc -f shop.dump postgres        # custom format, compressed
createdb -h localhost -U postgres restore_test
pg_restore -h localhost -U postgres -d restore_test --no-owner shop.dump
psql -h localhost -U postgres -d restore_test -c 'SELECT count(*) FROM orders;'
```
:::warn
A backup that has never been restored is a hope, not a backup. Schedule a restore test and alert when it fails.
:::
@end

@concept Point in time recovery
@plain
**PITR** restores a database to any chosen moment, for example one minute before someone ran the bad DELETE. It combines a base backup with a stream of archived write-ahead logs.
@problem
Nightly backups mean up to 24 hours of lost data. A bad deployment at 15:07 should not cost you the day.
@does
- Take periodic physical base backups and continuously archive WAL to durable storage such as S3.
- To recover, restore the base backup, replay WAL up to a target time, then promote.
- Amazon RDS offers automated PITR within a retention window; verify the current limits and granularity in the documentation.
- Worked example: base backup at 02:00, WAL archived every minute, bad delete at 15:07. Restore to 15:06 loses about one minute (RPO near one minute). Recovery time is base restore time plus replay of about 13 hours of WAL.
@diagram flow
caption: Recovering to just before the mistake
numbered: true
nodes:
  - "Base backup|02:00 snapshot|ok"
  - "WAL archive|continuous changes|info"
  - "Mistake|15:07 DELETE|bad"
  - "Restore|base backup plus WAL to 15:06|app"
  - "Promote|new primary, verify, switch traffic|ok"
@h Recovery settings
```ini title="postgresql.conf for archiving and recovery" nocheck
# on the primary: keep WAL
archive_mode = on
archive_command = 'aws s3 cp %p s3://my-wal-archive/%f'
# on the restored copy: replay to a target (plus an empty recovery.signal file)
restore_command = 'aws s3 cp s3://my-wal-archive/%f %p'
recovery_target_time = '2026-10-30 15:06:00+00'
recovery_target_action = 'promote'
```
@check
Why is replication not a substitute for PITR? || A replica faithfully applies destructive changes; only archived history lets you go back in time.
@end
