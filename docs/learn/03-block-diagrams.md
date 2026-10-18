# 3. Block diagrams

## Layers on your Windows laptop

```mermaid
flowchart TB
  subgraph win [Windows]
    browser[Browser → http://localhost:3000]
    subgraph wsl [WSL 2 — Ubuntu Linux]
      dockerd[Docker engine — dockerd]
      subgraph net [Docker network 'infra_default' — containers find each other by name]
        web[web :3000]
        api[api :8000]
        worker[worker]
        beat[beat]
        monitor[monitor]
        postgres[(postgres :5432)]
        redis[(redis :6379)]
      end
      vols[(volumes: pgdata · documents · backups · monitorlog)]
    end
  end
  browser -->|WSL forwards localhost| web
  dockerd --- net
  postgres --- vols
  api --- vols
  worker --- vols
```

Ports published to your machine (and only on `127.0.0.1`): **3000** (web) and **8000** (api). PostgreSQL and
Redis are reachable only inside the Docker network, unless you add `infra/docker-compose.local.yml`
(then `localhost:5433` and `localhost:6380`).

## Functional blocks

```mermaid
flowchart LR
  subgraph input [Inputs]
    P[Your profile<br/>verified facts]
    J[Job sources<br/>BA · Greenhouse · Lever · Personio<br/>manual URL import]
  end
  subgraph core [JobPilot core]
    DIS[Discovery<br/>normalize · dedup]
    MAT[Matching<br/>score · evidence · eligibility]
    REV{You review}
    DOC[Documents<br/>CV + letter · fact-check]
    FORM[Form preparation<br/>safe fields only]
    APP{You approve}
    SUB[Submission<br/>once · evidence]
    TRK[Tracker<br/>follow-ups · outcomes]
  end
  subgraph ops [Operations]
    SCH[Scheduler]
    MON[Monitor + alerts]
    NOT[Notifications<br/>in-app · email]
    BAK[Backups]
  end
  J --> DIS --> MAT --> REV --> DOC --> FORM --> APP --> SUB --> TRK
  P --> MAT
  P --> DOC
  P --> FORM
  SCH --> DIS
  SCH --> NOT
  SCH --> BAK
  MON --> NOT
```

## Server deployment (optional, with HTTPS)

```mermaid
flowchart LR
  internet((Internet)) -->|443 HTTPS| caddy[Caddy<br/>automatic certificates · HSTS<br/>blocks /docs]
  caddy -->|http| web[web :3000]
  web --> api[api :8000]
  api --> pg[(postgres)]
  api --> rd[(redis)]
  rd --> wk[worker]
  bt[beat] --> rd
  mon[monitor] --> pg
```

Started with `infra/docker-compose.prod.yml` on top of the normal file. Only ports 80 and 443 are open; web and
api are not published at all.

## Data flow of one application

```mermaid
flowchart LR
  A[Job posting] --> B[jobs row] --> C[job_match_evaluations]
  C --> D[applications: classified]
  D -->|you approve| E[documents v1, v2 ...]
  E --> F[form_fields]
  F -->|you approve| G[approvals: hashes]
  G --> H[submission_attempts]
  H --> I[applications: submitted]
  I --> K[follow_ups]
  D -.every change.-> L[application_state_history]
```

## Reliability blocks

```mermaid
flowchart TB
  subgraph watch [Who watches whom]
    S[scheduler heartbeat] <-->|each checks the other| M[monitor heartbeat]
  end
  M --> C1[database · queue · schedules · stuck runs]
  M --> C2[source failures · error spikes · Claude errors · browser errors]
  M --> C3[damaged documents · closed listings · stuck applications]
  M --> C4[duplicate or unclear submissions · email failures · backups · AI budget]
  C1 & C2 & C3 & C4 --> AL[Alert: severity · component · cause · what to do · paused?]
  AL --> UI[Notifications page]
  AL --> EM[Email if configured]
  DBdown[Database unreachable] --> FB[monitor fallback log + one email]
```

## CI pipeline (GitHub Actions)

```mermaid
flowchart LR
  push[git push] --> be[backend<br/>lint · pip-audit · 241 tests<br/>Postgres + Redis services]
  push --> fe[frontend<br/>npm audit · typecheck · build]
  be --> dk[docker<br/>build images · start full stack ·<br/>sign-in · search · heartbeats ·<br/>backup · restore drill · login limit]
  fe --> dk
```

Next: [4. Database schema](04-database-schema.md)
