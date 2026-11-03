---
title: Database migration pipelines with Flyway and Liquibase
minutes: 50
objectives:
  - Run schema migrations from a pipeline safely
  - Use the expand and contract pattern for zero downtime changes
  - Choose between Flyway and Liquibase and run them as Kubernetes jobs
---
Application code can be rolled back in seconds. A schema change usually cannot. Treat migrations as first class releases.

@concept Why migrations belong in the pipeline
@plain
Schema changes are versioned scripts stored beside the code and applied in order by a tool, not typed into a console.
@problem
Manual changes drift between environments and nobody knows which version of the schema production has.
@does
- Each change is a numbered, immutable script; the tool records applied scripts in a history table in the database.
- The same scripts run in dev, staging and production, in that order.
- Reviewers see schema changes in the same pull request as the code that needs them.
- Never edit a script after it has been applied anywhere; add a new one. Both tools verify checksums and fail if an applied script changed.
@diagram flow
caption: Same scripts through every environment
numbered: true
nodes:
  - "Pull request|code and migration|app"
  - "Dev and staging|migrate and test|info"
  - "Approval|production gate|warn"
  - "Production|migrate then deploy|ok"
@end

@concept Flyway basics
@plain
Flyway applies SQL files named `V1__create_table.sql`, `V2__add_index.sql` in version order, and tracks them in the table `flyway_schema_history`.
@problem
You want the simplest possible tool that anyone who knows SQL can use.
@does
- Versioned migrations `V<version>__<description>.sql` run once. Repeatable `R__name.sql` rerun when their checksum changes.
- Commands: `info`, `validate`, `migrate`, `repair`, `baseline`. Use `baseline` to adopt an existing database.
- Configuration via a file or environment variables such as `FLYWAY_URL`.
- Some features (undo migrations, advanced checks) are in paid editions; check the current Flyway docs.
@diagram flow
caption: Flyway flow
nodes:
  - "SQL files|V1, V2, V3|app"
  - "flyway migrate|compares history|cp"
  - "History table|checksums|info"
  - "Database|up to date|ok"
@h Example
```sql title="db/migration/V3__add_orders_status.sql" nocheck
ALTER TABLE orders ADD COLUMN status VARCHAR(20);
UPDATE orders SET status = 'NEW' WHERE status IS NULL;
```
```bash title="Run Flyway" lab
flyway -url=jdbc:postgresql://db:5432/shop -user=shop -locations=filesystem:db/migration info
flyway -url=jdbc:postgresql://db:5432/shop -user=shop -locations=filesystem:db/migration migrate
```
@end

@concept Liquibase basics
@plain
Liquibase describes changes as **changesets** in XML, YAML, JSON or SQL, each identified by id and author, and tracks them in `DATABASECHANGELOG`.
@problem
You need database-agnostic definitions, preconditions and rollbacks across several engines.
@does
- A changelog file includes changesets; each runs once.
- Preconditions skip or fail a changeset if the state is not as expected.
- `rollback` blocks define how to reverse a changeset; many automatic rollbacks exist for simple changes.
- Commands: `status`, `validate`, `update`, `rollback`, `updateSQL` (preview SQL without running it).
@diagram flow
caption: Liquibase flow
nodes:
  - "changelog.yaml|changesets|app"
  - "liquibase update|checks DATABASECHANGELOG|cp"
  - "Database|new changesets applied|ok"
@h Changelog
```yaml title="db/changelog.yaml"
databaseChangeLog:
  - changeSet:
      id: 3-add-orders-status
      author: platform
      changes:
        - addColumn:
            tableName: orders
            columns:
              - column:
                  name: status
                  type: varchar(20)
      rollback:
        - dropColumn:
            tableName: orders
            columnName: status
```
@check
What does updateSQL do? || Prints the SQL that update would run, without changing the database, so it can be reviewed.
@end

@concept Choosing between Flyway and Liquibase
@plain
Both work well. Pick on team habits and portability needs.
@problem
Switching later means rewriting history and re-baselining every database.
@does
- Flyway: plain SQL, tiny learning curve, good fit when you use one database engine.
- Liquibase: abstract changes, preconditions, rollbacks and contexts; more concepts to learn.
- Both have Spring Boot integration, Maven and Gradle plugins, and official container images.
- Alternatives exist for specific stacks (Alembic for Python, Atlas, golang-migrate, Rails migrations).
@diagram cmp
caption: Trade-offs
cards:
  - {h: "Flyway", kind: ok, items: ["Plain SQL files", "Easy to learn", "One engine typical"]}
  - {h: "Liquibase", kind: info, items: ["Abstract changesets", "Preconditions, rollback", "More to learn"]}
@choose Which tool
Flyway | Team knows SQL and uses one database engine | You need engine-neutral definitions
Liquibase | Several engines or formal rollback and preconditions | You want the least tooling
@end

@concept Expand and contract for zero downtime
@plain
Change the schema in compatible steps so old and new application versions both work during the rollout.
@problem
During a rolling deploy, old and new pods run together. Renaming a column breaks whichever version does not expect it.
@does
- **Expand**: add the new column or table, nullable, with no code dependency. Backfill in batches.
- **Migrate**: deploy code that writes both and reads the new one.
- **Contract**: in a later release, after the old code is gone, drop the old column.
- Rename = add new, copy, switch, drop old, over at least two releases. Avoid long locks: create indexes concurrently on PostgreSQL (`CREATE INDEX CONCURRENTLY`) and add constraints in a not-validated state first.
@diagram flow
caption: Three releases for one rename
numbered: true
nodes:
  - "Expand|add new column|app"
  - "Dual write|new code writes both|info"
  - "Switch reads|read new column|cp"
  - "Contract|drop old column|warn"
@h Safe index creation
```sql title="V7__index_orders_customer.sql" nocheck
-- Flyway needs executeInTransaction=false for this statement
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_orders_customer ON orders (customer_id);
```
:::warn
Dropping a column in the same release that stops using it breaks any pod still running the old version.
:::
@check
Why drop the old column in a later release? || Old pods may still run during the first rollout and would fail if the column vanished.
@end

@concept Running migrations in Kubernetes
@plain
Run migrations as a one-off Kubernetes Job or a Helm hook before the new application version, not inside every application pod at start-up.
@problem
Five replicas starting together would each try to migrate. Tools lock the history table, but long migrations then block pod readiness and cause restarts.
@does
- A Job using the official `flyway/flyway` or `liquibase/liquibase` image, with the SQL baked into your own image or mounted from a ConfigMap.
- Helm: `helm.sh/hook: pre-install,pre-upgrade` with `hook-delete-policy`. Argo CD: a `PreSync` hook.
- Use a separate database user with DDL rights; the application user gets only DML rights.
- Credentials from a secret created by External Secrets; never in the image.
@diagram flow
caption: Migrate then roll out
numbered: true
nodes:
  - "Pre-sync Job|runs migrate|app"
  - "Success|history updated|ok"
  - "Deployment rollout|new pods|cp"
@h Argo CD hook Job
```yaml title="migrate-job.yaml"
apiVersion: batch/v1
kind: Job
metadata:
  name: shop-migrate
  annotations:
    argocd.argoproj.io/hook: PreSync
    argocd.argoproj.io/hook-delete-policy: BeforeHookCreation
spec:
  backoffLimit: 0
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: flyway
          image: registry.example.com/shop/migrations:1.4.0
          args: ["migrate"]
          envFrom:
            - secretRef:
                name: shop-db-migrator
```
@end

@concept Testing, rollback and safety nets
@plain
Test migrations against realistic data, and plan how to recover if one fails halfway.
@problem
A migration that takes 2 seconds on a laptop can lock a 500 million row table for an hour in production.
@does
- In CI, start a database container (Testcontainers or a service container), apply all migrations from scratch, then run tests.
- Also test the upgrade from the previous release's schema with sample data.
- Rehearse in staging with a production-sized copy where allowed (masked data).
- Take a snapshot before production migrations (RDS manual snapshot); prefer forward fixes over undo scripts.
- Set `lock_timeout` and `statement_timeout` so a blocked migration fails fast instead of queuing behind a long query.
@diagram layers
caption: Safety layers
layers:
  - {label: "Before", nodes: ["Fresh schema test|CI container|app", "Upgrade test|previous schema|app"]}
  - {label: "During", nodes: ["lock_timeout|fail fast|warn", "Batched backfill|small transactions|warn"]}
  - {label: "After", nodes: ["Snapshot|restore point|ok", "Forward fix|new migration|ok"]}
@h PostgreSQL guard rails
```sql title="session settings" nocheck
SET lock_timeout = '5s';
SET statement_timeout = '15min';
```
@end
