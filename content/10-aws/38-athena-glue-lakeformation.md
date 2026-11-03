---
title: Athena, Glue and Lake Formation
minutes: 55
objectives:
  - Query S3 data with Athena and reduce scan cost with partitioning and Parquet
  - Catalog and transform data with Glue crawlers and jobs
  - Govern a data lake with Lake Formation permissions
---
A data lake keeps raw and curated data in S3. Glue catalogs and transforms it, Athena queries it, and Lake Formation controls who sees what.

@concept Athena serverless SQL
@plain
**Athena** runs SQL directly on files in S3 with no servers, and bills by data scanned.
@problem
Loading everything into a warehouse first is slow and costly for ad-hoc questions on logs and raw files.
@does
- Uses the Trino and Presto engine for SQL, and supports CSV, JSON, Parquet, ORC, Avro and Iceberg tables.
- Needs a table definition in the Glue Data Catalog and an S3 location for query results.
- Workgroups separate teams, enforce result locations and set per-query scan limits.
- Cost example: scanning 2 TB at a price of 5 dollars per TB is 10 dollars. Check the current price per TB.
@diagram flow
caption: Athena query path
nodes:
  - "Analyst|SQL|ext"
  - "Athena|workgroup|cp"
  - "Glue catalog|table schema|info"
  - "S3 data|files scanned|ok"
@h Run a query
```bash title="Start a query" nocheck
aws athena start-query-execution --work-group analytics \
  --query-string "SELECT status, count(*) FROM weblogs WHERE dt = '2026-10-30' GROUP BY status" \
  --query-execution-context Database=lake
```
@check
What does Athena bill on? || The amount of data scanned by each query.
@end

@concept Cutting scan cost with partitions and Parquet
@plain
Store data in a **columnar** format (Parquet) and in **partitioned** folders so a query reads only the columns and days it needs.
@problem
CSV scans every byte of every file, so cost and time grow with total data size.
@does
- Partition folders such as `dt=2026-10-30/` allow partition pruning when you filter on `dt`.
- Parquet reads only referenced columns and compresses well, often reducing scanned bytes by an order of magnitude.
- Avoid many tiny files; target files of about 128 MB or more.
- **Partition projection** computes partitions in the table definition, avoiding crawler runs.
- Example: 365 daily partitions of 10 GB is 3,650 GB. A one-day query scans 10 GB, which is 1/365 of the total.
@diagram cmp
caption: Layout choices
cards:
  - {h: "CSV, unpartitioned", kind: bad, items: ["Scans everything", "Slow", "Expensive"]}
  - {h: "Parquet, partitioned", kind: ok, items: ["Reads needed columns", "Prunes days", "Cheap and fast"]}
@h Convert with CTAS
```bash title="Create a Parquet table" nocheck
aws athena start-query-execution --work-group analytics --query-string \
 "CREATE TABLE weblogs_pq WITH (format='PARQUET', partitioned_by=ARRAY['dt'], external_location='s3://lake/curated/weblogs/') AS SELECT * FROM weblogs"
```
@check
Daily partitions of 10 GB for a year: scan for one day? || 10 GB, versus 3,650 GB without pruning.
@end

@concept Glue Data Catalog and crawlers
@plain
The **Glue Data Catalog** is a central metadata store of databases and tables. **Crawlers** scan data and create or update table definitions.
@problem
Every tool needs to know where data lives and what its schema is.
@does
- Used by Athena, EMR, Redshift Spectrum and Glue jobs.
- Crawlers infer schema and partitions on a schedule; for known layouts define tables in IaC instead.
- Schema changes can break queries; use a schema evolution policy.
- Iceberg tables in the catalog add ACID updates and time travel.
@diagram flow
caption: Catalog
nodes:
  - "S3 prefix|raw files|ok"
  - "Crawler|infer schema|app"
  - "Catalog table|metadata|info"
  - "Query engines|Athena, EMR|cp"
@h Database and table in Terraform
```hcl title="glue.tf"
resource "aws_glue_catalog_database" "lake" {
  name = "lake"
}

resource "aws_glue_crawler" "weblogs" {
  name          = "weblogs"
  database_name = aws_glue_catalog_database.lake.name
  role          = aws_iam_role.glue.arn
  schedule      = "cron(0 3 * * ? *)"
  s3_target {
    path = "s3://lake/raw/weblogs/"
  }
}
```
@end

@concept Glue ETL jobs
@plain
**Glue jobs** run Apache Spark or Python scripts on managed workers to clean and convert data.
@problem
Raw data is messy; you need repeatable transformation without running a cluster.
@does
- Types: Spark, Spark streaming, Python shell, Ray; Glue Studio for visual design.
- Billed per DPU-hour (check current price) with per-second billing and a minimum duration; right-size workers and use auto scaling.
- **Job bookmarks** track processed data for incremental runs.
- Triggers and workflows chain jobs, or orchestrate from Step Functions or MWAA.
@diagram flow
caption: Raw to curated
numbered: true
nodes:
  - "Raw zone|JSON and CSV|warn"
  - "Glue job|clean and convert|app"
  - "Curated zone|Parquet partitioned|ok"
  - "Catalog update|new partitions|info"
@h Job definition
```hcl title="glue-job.tf"
resource "aws_glue_job" "curate" {
  name              = "curate-weblogs"
  role_arn          = aws_iam_role.glue.arn
  glue_version      = "4.0"
  worker_type       = "G.1X"
  number_of_workers = 5
  command {
    name            = "glueetl"
    script_location = "s3://lake/scripts/curate.py"
  }
  default_arguments = {
    "--job-bookmark-option" = "job-bookmark-enable"
  }
}
```
@check
What does a job bookmark do? || Remembers what was processed so reruns handle only new data.
@end

@concept Lake Formation permissions
@plain
**Lake Formation** adds database-style grants (table, column, row) on top of the Glue catalog, instead of writing S3 bucket policies per user.
@problem
S3 policies cannot express column or row restrictions, and every team ends up with ad-hoc bucket access.
@does
- Register S3 locations; Lake Formation vends temporary credentials to integrated engines such as Athena.
- Grant to IAM principals with `SELECT` on specific columns; data filters give row-level security.
- **LF-tags** apply grants by classification such as `sensitivity=pii`.
- Cross-account sharing uses AWS RAM style grants to catalog resources.
@diagram layers
caption: Governed access
layers:
  - {label: "Principals", nodes: ["Analyst role|IAM|ext", "Data scientist role|IAM|ext"]}
  - {label: "Governance", nodes: ["Lake Formation|column and row grants, LF-tags|cp"]}
  - {label: "Storage", nodes: ["Glue catalog|tables|info", "S3 registered location|data|ok"]}
@h Grant columns
```bash title="Column grant" nocheck
aws lakeformation grant-permissions \
  --principal DataLakePrincipalIdentifier=arn:aws:iam::111122223333:role/Analyst \
  --permissions SELECT \
  --resource '{"TableWithColumns":{"DatabaseName":"lake","Name":"customers","ColumnNames":["id","country"]}}'
```
@check
How would you hide a PII column from analysts? || Grant SELECT on only the allowed columns, or use LF-tags with a sensitivity classification.
@end

@concept Iceberg tables and the lakehouse
@plain
**Apache Iceberg** is an open table format giving a data lake ACID updates, schema evolution and time travel.
@problem
Plain Parquet folders cannot update or delete rows safely or handle concurrent writers.
@does
- Athena supports Iceberg with `MERGE`, `UPDATE`, `DELETE` and `OPTIMIZE`.
- S3 Tables is an AWS managed Iceberg table offering; check current availability.
- Compaction keeps small files in check; snapshots expire with `VACUUM`.
- Open format means Spark, Trino, Redshift and others can read the same table.
@diagram flow
caption: Iceberg writes
nodes:
  - "Writers|Glue, Athena, Spark|app"
  - "Iceberg metadata|snapshots|cp"
  - "Parquet data files|S3|ok"
@h Create an Iceberg table
```bash title="Athena DDL" nocheck
aws athena start-query-execution --work-group analytics --query-string \
 "CREATE TABLE orders_ice (id bigint, status string, ts timestamp) PARTITIONED BY (day(ts)) LOCATION 's3://lake/iceberg/orders/' TBLPROPERTIES ('table_type'='ICEBERG')"
```
@end

@concept Data lake zones and cost governance
@plain
Organise the lake into **raw**, **cleaned** and **curated** zones with clear ownership, lifecycle and access rules.
@problem
An ungoverned lake turns into a swamp of unknown, duplicated and risky data.
@does
- Separate buckets or prefixes per zone; raw is immutable and kept for reprocessing.
- S3 lifecycle moves old raw data to colder classes; Intelligent-Tiering for unknown access.
- Workgroup scan limits and budgets stop runaway queries.
- Tag datasets with owner and classification; CloudTrail and Lake Formation logs give audit trails.
@diagram flow
caption: Zones
nodes:
  - "Raw|as received|warn"
  - "Cleaned|validated|info"
  - "Curated|business ready|ok"
  - "Consumers|BI and ML|app"
@h Workgroup scan limit
```hcl title="workgroup.tf"
resource "aws_athena_workgroup" "analytics" {
  name = "analytics"
  configuration {
    enforce_workgroup_configuration    = true
    bytes_scanned_cutoff_per_query     = 107374182400
    result_configuration {
      output_location = "s3://lake/athena-results/"
    }
  }
}
```
Here 107374182400 bytes is 100 GiB (100 x 1024 x 1024 x 1024).
@check
What stops a single query scanning terabytes by mistake? || A workgroup scan cutoff per query.
@end
