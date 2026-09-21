# ML Job Scheduler Control Plane: Step-by-Step Learning Version

This is the same exercise as `original_ps.md`, reorganized for learning instead of speed.

**What changed from the original**

- The 3-hour clock is gone. Work through milestones at your own pace. The timed run comes back at the very end as an optional final challenge.
- The requirements are split into 12 milestones, ordered so each one builds on the last and introduces only a few new ideas.
- Every milestone has a plain-language explanation, a build list, checks you can run to know you are done, hints, and questions to think about.
- Ambiguities in the original are called out so you can decide them on purpose.
- Nothing was removed. The original tables (fields, API, config, production targets) are kept in the Reference section at the end.

---

## 1. The big picture

Many teams share one pool of GPU machines. They send in jobs ("train this model", "run inference over this dataset"). Something has to decide which job runs where, make sure no team takes more than its share, and notice when a machine dies mid-job so the work can be handed to another machine. That "something" is the **control plane**, and it is what you are building.

Think of the host stand at a busy restaurant. The host does not cook. The host takes reservations, decides who sits at which table, keeps track of which tables are taken, and notices when a party leaves. Your service is the host. The "kitchen" (real GPUs doing real training) does not exist in this exercise. Machines and workers are just small scripts that call your API and pretend.

**You build:** a REST API backed by a database, plus two background loops (a scheduler and a lease sweeper).

**You do not build:** real training or inference, login or auth (the `tenant_id` and `user_id` fields are trusted as given), preemption of running work, multi-zone deployment, or any UI.

---

## 2. Life of a job

Read this story first. Every requirement later is a detail of one of these steps.

```
client --POST /v1/jobs--------> API validates, rate-limits, stores
                                job + its tasks, all PENDING
                                          |
                           scheduler tick (every 1 second)
                           picks tasks, checks quota and node space
                                          v
                           task becomes LEASED on node X
                           (gets lease_id, epoch, expires_at)
                                          |
worker on node X --GET /v1/nodes/X/assignments--> sees the task
worker --POST heartbeat every ~10s--------------> expires_at pushed forward
worker --POST complete--------------------------> task COMMITTED
                                                  job SUCCEEDED once all tasks commit

If the worker goes silent:
lease sweeper (every 10 seconds) sees expires_at in the past
   -> task back to PENDING, attempts + 1, next lease gets a higher epoch
   -> the old worker's late calls are answered with 409
```

1. A user submits a job. The API checks it is valid, checks the user is not spamming, and stores it. The job is split into **tasks**: a training job with `replicas = 4` becomes 4 tasks, a batch job with `shards = 10` becomes 10 tasks.
2. Machines (**nodes**) announce themselves: "I am node-7, pool `east`, I have 8 `a100` accelerators." They repeat this regularly. Repeating it is their heartbeat.
3. Once a second the **scheduler** looks at pending tasks and free space, and places what it can, respecting tenant quotas, accelerator type, priority, and fairness.
4. Placing a task creates a **lease**: a time-limited claim that says "node-7 owns this task until 12:00:30."
5. The worker on that node asks for its assignments, starts the (pretend) work, and heartbeats the lease to keep it alive.
6. When done, the worker calls `complete`. The task's result is recorded exactly once.
7. If the worker disappears, its lease expires, the task goes back in the queue, and someone else gets it with a new lease and a higher **epoch**. If the old worker comes back from the dead and tries to report, it is rejected.

---

## 3. Glossary

| Term | Plain meaning | Analogy |
|---|---|---|
| Control plane | The part that makes decisions and keeps records, as opposed to the part that does the heavy work | The restaurant host, not the kitchen |
| Tenant | A team or customer sharing the platform | A corporate account at the restaurant |
| Quota | The most accelerators a tenant may use at the same time | "This account may occupy at most 16 seats at once" |
| Node | A machine with some number of accelerators of one type | A table with N seats, in a particular section |
| Pool | A named group of nodes | A dining room |
| Accelerator | A GPU-like device. Here it is only a number to count | A seat |
| Job | What the user submits | A reservation |
| Task | One placeable piece of a job | One guest, or one takeout order |
| Replica / gang | Training tasks that must all start together, or none start | A party of 8 that will not sit unless all 8 fit. You never seat 5 and hold those seats while waiting |
| Shard | One independent piece of a batch job | One of 10 separate takeout orders. If one is dropped, remake only that one |
| Admission | Deciding a job is allowed to use resources now, given its tenant's quota | Checking the account has seats left |
| Placement | Choosing the specific node for a task | Choosing the table |
| Lease | A time-limited claim on a task that must be renewed | A library loan. Renew it or the book goes back on the shelf |
| Heartbeat | A regular "still alive" call | Renewing the loan |
| TTL | Time to live. How long a lease lasts without a heartbeat | The loan period |
| Epoch | A counter that goes up every time a task is leased again | A hotel key card. When the room is reassigned, the old card stops working even if the old guest still holds it |
| Commit | Recording the final, authoritative result of a task | Handing in the one official copy of the exam |
| Idempotency | Doing the same request twice has the same effect as doing it once | Double-clicking "Place order" does not charge you twice |
| Idempotency-Key | A client-chosen ID for a request, so the server can spot a repeat | The order confirmation number |
| Rate limiting | Capping how fast one user can send requests | Each customer has a roll of tickets that refills slowly |
| Token bucket | The usual rate-limit algorithm. A bucket holds up to `burst` tokens and refills at `rate` per second. Each request spends one | The ticket roll |
| Aging | Raising a job's effective priority the longer it waits | A deli counter where your number gets bumped if you have waited too long |
| Starvation | A job that never runs because others always go first | The guest who is never seated |
| Durability | State survives a crash and restart | The reservation book is on paper, not in the host's head |
| Migration | A versioned, numbered script that changes the database schema | Numbered renovation plans, applied in order |
| Sweeper | A background loop that looks for expired things | Staff walking the floor checking for abandoned tables |
| Tick | One run of a loop that repeats on a timer | One glance at the waiting list |

---

## 4. Before you start

### Suggested stack

Use the language you are most comfortable in. If that is Python, a good learning path is:

- **FastAPI** (or Flask) for the HTTP layer
- **SQLite** for storage through Milestone 7. It is a real SQL database, it is built into Python, it needs no server, and it survives restarts
- **Postgres** from Milestone 8, when you need safe behavior with two running instances
- **pytest** for tests

If you already know Docker and Postgres, start with Postgres and skip the switch.

### Project layout

The original grades "how you separate the HTTP layer, the scheduling policy, and storage." Set that up from day one:

```
api/         HTTP routes, request parsing, error envelope. No business rules.
scheduler/   Pure decision logic. No HTTP, no SQL.
store/       All SQL lives here.
config.py    Reads settings from environment variables, with defaults.
clock.py     The one place that knows what time it is (see Milestone 2).
migrations/  001_init.sql, 002_..., applied in order.
tests/
```

### Ground rules for learning

- Go in order. Later milestones assume earlier ones work.
- Turn every item under "Check yourself" into an automated test. When all checks pass, the milestone is done.
- Write the core logic yourself: validation, the token bucket, the scheduler function, the lease update. Use AI tools to explain concepts and review your code. Let them generate boilerplate (Dockerfile, CI YAML) only after you can say what each line does.
- Keep a short learning log. After each milestone write three lines: what was new, what surprised you, what you would do differently.
- The time estimates are rough guesses for someone new to backend work. Ignore them if they do not match your pace.

---

## 5. Decisions the spec leaves to you

Real specs have gaps. Noticing them and choosing deliberately is part of the skill. Decide each of these when you reach it, and write your choice in the README.

| Question | A reasonable choice |
|---|---|
| Is an `Idempotency-Key` unique globally or per tenant? | Per tenant |
| What status code for "same key, different body"? | `409` (or `422`). Pick one |
| What does a replayed idempotent request return? | `200` with the original job |
| "Total demand exceeds the tenant's entire quota." For a gang, demand is clearly `replicas x accelerators_per_task`, since all replicas run at once. For a batch job, shards can run a few at a time, so is demand `shards x accelerators_per_task` or only `accelerators_per_task`? | The literal reading is `shards x accelerators_per_task`. The looser reading is friendlier to users. Pick one and say why |
| When a worker reports `status: failed`, does the task fail for good, or does it count as one attempt and get requeued? | Count it as an attempt and requeue until max attempts |
| When a gang is revoked, do all replicas get `attempts + 1` or only the one that was lost? | All of them. Simplest to reason about |
| Tasks have no `CANCELLED` state. What happens to the tasks of a cancelled job? | Clear their leases and stop scheduling them. The job state `CANCELLED` is the authority |
| Does `retry` reset attempt counts? | Yes, for the tasks being re-run |
| Does a heartbeat need the `epoch` in the body, given the `lease_id` is already in the URL? | Require it. It is cheap and makes the stale-worker case explicit |

---

## 6. Milestones

### Milestone 0: Hello, server (about 1 hour)

**Why:** everything else hangs off a server that starts with one command and has at least one test.

**New ideas:** HTTP routes, JSON responses, automated tests, reading config from the environment.

**Build**
- The folder layout from section 4.
- `GET /healthz` returning `200` and `{"status": "ok"}`.
- `config.py` that reads `PORT` from the environment with a default.
- One command to run (`make run`) and one to test (`make test`).

**Check yourself**
- `curl localhost:8080/healthz` returns 200.
- `make test` passes with one test that calls `/healthz`.
- A fresh clone works with those two commands and nothing else.

**Think about it:** why keep `api/`, `scheduler/`, and `store/` apart when the project is this small?

---

### Milestone 1: Submit and look up a job (2 to 3 hours)

**Why:** this is the front door. It teaches validation, storage, and state machines.

**New ideas:** REST resources, status codes (201, 400, 404, 409), SQL tables, migrations, a state machine as a table of allowed transitions.

**Build**
- A config entry for tenants and known accelerator types, for example `acme` with quota 16, `globex` with quota 8, types `a100` and `h100`.
- Migration `001` creating `jobs` and `tasks` tables.
- `POST /v1/jobs`: validate, then create the job and its tasks, all `PENDING`. Training with `replicas = N` creates N tasks. Batch with `shards = M` creates M tasks.
- `GET /v1/jobs/{id}`: job state, `pending_reason`, and for each task its state, attempts, and node.
- `GET /v1/jobs?tenant=&user=&state=`: filtered list.
- `POST /v1/jobs/{id}/cancel`: for now, only handles `PENDING` jobs.
- The error envelope (see Reference) on every error, with a `request_id`.

Example request bodies:

```json
{
  "tenant_id": "acme",
  "user_id": "gozel",
  "type": "training",
  "resources": {"accelerator_type": "a100", "accelerators_per_task": 2},
  "priority_class": "normal",
  "input_ref": "s3://bucket/data",
  "output_ref": "s3://bucket/model",
  "checkpointable": true,
  "replicas": 4
}
```

```json
{
  "tenant_id": "globex",
  "user_id": "sam",
  "type": "batch_inference",
  "resources": {"accelerator_type": "h100", "accelerators_per_task": 1},
  "priority_class": "low",
  "input_ref": "s3://bucket/in",
  "output_ref": "s3://bucket/out",
  "checkpointable": false,
  "shards": 10
}
```

**Check yourself**
- A valid job returns 201 and reads back as `PENDING`.
- `replicas = 4` creates exactly 4 tasks.
- Each of these is rejected with the envelope, a useful `code`, and the right `field`: unknown tenant, unknown accelerator type, `accelerators_per_task = 0`, `replicas` on a batch job, `shards` on a training job.
- A job that could never fit in the tenant's whole quota is rejected at submission with a reason.
- `GET` on an unknown id returns 404 in the envelope.
- Cancelling twice: the second call is rejected as an illegal transition.

**Hints**
- Write `validate(job, config)` as a plain function that returns a list of errors. No HTTP inside. It becomes trivial to test.
- Keep allowed transitions in one dictionary, such as `{"PENDING": {"RUNNING", "CANCELLED"}, ...}`, and route every state change through one function that checks it.

**Think about it:** why reject an oversized job at submission instead of letting it wait in the queue?

---

### Milestone 2: Make submission safe (about 2 hours)

**Why:** networks retry, clients double-send, and some users flood. The front door has to cope.

**New ideas:** idempotency, hashing a request body, unique constraints, the token bucket, `429` with `Retry-After`, an injectable clock.

**Build**
- Require the `Idempotency-Key` header. Missing means 400.
- Store the key and a hash of the body with the job. Same key and same body returns the original job and creates nothing. Same key with a different body is rejected.
- A token bucket per user (key it by tenant and user). Defaults: 5 per second, burst 10. When empty, return `429` with a `Retry-After` header.
- `clock.py`: a tiny object with a `now()` method. Production uses the real time. Tests use a fake one you can move forward by hand. From now on, nothing in your code calls the system time directly.
- A cap on pending jobs per tenant (default 1,000). Beyond it, reject with a clear code such as `too_many_pending`.
- A cap on request body size. Too large means `413`.

**Check yourself**
- Send the identical request twice: same job id both times, one row in the database.
- Same key, one field changed: rejected.
- User A sends 30 requests at once: some get 429 with `Retry-After`. User B sending at the same moment is not affected.
- Token bucket unit test with the fake clock: drain the bucket, advance one second, exactly 5 tokens are back. No `sleep` anywhere.
- With the pending cap set to 3 in config, the 4th pending job is rejected.

**Hints**
- Bucket math: `tokens = min(burst, tokens + elapsed_seconds * rate)`, then spend one if `tokens >= 1`.
- Put a unique constraint on `(tenant_id, idempotency_key)`. If two identical requests arrive at the same instant, one insert wins. The loser catches the constraint error and returns the winner's job. The database settles the race for you.

**Think about it:** if the rate limiter lives in your process's memory and you later run two copies of the service, what rate does a user actually get?

---

### Milestone 3: Nodes and first placement (about 3 hours)

**Why:** this is the first real scheduling. Keep it simple: test only with jobs that have one task (`replicas = 1` or `shards = 1`). Multi-task jobs come in Milestone 6.

**New ideas:** a background loop, a pure decision function, quota accounting, `pending_reason`.

**Build**
- `PUT /v1/nodes/{id}` with `pool`, `accelerator_type`, `capacity`. Create or update the node and record `last_seen`.
- A pure function, roughly `schedule(pending_tasks, nodes, usage_by_tenant, now) -> placements`. No HTTP and no SQL inside it.
- A loop that runs every tick (default 1 second): load the inputs, call `schedule`, write the results. A placed task becomes `LEASED` with a `node_id`, a new `lease_id`, `epoch = previous epoch + 1`, and `expires_at = now + lease TTL`. Its job becomes `RUNNING`.
- Rules inside `schedule`: the node's accelerator type must match, the node must have enough free capacity for the whole task, and the tenant's accelerators in use plus this task must not exceed its quota.
- Set `pending_reason` on jobs that did not get placed: `quota` when the tenant has no headroom, `capacity` when no compatible node has room.
- `GET /v1/nodes/{id}/assignments`: tasks leased to this node, each with `lease_id`, `epoch`, `expires_at`, and `checkpoint_ref` (empty for now).

**Check yourself**
- An `a100` task never lands on an `h100` node.
- One node with capacity 4 and two tasks needing 3 each: one is placed, the other stays pending with reason `capacity`.
- Tenant quota 8 and jobs adding up to 12: usage never goes above 8, and the job left out shows reason `quota`.
- The tests for `schedule` run without a server or a database.

**Hints**
- Free capacity of a node = `capacity` minus the accelerators of tasks currently `LEASED` on it.
- Tenant usage = accelerators of all that tenant's `LEASED` tasks. Compute it from the database each tick instead of keeping a counter that can drift.

**Think about it:** why is a pure function easier to trust than scheduling logic mixed into request handlers?

---

### Milestone 4: Leases and the single commit (2 to 3 hours)

**Why:** this is the heart of the exercise. Two promises must hold: a task never has two owners, and a result is never recorded twice.

**New ideas:** leases, the epoch as a guard against stale workers, the conditional update (also called compare-and-set), `409 Conflict`.

**Build**
- `POST /v1/leases/{id}/heartbeat`: if the lease is current, set `expires_at = now + TTL`. It may carry a `checkpoint_ref`, which you store on the task.
- `POST /v1/leases/{id}/complete` with `status` of `succeeded` (plus `output_ref`) or `failed` (plus `error`). Success makes the task `COMMITTED`.
- Both calls are rejected with `409`, and change nothing, when the lease is expired, the epoch is stale, or the task is no longer `LEASED`.
- Job roll-up: when every task is `COMMITTED` the job is `SUCCEEDED`. When any task is `FAILED` the job is `FAILED`.
- Extend `cancel` to running jobs: revoke the leases and free the quota. Cancelling a `SUCCEEDED` job is rejected.

**Check yourself**
- Calling `complete` twice: the second gets 409 and the stored output does not change.
- `complete` or `heartbeat` with the wrong epoch gets 409.
- After cancelling a running job, its worker's heartbeat gets 409, and a waiting job from the same tenant is placed on the next tick because the quota was freed.
- Cancelling a succeeded job is rejected.

**Hints**
- Do the commit as one SQL statement: `UPDATE tasks SET state = 'COMMITTED', output_ref = ? WHERE lease_id = ? AND epoch = ? AND state = 'LEASED' AND expires_at > ?`. Then look at how many rows changed. One row means success. Zero rows means 409.

**Think about it:** why is "read the row, check it in Python, then write" unsafe when two requests arrive at the same moment, while the single `UPDATE ... WHERE` is safe?

---

### Milestone 5: Time, expiry, and recovery (2 to 3 hours)

**Why:** machines die. The system has to notice and hand the work to someone else without waiting forever and without running it twice.

**New ideas:** a sweeper loop, testing time without sleeping, attempt counts, node loss, checkpoints, retry.

**Build**
- A sweeper that runs every 10 seconds. Any lease with `expires_at` in the past: the task returns to `PENDING`, `attempts + 1`, lease cleared.
- A task over the maximum attempts (default 3) becomes `FAILED`, which fails the job.
- The next lease on a requeued task has a higher epoch than the last.
- A node whose `last_seen` is older than the node heartbeat timeout (default 60 seconds) gets no new placements.
- Checkpoints: for a `checkpointable` job, the requeued task's assignment carries the latest `checkpoint_ref`. For a non-checkpointable job it carries none.
- `POST /v1/jobs/{id}/retry`: allowed only from `FAILED`. Only tasks that have not committed go back to `PENDING`.

**Check yourself** (all with the fake clock, none with `sleep`)
- Lease a task, advance 31 seconds, run the sweep: the task is `PENDING` with `attempts = 1`.
- The old lease's heartbeat now gets 409. The new lease has a higher epoch.
- Three expiries in a row: task `FAILED`, job `FAILED`.
- `retry` on a running job is rejected. `retry` on a failed batch job leaves committed shards alone.
- A node that stops heartbeating gets nothing new after 60 seconds.
- A checkpointable task that heartbeated `checkpoint_ref = "ckpt-7"` and then expired shows `ckpt-7` in its next assignment.

**Hints**
- Give the sweeper and the scheduler a `run_once(now)` method. The timer loop calls it in production, and tests call it directly.

**Think about it:** the production target says lost leases must be detected within two minutes. With a 30 second TTL and a 10 second sweep, what is your worst case? What happens to tasks on a node that was lost?

---

### Milestone 6: Gangs and shards (2 to 3 hours)

**Why:** distributed training needs all its replicas at once. Batch work is the opposite: every piece stands alone.

**New ideas:** all-or-nothing placement, transactions, why partial allocation causes deadlock.

**Build**
- Training jobs: try to place all replicas against a scratch copy of the free-capacity map. If every replica fits (they may spread across nodes, but each task must fit on a single node), apply all placements in one transaction. If not, place none and hold nothing.
- `pending_reason`: `quota` if the tenant lacks headroom for the whole gang, `capacity` if not even one replica fits anywhere, `gang` if some replicas fit but not all.
- Gang revoke: if any replica's lease is lost, revoke every lease in the gang and requeue them together.
- Batch jobs: each shard is placed, retried, and committed on its own. The job succeeds when every shard has committed.

**Check yourself**
- A gang of 4 tasks needing 2 each, with 6 free: nothing is placed, free capacity is still 6, reason is `gang`.
- Add a node with enough room: all 4 are placed in the same tick.
- Let one replica's lease expire: all 4 return to `PENDING` and all 4 old leases now get 409.
- A batch job with 5 shards where one lease expires: only that shard is requeued. The other four are untouched.

**Think about it:** picture two gangs that each grab half the cluster and wait for the other half. Why does all-or-nothing placement prevent that?

---

### Milestone 7: Priority, fairness, and no starvation (about 2 hours)

**Why:** with more work than capacity, the order of the queue is the product.

**New ideas:** sort keys as policy, fair share, aging.

**Build**
- Order pending work by a sort key. A simple one that meets the spec:
  1. effective priority (high, then normal, then low)
  2. the tenant's usage divided by its quota, lowest first
  3. the user's running task count within the tenant, lowest first
  4. submit time, oldest first
- Aging: for every X seconds a job has waited, raise its effective priority by one class. Make X configurable.
- Write the policy in your README in a few sentences.

**Check yourself** (test the pure `schedule` function directly)
- All else equal, high goes before normal, and normal before low.
- Tenant A submits 100 jobs, then tenant B submits 1. B's job is placed within a few ticks, not after all 100 of A's.
- The same holds for two users inside one tenant.
- A steady stream of high-priority jobs plus one low-priority job: advance the fake clock past the aging threshold and the low job gets placed.

**Think about it:** if a large gang at the front of the queue cannot fit, should smaller jobs behind it be allowed to jump ahead? What does that do to the gang over time, and how could aging help?

---

### Milestone 8: Surviving crashes and running two copies (2 to 3 hours)

**Why:** "it works on my laptop while nothing goes wrong" is not the bar. The original asks that leases, quotas, and queue order survive a restart, and that two instances at once behave safely.

**New ideas:** durability, transactions, race conditions, locks shared through the database.

**Build**
- Confirm every piece of scheduler state lives in the database and not in Python variables. The in-memory rate limiter is the usual exception. Note it as a known limit.
- Wrap every multi-row change in a transaction. Gang placement and gang revoke are the important ones.
- Move to Postgres if you are on SQLite.
- Make sure only one instance runs the scheduler tick and the sweeper at a time, for example with a Postgres advisory lock taken at the start of each tick.
- Timeouts on requests and on database calls.

**Check yourself**
- Submit jobs, lease a few, kill the process with `kill -9`, restart. Same jobs, same leases (still valid if not yet expired), same quota usage, same queue order.
- Run two instances against one database and drive load at them. Then run a checking query: no task has two live leases, and no tenant is above its quota.

**Think about it:** which of your four promises (quota, single owner, single commit, no partial gangs) is protected by a database constraint or conditional update, and which still depends on "only one scheduler runs at a time"?

---

### Milestone 9: Operate it (about 2 hours)

**Why:** a service you cannot observe is a service you cannot fix.

**New ideas:** structured logging, request IDs, metrics, liveness versus readiness, graceful shutdown.

**Build**
- Every setting in the Reference config table readable from the environment.
- JSON logs, one object per line, carrying `request_id` and, where relevant, `job_id`.
- `GET /metrics` with: queue depth, scheduling latency, usage against quota per tenant, lease expirations, rejected commits, rate-limited requests.
- `GET /readyz` that checks the database. `/healthz` stays a plain "the process is up."
- Graceful shutdown: stop accepting requests, finish the ones in flight, stop the loops.

**Check yourself**
- Change the lease TTL with an environment variable alone.
- Stop the database: `/readyz` returns 503 while `/healthz` still returns 200.
- Every log line parses as JSON and has a `request_id`.
- Trigger a 429 and a rejected commit, then see both counters go up in `/metrics`.

**Think about it:** why would a load balancer care about the difference between "alive" and "ready"?

---

### Milestone 10: Automate and deploy (2 to 3 hours)

**Why:** the original grades a one-command setup, CI on every push, and an automated path to a live URL.

**Build**
- A simulator script that registers nodes, submits a mix of jobs, acts as workers, and makes one worker go silent. It doubles as your demo and your smoke test.
- A `Dockerfile` and a `docker-compose.yml` with the app and Postgres.
- CI (GitHub Actions is fine) that lints, tests, and builds on every push.
- A deploy step to DigitalOcean or any host you like, followed by a smoke test against the live URL.

**Check yourself**
- Fresh clone plus one command gives a running service.
- Pushing a failing test turns CI red.
- The live URL answers `/healthz` and `/readyz`.
- The smoke test submits a job to the live service and watches it succeed.

---

### Milestone 11: Write it up (about 1 hour)

Your `README.md` needs:
- how to run, test, and deploy
- your fairness and starvation policy in a few sentences
- what you cut and why, plus your choices from section 5
- half a page at most on what breaks first at the production targets, and what you would change

Questions to guide the scale section:
- At 200 submissions per second, each one a database transaction, what is the first limit you hit?
- Your tick loads every pending job once a second. What happens at 50,000 queued jobs? What would you index, cache, or partition (by pool, for instance)?
- 5,000 live leases heartbeating every 10 seconds is about 500 writes per second. Is that a problem for one database?
- One scheduler at a time is safe. Is it fast enough for a p95 decision under two seconds?
- How would the metadata survive the loss of a whole zone?
- How would you show that fair share is actually happening?

---

## 7. Reference (unchanged from the original)

### Job fields

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

### States

- **Job:** `PENDING` → `RUNNING` → `SUCCEEDED` | `FAILED` | `CANCELLED`. A pending job exposes a `pending_reason`: `quota`, `capacity`, or `gang`.
- **Task:** `PENDING` → `LEASED` → `COMMITTED` | `FAILED`. A task whose lease expires returns to `PENDING` with its attempt count incremented. A task that exceeds the maximum attempts becomes `FAILED`, which fails the job.
- Illegal transitions (for example cancelling a succeeded job) must be rejected.

### Nodes

A node registers with a `pool`, an `accelerator_type`, and a `capacity`. Nodes heartbeat by re-registering. A node that stops heartbeating is treated as lost, and its capacity is no longer placeable.

### API

| Endpoint | Behavior | Milestone |
|---|---|---|
| `POST /v1/jobs` | Submit a job. Requires an `Idempotency-Key` header. | 1, 2 |
| `GET /v1/jobs/{id}` | Job state, `pending_reason`, and per-task state, attempts, and node. | 1 |
| `GET /v1/jobs?tenant=&user=&state=` | Filtered listing. | 1 |
| `POST /v1/jobs/{id}/cancel` | Cancels the job, revokes its leases, frees its quota. | 1, 4 |
| `POST /v1/jobs/{id}/retry` | Allowed only from `FAILED`. Re-runs only tasks that have not committed. | 5 |
| `PUT /v1/nodes/{id}` | Register or heartbeat a node. | 3 |
| `GET /v1/nodes/{id}/assignments` | Tasks placed on this node, each with a `lease_id`, `epoch`, `expires_at`, and the latest `checkpoint_ref` if any. | 3, 5 |
| `POST /v1/leases/{id}/heartbeat` | Extends the lease. May carry a new `checkpoint_ref`. | 4 |
| `POST /v1/leases/{id}/complete` | Reports `status` (`succeeded` or `failed`), plus `output_ref` or `error`. | 4 |
| `GET /healthz`, `GET /readyz`, `GET /metrics` | Liveness, readiness, and metrics. | 0, 9 |

You may adjust paths and payload shapes if you document the changes.

### Error envelope

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

### Configuration

Everything below must be configurable without a code change.

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

### Production targets

You do not have to demonstrate these. Your design and write-up should account for them.

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

## 8. How the milestones map to the original grading

| Original priority | Items | Milestones |
|---|---|---|
| Must have | Submit, inspect, cancel with idempotency, validation, rate limiting | 1, 2 |
| Must have | Tenant quota admission, single-task placement | 3 |
| Must have | Leases with expiry, requeue, single commit | 4, 5 |
| Must have | Automated tests | every milestone |
| Must have | Deployed service with health checks and structured logs | 0, 9, 10 |
| Should have | Gangs, shards | 6 |
| Should have | Priority, fair share, bounded starvation | 7 |
| Should have | Retry of failed jobs | 5 |
| Should have | Metrics, CI with deploy, simulator script | 9, 10 |
| Stretch | Checkpoint resume | 5 |
| Stretch | Safe with multiple instances | 8 |
| Stretch | Load test, scale write-up | 10, 11 |

| Original evaluation area | Where you practice it |
|---|---|
| Engineering quality | The `api/`, `scheduler/`, `store/` split, and enforcing promises in the database (2, 4, 8) |
| Testing | "Check yourself" lists, the fake clock (2, 5, 7) |
| Automation and workflow | 0, 10 |
| Operational excellence | 8, 9 |

---

## 9. Final challenge: the timed run

When all milestones are done, put the code away for a few days. Then open `original_ps.md`, set a 3-hour timer, and build it again from an empty folder. You will not finish everything, and the original says so. The skill being tested there is choosing what to cut, deploying early, and saying clearly what you left out.
