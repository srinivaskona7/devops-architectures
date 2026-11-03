---
title: Configuration management and Ansible basics
minutes: 50
objectives:
  - Explain idempotence and desired state
  - Write an inventory, an ad hoc command and a playbook
  - Structure roles with variables, templates and handlers
  - Protect secrets with Ansible Vault and test changes safely
---
Configuration management makes servers match a description kept in Git. Even with containers, you configure nodes, bastions, CI runners and databases. Ansible is agentless: it connects over SSH and runs small modules. Module names and options change between versions, so check the current documentation.

@concept Desired state and idempotence
@plain
You describe what the server should look like (package installed, file present, service running). The tool changes only what differs. Running it twice makes no further changes: that property is **idempotence**.
@problem
Shell scripts like `echo line >> file` append again on every run and drift from reality. Hand edits leave "snowflake" servers nobody can rebuild.
@does
- Each task reports `ok` (already correct), `changed` or `failed`.
- A second run with zero changes proves the server matches the code.
- Configuration management complements Terraform (which creates infrastructure) and image builds (which bake software).
@diagram cmp
caption: Script versus desired state
cards:
  - {h: "Imperative script", kind: warn, items: ["Runs commands in order", "Re-running may break things"]}
  - {h: "Desired state", kind: ok, items: ["Declares the end result", "Safe to re-run, shows drift"]}
@h See the difference
```bash title="Append versus ensure" lab
f=/tmp/demo.conf; : > $f
for i in 1 2 3; do echo "setting=1" >> $f; done; wc -l < $f          # 3 lines: not idempotent
: > $f
for i in 1 2 3; do grep -qx "setting=1" $f || echo "setting=1" >> $f; done; wc -l < $f   # 1 line
```
@check
What does an idempotent run report on the second execution? || Zero changed tasks.
@end

@concept Inventory and ad hoc commands
@plain
The **inventory** lists the hosts and groups Ansible manages. Ad hoc commands run one module on many hosts without writing a playbook.
@problem
You need quick answers and fixes across 50 servers without logging in to each.
@does
- INI or YAML inventory; groups such as `[web]` and `[db]`; variables per group.
- Dynamic inventory plugins query AWS, Azure or Kubernetes instead of keeping a file.
- `ansible web -m ping`, `-m command -a "uptime"`, `-b` for sudo, `--limit` to narrow.
@diagram flow
caption: Control node to managed nodes
nodes:
  - "Control node|ansible installed|cp"
  - "SSH|keys, no agent|info"
  - "web1, web2|group web|app"
  - "db1|group db|app"
@h Inventory and commands
```ini title="inventory.ini"
[web]
web1.example.com
web2.example.com

[db]
db1.example.com

[all:vars]
ansible_user=deploy
```
```bash title="Ad hoc" nocheck
ansible -i inventory.ini all -m ping
ansible -i inventory.ini web -b -m ansible.builtin.service -a "name=nginx state=restarted"
ansible -i inventory.ini db --limit db1.example.com -m ansible.builtin.command -a "df -h /"
ansible-inventory -i inventory.ini --graph
```
@check
Which flag runs a task with sudo? || `-b` (become).
@end

@concept Playbooks, tasks and modules
@plain
A **playbook** is a YAML file listing plays; each play maps hosts to ordered tasks; each task calls a **module** such as `package`, `template` or `service`.
@problem
Ad hoc commands are not reviewable or repeatable. A playbook is code in Git that anyone can run.
@does
- Use fully qualified module names like `ansible.builtin.package`.
- `become: true` escalates privileges. `when:` adds conditions. `loop:` repeats a task.
- Prefer modules to `command` or `shell`, because modules are idempotent and report changes accurately.
- `--check --diff` shows what would change without changing it.
@diagram flow
caption: Anatomy of a play
numbered: true
nodes:
  - "Play|hosts: web, become: true|cp"
  - "Task 1|install nginx|app"
  - "Task 2|deploy config|app"
  - "Task 3|ensure service running|app"
@h A playbook
```yaml title="site.yml"
- name: Web servers
  hosts: web
  become: true
  tasks:
    - name: Install nginx
      ansible.builtin.package:
        name: nginx
        state: present

    - name: Ensure the web root exists
      ansible.builtin.file:
        path: /var/www/shop
        state: directory
        owner: www-data
        mode: "0755"

    - name: Start and enable nginx
      ansible.builtin.service:
        name: nginx
        state: started
        enabled: true
```
```bash title="Dry run, then apply" nocheck
ansible-playbook -i inventory.ini site.yml --check --diff
ansible-playbook -i inventory.ini site.yml
ansible-playbook -i inventory.ini site.yml | tail -5      # second run: changed=0
```
@end

@concept Variables, templates and facts
@plain
Variables make a playbook reusable. **Templates** (Jinja2) generate config files from variables. **Facts** are values Ansible discovers on each host, like OS family or memory.
@problem
Hard-coding values in each file forces copies for dev, staging and production that drift apart.
@does
- Variables come from many places; precedence rules are long, so keep it simple: defaults in the role, overrides in group_vars and host_vars.
- `{{ var }}` substitutes; `{% if %}` and `{% for %}` add logic in templates.
- Use facts such as `ansible_facts['os_family']` for conditions and `ansible_facts['memtotal_mb']` for sizing.
@diagram flow
caption: Data into a file
nodes:
  - "group_vars/web.yml|port, workers|info"
  - "Template nginx.conf.j2|placeholders|app"
  - "template module|renders per host|cp"
  - "/etc/nginx/nginx.conf|final file|ok"
@h Template
```yaml title="group_vars/web.yml"
nginx_port: 8080
nginx_worker_connections: 2048
```
```text title="templates/shop.conf.j2" nocheck
server {
    listen {{ nginx_port }};
    server_name {{ inventory_hostname }};
{% if ansible_facts['memtotal_mb'] > 4096 %}
    # larger hosts keep more keepalive connections
    keepalive_requests 1000;
{% endif %}
    location / { proxy_pass http://127.0.0.1:3000; }
}
```
@check
Why prefer the template module to echo in shell? || It is idempotent and shows the diff.
@end

@concept Handlers and ordering
@plain
A **handler** is a task that runs only when notified by a task that changed something, and only once at the end of the play.
@problem
Restarting nginx on every run causes needless downtime; forgetting to restart after a config change leaves the old config running.
@does
- A task uses `notify: Restart nginx`. Handler tasks sit under `handlers:`.
- Validate config before it is installed using the `validate:` parameter of `template` and `copy` modules.
- `meta: flush_handlers` forces handlers to run before later tasks.
@diagram seq
caption: Notify only when changed
actors: ["Task|template module|app", "Handler|restart nginx|cp"]
steps:
  - "0>0: config differs, changed | req"
  - "0>1: notify | req"
  - "note 1..1: runs once at end of play"
  - "1>1: restart service | resp"
@h Example
```yaml title="Template with validation and handler"
- name: Web config
  hosts: web
  become: true
  tasks:
    - name: Install config
      ansible.builtin.template:
        src: shop.conf.j2
        dest: /etc/nginx/conf.d/shop.conf
        mode: "0644"
        validate: nginx -t -c /etc/nginx/nginx.conf
      notify: Reload nginx
  handlers:
    - name: Reload nginx
      ansible.builtin.service:
        name: nginx
        state: reloaded
```
:::tip
Be careful: `validate` for conf.d snippets needs a command that tests the whole config. Test it on a staging host first.
:::
@end

@concept Roles and collections
@plain
A **role** is a standard folder layout that packages tasks, defaults, templates and handlers for one purpose, such as `nginx` or `node_exporter`. **Collections** distribute roles and modules.
@problem
Large playbooks become long and are copied between projects with edits.
@does
- Layout: `tasks/main.yml`, `defaults/main.yml`, `templates/`, `handlers/main.yml`, `meta/main.yml`.
- `ansible-galaxy init rolename` scaffolds one. `ansible-galaxy install -r requirements.yml` pulls shared roles and collections at pinned versions.
- Keep roles small, parameterised through defaults, and idempotent.
@diagram layers
caption: A role on disk
layers:
  - {label: "roles/nginx", nodes: ["tasks/main.yml|steps|app", "handlers/main.yml|restart or reload|app"]}
  - {label: "Config", nodes: ["defaults/main.yml|safe default values|env", "templates/|jinja files|env"]}
  - {label: "Playbook", nodes: ["site.yml|roles: nginx|cp"]}
@h Create and call
```bash title="Scaffold a role" lab
ansible-galaxy init /tmp/roles/nginx 2>/dev/null && ls /tmp/roles/nginx
```
```yaml title="site.yml using the role"
- hosts: web
  become: true
  roles:
    - role: nginx
      vars:
        nginx_port: 8080
```
@check
Where do default values for a role live? || defaults/main.yml.
@end

@concept Secrets, testing and Ansible with Kubernetes
@plain
**Ansible Vault** encrypts variable files so secrets can live in Git. Testing with `--check`, `ansible-lint` and Molecule catches errors before production.
@problem
Plaintext passwords in a repository are a breach waiting to happen, and untested playbooks fail halfway across a fleet.
@does
- `ansible-vault encrypt_string` or `encrypt` protects values; the vault password comes from a file or a secret manager. Alternatively fetch secrets at run time from Vault or AWS Secrets Manager with lookup plugins.
- `ansible-lint` flags bad practice; Molecule runs roles in disposable containers.
- Roll out in batches with `serial: 2` and stop on failure with `max_fail_percentage`.
- Ansible can also manage Kubernetes via the `kubernetes.core` collection, but for clusters prefer GitOps; use Ansible for the nodes and surrounding systems.
@diagram flow
caption: A safer rollout
numbered: true
nodes:
  - "Lint|ansible-lint|info"
  - "Molecule|test in containers|app"
  - "Check mode|on staging|warn"
  - "serial rollout|2 hosts at a time|cp"
  - "Verify|health check|ok"
@h Vault and a rolling play
```bash title="Encrypt a value" nocheck
ansible-vault encrypt_string 'S3cretPassw0rd' --name db_password
ansible-playbook site.yml --vault-password-file ~/.vault_pass
ansible-lint site.yml
```
```yaml title="Rolling update"
- hosts: web
  become: true
  serial: 2
  max_fail_percentage: 0
  tasks:
    - name: Update package
      ansible.builtin.package:
        name: shopctl
        state: latest
    - name: Wait for health
      ansible.builtin.uri:
        url: http://localhost:8080/healthz
        status_code: 200
      retries: 10
      delay: 3
```
@check
What does serial: 2 do? || It runs the play on two hosts at a time, limiting blast radius.
@end
