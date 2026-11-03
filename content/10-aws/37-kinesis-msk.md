---
title: Streaming with Kinesis and MSK
minutes: 55
objectives:
  - Compare Kinesis Data Streams, Firehose and Amazon MSK
  - Size a stream by shards and choose capacity modes
  - Build reliable consumers and deliver streams to S3
---
Streams hold ordered records for a time so many consumers can read them, replay them and process in near real time.

@concept Streaming fundamentals
@plain
A **stream** is an append-only log of records split into partitions. Producers write, consumers read from their own position.
@problem
Queues delete messages after one consumer. Analytics, audit and several downstream systems need the same data, in order, replayable.
@does
- Records with the same **partition key** go to the same shard or partition and keep their order.
- Retention lets late or new consumers read history.
- Throughput scales by adding shards or partitions.
- Consumers track a position (checkpoint) so they can resume.
@diagram flow
caption: Stream model
nodes:
  - "Producers|apps and agents|app"
  - "Stream|shards or partitions|cp"
  - "Consumer A|real time|ok"
  - "Consumer B|batch analytics|ok"
@h Choose
Kinesis Data Streams is native and serverless. MSK runs Apache Kafka. Firehose is for delivery without code.
@check
What guarantees order for related records? || Writing them with the same partition key so they land in one shard or partition.
@end

@concept Kinesis Data Streams shards and capacity
@plain
A shard accepts up to 1 MB per second or 1,000 records per second of writes and delivers up to 2 MB per second of reads (check the current quotas).
@problem
Undersized streams throttle producers; oversized streams waste money.
@does
- **Provisioned mode**: you choose shard count. **On-demand mode**: capacity scales automatically within documented limits.
- Hot partition keys overload a single shard even when others are idle.
- Sizing example: 6 MB per second peak ingest needs at least 6 shards, so provision 7 for headroom.
- Retention defaults to 24 hours and can be extended (check the current maximum).
- `ProvisionedThroughputExceededException` means slow down and retry with backoff.
@diagram cmp
caption: Capacity modes
cards:
  - {h: "Provisioned", kind: cp, items: ["You set shards", "Predictable cost", "Resharding work"]}
  - {h: "On-demand", kind: ok, items: ["Auto scaling", "Pay per data", "Good for spiky"]}
@h Create and write
```bash title="Stream commands" nocheck
aws kinesis create-stream --stream-name clicks --shard-count 7
aws kinesis put-record --stream-name clicks --partition-key user-42 --data "$(echo -n '{"page":"/"}' | base64)"
```
@check
Peak is 6 MB per second at 1 MB per shard. How many shards at minimum? || 6.
@end

@concept Consumers and enhanced fan-out
@plain
Consumers read with the shared 2 MB per second per shard limit, or get a dedicated 2 MB per second each with **enhanced fan-out**.
@problem
Several consumers on one shard compete for read throughput and add latency.
@does
- Standard consumers poll with `GetRecords`.
- Enhanced fan-out uses HTTP/2 push to a registered consumer, typically around 70 ms latency.
- The Kinesis Client Library (KCL) manages leases, checkpoints and resharding.
- Lambda reads through an event source mapping with batch size, parallelization factor and on-failure destination.
@diagram flow
caption: Consumers
nodes:
  - "Shard|2 MB per s shared|cp"
  - "Standard consumers|share it|warn"
  - "Enhanced fan-out|dedicated per consumer|ok"
@h Lambda mapping
```hcl title="kinesis-mapping.tf"
resource "aws_lambda_event_source_mapping" "clicks" {
  event_source_arn                   = aws_kinesis_stream.clicks.arn
  function_name                      = aws_lambda_function.process.arn
  starting_position                  = "LATEST"
  batch_size                         = 100
  parallelization_factor             = 2
  bisect_batch_on_function_error     = true
  maximum_retry_attempts             = 3
}
```
@end

@concept Firehose delivery
@plain
**Amazon Data Firehose** loads streaming data into S3, Redshift, OpenSearch, Splunk and HTTP endpoints, with buffering and optional transformation.
@problem
Writing, batching and retrying delivery code for data lakes is repetitive.
@does
- Buffer by size or time, then write files to S3 with prefix partitions like `year=!{timestamp:yyyy}/`.
- Convert JSON to Parquet or ORC using a Glue schema.
- Optional Lambda transformation and dynamic partitioning.
- Source can be direct PUT, a Kinesis stream, MSK or CloudWatch Logs subscriptions.
@diagram flow
caption: Stream to lake
nodes:
  - "Kinesis stream|events|cp"
  - "Firehose|buffer and convert|info"
  - "S3 Parquet|partitioned|ok"
  - "Athena|query|app"
@h Delivery stream
```hcl title="firehose.tf"
resource "aws_kinesis_firehose_delivery_stream" "to_s3" {
  name        = "clicks-to-s3"
  destination = "extended_s3"
  kinesis_source_configuration {
    kinesis_stream_arn = aws_kinesis_stream.clicks.arn
    role_arn           = aws_iam_role.firehose.arn
  }
  extended_s3_configuration {
    role_arn            = aws_iam_role.firehose.arn
    bucket_arn          = aws_s3_bucket.lake.arn
    buffering_size      = 64
    buffering_interval  = 300
    prefix              = "clicks/dt=!{timestamp:yyyy-MM-dd}/"
    error_output_prefix = "errors/!{firehose:error-output-type}/"
  }
}
```
@check
What two triggers flush a Firehose buffer? || Buffer size and buffer interval, whichever comes first.
@end

@concept Amazon MSK
@plain
**Amazon MSK** runs Apache Kafka brokers for you, in your VPC, with Kafka protocol compatibility.
@problem
You already have Kafka clients, connectors and skills, but running brokers and ZooKeeper-free controllers yourself is heavy.
@does
- Provisioned clusters across three AZs (broker sizes) or **MSK Serverless** for variable workloads.
- Auth: IAM access control, SASL/SCRAM, mutual TLS; encryption in transit and at rest.
- **MSK Connect** runs Kafka Connect connectors. Tiered storage keeps old data cheaply.
- Replication factor 3 with `min.insync.replicas` 2 tolerates one AZ failure without write loss using `acks=all`.
@diagram flow
caption: MSK in a VPC
nodes:
  - "Producers|Kafka clients|app"
  - "Brokers|three AZs|cp"
  - "Consumers|consumer groups|ok"
  - "MSK Connect|S3 sink|info"
@h Cluster outline
```hcl title="msk.tf"
resource "aws_msk_cluster" "events" {
  cluster_name           = "events"
  kafka_version          = "3.6.0"
  number_of_broker_nodes = 3
  broker_node_group_info {
    instance_type   = "kafka.m5.large"
    client_subnets  = var.private_subnet_ids
    security_groups = [aws_security_group.msk.id]
    storage_info {
      ebs_storage_info {
        volume_size = 500
      }
    }
  }
  client_authentication {
    sasl {
      iam = true
    }
  }
  encryption_info {
    encryption_in_transit {
      client_broker = "TLS"
    }
  }
}
```
:::note
Check the currently supported Kafka versions before choosing one.
:::
@end

@concept Choosing Kinesis, MSK, SQS and EventBridge
@plain
Pick by the access pattern, the ecosystem you already use and the operations you accept.
@problem
Teams over-build with Kafka when a queue suffices, or force queue semantics onto an analytics pipeline.
@does
- Kinesis: AWS native, easy Lambda integration, fewer knobs.
- MSK: Kafka ecosystem, Connect, Streams, larger records and retention flexibility.
- SQS: independent tasks, no ordering across messages, delete on success.
- EventBridge: event routing with rules, not high-volume analytics streams.
- Estimating monthly shard cost: shards x hours x price per shard-hour plus PUT payload units. For 7 shards over 730 hours that is 5,110 shard-hours; multiply by the current price.
@diagram cmp
caption: Stream choice
cards:
  - {h: "Kinesis", kind: ok, items: ["AWS native", "Simple operations", "Lambda friendly"]}
  - {h: "MSK", kind: cp, items: ["Kafka API", "Connect ecosystem", "More tuning"]}
  - {h: "SQS", kind: app, items: ["Work queue", "No replay", "Simplest"]}
@choose Streaming service
Kinesis Data Streams | AWS native producers and Lambda consumers | you must reuse Kafka clients and connectors
MSK | you run Kafka today or need its ecosystem | the team cannot operate Kafka concepts
Firehose | the goal is only to land data in S3 or OpenSearch | you need custom consumers and replay
@check
Which option is best to just land logs in S3 as Parquet? || Firehose.
@end
