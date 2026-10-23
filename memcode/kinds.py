"""What the memory agent looks for: one running list of kinds (topics). Add a line to teach it a new kind.

Each kind is (topic, what to look for, example). WORK kinds come from what happens in the session; PROFILE kinds are
inferred about the project itself, whether or not anyone says them. The list builds the memory agent's prompt
(model.SYSTEM), the topics its output may use (model.SCHEMA), and the profile topics memcode keeps from a lower rating
and never pins to a file's content (curate.py).
"""
from __future__ import annotations

WORK = (
    ("process", "how the user wants the agent to work: what it must ask first, what it must never do, review and "
     "commit habits (from_user when the user said it)", "Ask before pushing to any shared branch"),
    ("workflow", "how to build, test, lint, run, release, deploy or debug here; multi-step procedures (every place a "
     "version must be bumped); the exact command that works", "A release bumps the version in plugin.json, "
     "marketplace.json and mcp_server.py"),
    ("pitfall", "a mistake made or a trap hit, written as its fix, not as the failure",
     "Start the server with APP_ENV=dev python3 -m app.server"),
    ("environment", "how the tools, CLI, sandbox, CI or host behave here: an env var a host sets, a missing command, a "
     "flag a tool needs", "The desktop app sets CLAUDE_PROJECT_DIR to the main checkout in worktree sessions"),
    ("design", "a decision and its reason, an invariant, a limit, which module owns what, why something is built the "
     "way it is", "The store stays in the main checkout; files are read from the session's own checkout"),
    ("decision", "the state of ongoing work the USER stated or confirmed (scope, parked items, holds and gates, an "
     "agreed approach), or a result a [ran] line verified or disproved that settles a question raised in the session; "
     "never the coding agent's own progress", "G16 is parked until the end"),
)

PROFILE = (
    ("stack", "language, build tool, frameworks and how the project is built (the first `mvn` command shows a Maven "
     "Java project and its usual build command)", "Java multi-module project built with Maven (`./mvnw`)"),
    ("infra", "the infrastructure the project runs on: cloud and region, containers and orchestration, databases, "
     "caches, queues, infrastructure as code (a Dockerfile, a Helm chart, Terraform, a docker-compose service)",
     "Runs on EKS in eu-west-1; Postgres 15 on RDS, Redis for sessions; Terraform in infra/"),
    ("deployment", "how and where the project is deployed: environments, pipeline, release trigger, who or what "
     "deploys, rollbacks (a CI workflow, a deploy script, a tag-triggered job)",
     "Tags v* trigger deploy.yml: staging first, then a manual approval for prod"),
    ("branching", "the branching and merge strategy: default and protected branches, branch naming, PR or MR flow, "
     "merge vs rebase, release branches", "Work branches off develop as feature/<ticket>; main only takes release merges"),
    ("structure", "where things live: modules, layers, where tests, configs and migrations go",
     "Database migrations live in db/migrations, one file per change"),
    ("location", "where important docs, scripts, configs and runbooks are, so nobody has to search for them",
     "Release steps are in docs/RELEASING.md; scripts/bootstrap.sh sets up a dev machine"),
    ("reference", "an important link shared or used in the session: a dashboard, design doc, ticket board, API "
     "reference, runbook, staging URL; with what it is for", "Grafana board for checkout latency: "
     "https://grafana.example.com/d/checkout"),
    ("integration", "an SDK, library or external service the project uses, what for and where (an edit that updates "
     "calls to a payments SDK shows which SDK, its API style, and the module that wraps it)",
     "PaymentGateway wraps the Stripe Java SDK; OrderService.pay calls it to charge orders"),
    ("component", "a class or module that is central or used often: its responsibility, main methods, who uses it",
     "OrderService is the entry point of the order lifecycle (place, pay, ship, cancel)"),
    ("domain", "key types and what they mean, e.g. the states of an enum used across the code and their order",
     "OrderState goes NEW -> PAID -> SHIPPED -> DELIVERED, plus CANCELLED"),
    ("convention", "how code is written here, as seen in the code: naming, error handling, logging, test style (only "
     "the user's words make it from_user)", "Services return Result<T, Error> instead of throwing"),
)

TOPICS = tuple(k for k, _, _ in WORK + PROFILE)
PROFILE_TOPICS = tuple(k for k, _, _ in PROFILE)


def prompt_list(kinds) -> str:
    return "".join(f"- {topic}: {what} (e.g. '{example}').\n" for topic, what, example in kinds)
