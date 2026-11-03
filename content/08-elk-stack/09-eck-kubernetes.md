---
title: ELK on Kubernetes with ECK and Filebeat
minutes: 55
objectives:
  - Install the ECK operator and deploy Elasticsearch and Kibana from manifests
  - Run Filebeat as a DaemonSet with Kubernetes autodiscover
  - Plan storage, node roles and upgrades for Elasticsearch on Kubernetes
---
Elasticsearch is stateful and picky. Elastic Cloud on Kubernetes (ECK) is an operator that handles the hard parts: certificates, rolling upgrades, scaling and node roles.

@concept What ECK is
@plain
ECK is a Kubernetes operator from Elastic. You create custom resources such as `Elasticsearch`, `Kibana`, `Beat`, `Agent` and `Logstash`, and the operator builds StatefulSets, Services, Secrets and TLS certificates for them.
@problem
Hand-writing StatefulSets for Elasticsearch means managing discovery, certificates, rolling restarts that wait for green health, and shard allocation during upgrades. Mistakes cause data loss.
@does
- Installs CRDs and one operator Deployment (`elastic-system` namespace).
- Generates a self-signed CA and per-node certificates, so transport and HTTP are encrypted by default.
- Creates the `elastic` superuser password in a Secret named `<name>-es-elastic-user`.
- Performs rolling upgrades safely, respecting shard allocation.
@diagram flow
caption: Operator pattern for Elasticsearch
nodes:
  - "Elasticsearch CR|your manifest|app"
  - "ECK operator|reconciles|cp"
  - "StatefulSets, Services, Secrets|generated|env"
  - "Running cluster|TLS and users|ok"
@h Install the operator
```bash title="Install ECK with Helm" lab
helm repo add elastic https://helm.elastic.co
helm repo update
helm install elastic-operator elastic/eck-operator -n elastic-system --create-namespace
kubectl -n elastic-system get pods
```
:::note
Check the ECK documentation for the operator version that matches the Elastic Stack version you plan to run.
:::
@end

@concept Deploying Elasticsearch with ECK
@plain
An `Elasticsearch` resource lists one or more `nodeSets`. Each node set is a group of nodes with the same roles, resources and storage.
@problem
A single node set with every role does not scale, and you want hot and warm data tiers with different disks.
@does
- `version` selects the Elastic Stack version.
- `nodeSets[].count`, `config.node.roles` and `volumeClaimTemplates` define the group.
- Set `podTemplate` resources, JVM options (`ES_JAVA_OPTS`) and anti-affinity.
- ECK sets `vm.max_map_count` through an init container only if allowed; otherwise configure the node or use `node.store.allow_mmap: false` (slower).
@diagram layers
caption: Node sets for a log cluster
layers:
  - {label: "Control", nodes: ["master x3|master role|cp"]}
  - {label: "Data", nodes: ["hot x3|data_hot, data_content, ingest|bad", "warm x2|data_warm|warn"]}
@h Manifest
```yaml title="elasticsearch.yaml"
apiVersion: elasticsearch.k8s.elastic.co/v1
kind: Elasticsearch
metadata:
  name: logs
  namespace: logging
spec:
  version: 8.15.0
  nodeSets:
    - name: master
      count: 3
      config:
        node.roles: ["master"]
      podTemplate:
        spec:
          containers:
            - name: elasticsearch
              resources:
                requests: {cpu: "1", memory: 4Gi}
                limits: {memory: 4Gi}
      volumeClaimTemplates:
        - metadata:
            name: elasticsearch-data
          spec:
            accessModes: [ReadWriteOnce]
            storageClassName: gp3
            resources:
              requests:
                storage: 10Gi
    - name: hot
      count: 3
      config:
        node.roles: ["data_hot", "data_content", "ingest"]
      podTemplate:
        spec:
          containers:
            - name: elasticsearch
              env:
                - name: ES_JAVA_OPTS
                  value: "-Xms8g -Xmx8g"
              resources:
                requests: {cpu: "4", memory: 16Gi}
                limits: {memory: 16Gi}
      volumeClaimTemplates:
        - metadata:
            name: elasticsearch-data
          spec:
            accessModes: [ReadWriteOnce]
            storageClassName: gp3
            resources:
              requests:
                storage: 1Ti
```
:::note
The version shown is an example. Use a supported release from the current Elastic documentation.
:::
@end

@concept Kibana, users and secrets
@plain
A `Kibana` resource points at an Elasticsearch resource with `elasticsearchRef`. ECK wires up the connection, certificates and service account.
@problem
Connecting Kibana to a secured Elasticsearch by hand needs tokens, CA certificates and config.
@does
- `kubectl get secret logs-es-elastic-user -o go-template='{{.data.elastic | base64decode}}'` returns the superuser password.
- Expose Kibana via a Service of type ClusterIP and an Ingress or Gateway with TLS; avoid LoadBalancer on the public internet.
- Additional users and roles can be declared in file realm Secrets (`auth.fileRealm`); for people prefer SAML or OIDC.
@diagram flow
caption: Kibana linked to Elasticsearch
nodes:
  - "Kibana CR|elasticsearchRef logs|app"
  - "ECK|creates service account and certs|cp"
  - "Elasticsearch|trusts Kibana|ok"
@h Kibana and access
```yaml title="kibana.yaml"
apiVersion: kibana.k8s.elastic.co/v1
kind: Kibana
metadata:
  name: logs
  namespace: logging
spec:
  version: 8.15.0
  count: 2
  elasticsearchRef:
    name: logs
  http:
    tls:
      selfSignedCertificate:
        disabled: true
```
```bash title="Get the password and connect" lab
PW=$(kubectl -n logging get secret logs-es-elastic-user -o go-template='{{.data.elastic | base64decode}}')
kubectl -n logging port-forward svc/logs-es-http 9200 &
sleep 2
curl -sk -u "elastic:$PW" https://localhost:9200/_cluster/health?pretty
```
@end

@concept Storage, scheduling and upgrades
@plain
Elasticsearch needs fast, persistent volumes, spread over failure zones, and careful maintenance.
@problem
A pod rescheduled to another zone cannot attach its EBS volume, and draining nodes carelessly can take two copies of a shard offline at once.
@does
- EBS volumes are zone-bound (`WaitForFirstConsumer` storage class). Use topology spread or anti-affinity so replicas of a shard live in different zones; set `cluster.routing.allocation.awareness.attributes: k8s_node_name,zone` through ECK `podTemplate` and node labels (see the ECK docs).
- Use a StorageClass with `allowVolumeExpansion: true` so volumes can grow.
- Changing the `version` field triggers a rolling upgrade. ECK waits for cluster health between nodes.
- Use PodDisruptionBudgets (ECK creates a default) so node drains do not break quorum.
- After maintenance remember to uncordon nodes, since a cordoned node blocks the scheduling of ES pods.
@diagram cmp
caption: Rules for stateful logging on Kubernetes
cards:
  - {h: "Do", kind: ok, items: ["Dedicated node pool with taints", "gp3 volumes and expansion", "Spread across 3 zones", "Snapshots to S3 with IRSA"]}
  - {h: "Avoid", kind: bad, items: ["Sharing nodes with noisy apps", "emptyDir for data", "Draining many nodes at once", "No memory limit equal to request"]}
@end

@concept Filebeat DaemonSet with ECK
@plain
A `Beat` resource with `type: filebeat` and `deployment.daemonSet` tells ECK to run one Filebeat pod on every node, already connected to your Elasticsearch.
@problem
You need every pod's stdout collected without changing any application.
@does
- The pod mounts `/var/log/containers`, `/var/log/pods` and `/var/lib/docker/containers` (path depends on the runtime) as read-only host paths.
- Runs as root (needed to read node logs) with a service account that may `get/list/watch` pods, namespaces and nodes for metadata.
- `elasticsearchRef` configures the output and certificates.
- Set resource limits; Filebeat typically needs 100 to 300 MiB depending on file count.
@diagram flow
caption: One Filebeat per node
nodes:
  - "Node 1|Filebeat pod|env"
  - "Node 2|Filebeat pod|env"
  - "Node 3|Filebeat pod|env"
  - "Elasticsearch|data stream logs-kubernetes|cp"
@h Beat resource
```yaml title="filebeat.yaml"
apiVersion: beat.k8s.elastic.co/v1beta1
kind: Beat
metadata:
  name: filebeat
  namespace: logging
spec:
  type: filebeat
  version: 8.15.0
  elasticsearchRef:
    name: logs
  config:
    filebeat.autodiscover:
      providers:
        - type: kubernetes
          node: ${NODE_NAME}
          hints.enabled: true
          hints.default_config:
            type: filestream
            id: kubernetes-container-logs-${data.kubernetes.pod.uid}-${data.kubernetes.container.name}
            paths:
              - /var/log/containers/*${data.kubernetes.container.id}.log
            parsers:
              - container: ~
    processors:
      - add_cloud_metadata: {}
      - add_host_metadata: {}
  daemonSet:
    podTemplate:
      spec:
        serviceAccountName: filebeat
        automountServiceAccountToken: true
        terminationGracePeriodSeconds: 30
        dnsPolicy: ClusterFirstWithHostNet
        hostNetwork: true
        securityContext:
          runAsUser: 0
        containers:
          - name: filebeat
            env:
              - name: NODE_NAME
                valueFrom:
                  fieldRef:
                    fieldPath: spec.nodeName
            resources:
              requests: {cpu: 100m, memory: 200Mi}
              limits: {memory: 400Mi}
            volumeMounts:
              - name: varlogcontainers
                mountPath: /var/log/containers
              - name: varlogpods
                mountPath: /var/log/pods
        volumes:
          - name: varlogcontainers
            hostPath:
              path: /var/log/containers
          - name: varlogpods
            hostPath:
              path: /var/log/pods
```
:::note
You also need a ServiceAccount, ClusterRole and ClusterRoleBinding for `filebeat`. Mount paths and the `container` parser depend on your runtime (containerd on EKS). Check the current ECK recipes.
:::
@end

@concept Autodiscover and hints
@plain
Autodiscover lets Filebeat watch the Kubernetes API for pods starting and stopping, and apply an input template to each automatically. **Hints** let pods configure their own log handling through annotations.
@problem
Static file paths cannot follow pods that appear and disappear, and one config for all workloads cannot treat Nginx and a Java app differently.
@does
- Provider `kubernetes` with `node: ${NODE_NAME}` limits watching to pods on this node (important for load on the API server).
- Annotations such as `co.elastic.logs/json.keys_under_root: "true"`, `co.elastic.logs/multiline.pattern`, `co.elastic.logs/enabled: "false"` and `co.elastic.logs/module: nginx` change per-pod behaviour.
- Enriches events with namespace, pod, labels and container fields.
- Use `templates` with conditions for finer control in place of hints.
@diagram flow
caption: Pod to input
nodes:
  - "Pod starts|annotation co.elastic.logs/module nginx|app"
  - "Autodiscover event|Kubernetes watch|info"
  - "Input created|reads the container file|warn"
  - "Pod stops|input removed|plain"
@h Pod annotations
```yaml title="deployment snippet"
apiVersion: apps/v1
kind: Deployment
metadata:
  name: checkout
  namespace: shop
spec:
  replicas: 2
  selector:
    matchLabels: {app: checkout}
  template:
    metadata:
      labels: {app: checkout}
      annotations:
        co.elastic.logs/json.keys_under_root: "true"
        co.elastic.logs/json.add_error_key: "true"
        co.elastic.logs/json.message_key: message
    spec:
      containers:
        - name: app
          image: registry.example.com/checkout:1.4.2
```
@end

@concept Operating the pipeline on EKS
@plain
On Amazon EKS, plan for IAM roles, zones, control plane logs and costs.
@problem
Logging clusters grow quietly. Without guard rails they take the nodes, the EBS budget and the network with them.
@does
- Use IRSA for the S3 snapshot repository. Annotate the Elasticsearch service account with the IAM role, and enable the S3 repository plugin (built in on recent versions).
- EKS control plane logs (API, audit, authenticator) go to CloudWatch Logs only if enabled; forward to Elasticsearch with a subscription filter, Firehose or Fluent Bit if you want them here.
- Cross-AZ traffic is billed: place Filebeat output through a Service with topology-aware routing, or accept the cost for resilience.
- Monitor Filebeat with `GET :5066/stats` and Elasticsearch with an exporter. Alert on yellow cluster and on disk watermarks.
- Taint a dedicated node pool (`logging=true:NoSchedule`) for Elasticsearch.
@diagram flow
caption: Log paths in an EKS estate
nodes:
  - "Pods|stdout|app"
  - "Filebeat DaemonSet|Elasticsearch in cluster|env"
  - "Control plane logs|CloudWatch Logs|ext"
  - "Forwarder|Firehose or Fluent Bit|warn"
  - "Elasticsearch|search and alerts|cp"
@h Quick health checks
```bash title="Verify the pipeline" lab
kubectl -n logging get elasticsearch,kibana,beat
kubectl -n logging get pods -o wide
kubectl -n logging logs ds/filebeat-beat-filebeat --tail=20
kubectl -n logging exec logs-es-hot-0 -c elasticsearch -- curl -sk -u "elastic:$PW" https://localhost:9200/_cat/indices/.ds-filebeat*?v
```
@end
