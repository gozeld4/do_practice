# Problem Statement: ML Job Scheduler Control Plane

**Duration:** 3 hours
**Languages:** Go or Python preferred; any language you are most productive in is acceptable.
**Tools:** GitHub Copilot is enabled on the provided laptop. Any other AI tools and documentation are allowed.
**Deployment:** You have DigitalOcean credits. The service must be deployed and reachable before the window closes.

---

## 1. Scenario

A shared ML compute platform accepts finite, one-off **training** and **batch-inference** jobs from multiple tenants. Recurring services and continuously running workloads do not exist on this platform.

You are building the **control plane**: a REST API service that

1. ingests job submissions, validating and rate-limiting them,
2. admits jobs under tenant quotas,
3. places work on compatible compute nodes,
4. hands out time-bound leases to workers,
5. recovers work when a worker or node goes silent, and
6. records exactly one authoritative result per task.

There are no real accelerators. Nodes and workers are plain HTTP clients that call your API. A small script that plays those roles is enough to exercise the system.

### Out of scope

- Actually executing training or inference
- Authentication beyond the tenant and user fields on the request
- Preemption of running work
- Multi-zone deployment
- Any UI

---

## 2. Domain model

### Job

A job declares:

| Field | Notes |
|---|---|
| `tenant_id` | Must be a tenant known to the service (from config). |
| `user_id` | The submitting user within the tenant. |
| `type` | `training` or `batch_inference`. |
| `resources.accelerator_type` | For example `a100`, `h100`. Must match a type the platform knows. |
| `resources.accelerators_per_task` | Integer, at least 1. A task must fit on a single node. |
| `priority_class` | `low`, `normal`, or `high`. |
| `input_ref`, `output_ref` | Opaque strings (URIs). |
| `checkpointable` | Boolean. Whether a task can resume from a checkpoint. |
| `replicas` | Training only. Number of replicas that must start together (a gang). |
| `shards` | Batch inference only. Number of independently retryable shards. |

### Tasks

- A **training** job with `replicas = N` produces N tasks that form a **gang**: all N are placed together or none are. If any replica's lease is lost, the whole gang is revoked and requeued as a unit.
- A **batch-inference** job with `shards = M` produces M independent tasks. Each shard is placed, retried, and committed on its own. The job succeeds when every shard has committed.

### States

- **Job:** `PENDING` → `RUNNING` → `SUCCEEDED` | `FAILED` | `CANCELLED`
  A pending job exposes a `pending_reason`: `quota`, `capacity`, or `gang`.
- **Task:** `PENDING` → `LEASED` → `COMMITTED` | `FAILED`
  A task whose lease expires returns to `PENDING` with its attempt count incremented. A task that exceeds the maximum attempts becomes `FAILED`, which fails the job.

Illegal transitions (for example cancelling a succeeded job) must be rejected.

### Nodes

A node registers with a `pool`, an `accelerator_type`, and a `capacity` (number of accelerators). Nodes heartbeat by re-registering. A node that stops heartbeating is treated as lost, and its capacity is no longer placeable.

---

## 3. API

| Endpoint | Behavior |
|---|---|
| `POST /v1/jobs` | Submit a job. Requires an `Idempotency-Key` header. |
| `GET /v1/jobs/{id}` | Job state, `pending_reason`, and per-task state, attempts, and node. |
| `GET /v1/jobs?tenant=&user=&state=` | Filtered listing. |
| `POST /v1/jobs/{id}/cancel` | Cancels the job, revokes its leases, frees its quota. |
| `POST /v1/jobs/{id}/retry` | Allowed only from `FAILED`. Re-runs only tasks that have not committed. |
| `PUT /v1/nodes/{id}` | Register or heartbeat a node. |
| `GET /v1/nodes/{id}/assignments` | Tasks placed on this node, each with a `lease_id`, `epoch`, `expires_at`, and the latest `checkpoint_ref` if any. |
| `POST /v1/leases/{id}/heartbeat` | Extends the lease. May carry a new `checkpoint_ref`. |
| `POST /v1/leases/{id}/complete` | Reports `status` (`succeeded` or `failed`), plus `output_ref` or `error`. |
| `GET /healthz`, `GET /readyz`, `GET /metrics` | Liveness, readiness, and metrics. |

You may adjust paths and payload shapes if you document the changes.

### Errors

All errors use one envelope:

```json
{
  "error": {
    "code": "quota_exceeded",
    "message": "requested 32 accelerators exceeds tenant quota of 16",
    "field": "resources.accelerators_per_task",
    "request_id": "req_01J..."
  }
}
```

---

## 4. Functional requirements

### Submission

- **Idempotency.** The same `Idempotency-Key` with the same body returns the original job and creates nothing new. The same key with a different body is rejected.
- **Validation.** Reject unknown tenants, unknown accelerator types, non-positive counts, `replicas` on a batch job, and `shards` on a training job. A job whose total demand exceeds the tenant's entire quota is rejected at submission with a reason. It is never queued forever.
- **Rate limiting.** Abusive per-user submission bursts are limited before they reach admission. Return `429` with `Retry-After`. One user's burst must not affect another user.

### Admission and placement

- **Tenant quotas.** A tenant's accelerators in use never exceed its configured quota.
- **Compatibility.** A task is placed only on a node with the matching accelerator type and enough free capacity.
- **Gangs.** Training replicas are placed all-or-nothing. A gang that cannot fully fit holds no partial resources.
- **Priority and fairness.** Higher priority classes are served first. Within a class, work is shared fairly across tenants, and across users within a tenant.
- **Bounded starvation.** No job waits forever behind a flooding tenant, a flooding user, or a steady stream of higher-priority work. Choose a mechanism (for example aging) and document it.

### Leases and recovery

- **Single owner.** At most one live lease owns a task at any time. Each new lease on a task carries a higher `epoch`.
- **Expiry.** A lease that is not heartbeated within its TTL expires. The task is requeued and its attempt count increments.
- **Checkpoints.** A requeued task from a checkpointable job is handed the latest `checkpoint_ref`. A non-checkpointable task restarts from scratch.
- **Single commit.** A logical task publishes its authoritative output exactly once. A `complete` or `heartbeat` call with an expired lease or stale epoch is rejected with `409` and changes nothing.
- **Durability.** Scheduler metadata survives a process crash and restart. After a restart, leases, quotas, and queue order are intact.

### Overload

- Bound the number of pending jobs per tenant and reject beyond it with a clear reason.
- Bound request body size and apply timeouts to requests and database calls.

---

## 5. Configuration

Everything below must be configurable without a code change. Suggested defaults are for this exercise.

| Setting | Suggested default |
|---|---|
| Per-user submission rate and burst | 5 per second, burst of 10 |
| Tenant quotas (accelerators) | Two or more tenants of your choosing |
| Max pending jobs per tenant | 1,000 |
| Lease TTL | 30 seconds |
| Lease sweep interval | 10 seconds |
| Node heartbeat timeout | 60 seconds |
| Max attempts per task | 3 |
| Scheduler tick | 1 second |
| Starvation / aging threshold | Your choice, documented |

---

## 6. Production targets

You are not expected to demonstrate these numbers in three hours. Your design, configuration, and write-up should account for them.

- 10,000 accelerators across several resource pools
- 50,000 queued jobs and 5,000 concurrently running task or replica allocations at peak
- Peak submission traffic of 200 jobs per second
- Runtimes from seconds (small batch shards) to several days (distributed training)
- p95 scheduling decision under two seconds for already-admitted work
- Tenant fair-share progress that is measurable
- Lost allocation leases detected within two minutes
- Scheduler metadata preserved through a single-zone failure
- The same logical output never published twice

---

## 7. What we evaluate

### Engineering quality
Clean code organization, sensible validation, and meaningful error handling. We look at how you separate the HTTP layer, the scheduling policy, and storage, and at where you choose to enforce correctness.

### Testing
A structured approach to verifying the service through automated tests. The requirements in section 4 are written as properties so that they can be tested. Time-dependent behavior (lease expiry, starvation bounds) should be testable without long sleeps.

### Automation and workflow
A one-command local setup, versioned schema migrations, a CI pipeline that lints, tests, and builds on every push, and an automated path to deployment, ideally followed by a smoke test against the live URL.

### Operational excellence
How the service behaves in a live environment:

- configuration through the environment
- structured logs that carry request and job identifiers
- metrics for queue depth, scheduling latency, usage against quota per tenant, lease expirations, rejected commits, and rate-limited requests
- a readiness check that reflects dependencies, and graceful shutdown
- safe behavior if two instances of the service run at once

---

## 8. Prioritization

You will not finish everything. Cut scope deliberately and say what you cut.

**Must have**
- Submit, inspect, and cancel with idempotency, validation, and rate limiting
- Tenant quota admission
- Placement of single-task work on compatible nodes
- Leases with expiry, requeue, and single commit
- Automated tests covering the above
- A deployed service with health checks and structured logs

**Should have**
- Gang placement for training jobs
- Sharded batch-inference jobs
- Priority, fair share, and bounded starvation
- Retry of failed jobs
- Metrics endpoint
- CI pipeline with automated deploy
- A small script that registers nodes, submits mixed jobs, and simulates a worker going silent

**Stretch**
- Checkpoint resume
- A scheduler that is safe with multiple service instances
- Load-test results against the deployed service
- The scale write-up (see below)

---

## 9. Deliverables

1. A Git repository with your code, tests, migrations, and CI configuration.
2. The URL of the deployed service.
3. A `README.md` containing:
   - how to run, test, and deploy
   - your fairness and starvation policy in a few sentences
   - what you cut and why
   - a short section, half a page at most, on what breaks first at the production targets in section 6 and what you would change
