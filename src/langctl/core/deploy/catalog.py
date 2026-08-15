"""Where a project can be deployed, and what each destination really costs.

One table, so the picker, the "not yet" message and the documentation cannot
disagree about what is available.

The honesty here is deliberate. Every one of these destinations ends with the
same agent answering the same requests; what differs is the bill, the account
you need, and how much of it langctl can actually do for you. A picker that
lists five options as if they were equivalent would push people towards the
expensive ones for no benefit.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Status = Literal["ready", "planned", "external"]


@dataclass(frozen=True)
class Target:
    """A deployment destination."""

    key: str
    label: str
    #: One line for the picker.
    summary: str
    #: Rough monthly cost, for the smallest sensible configuration. The single
    #: number most likely to change someone's choice, and the one nobody wants
    #: to discover after deploying.
    cost: str
    status: Status
    #: What it will do, shown when it is not available yet.
    detail: str


TARGETS: tuple[Target, ...] = (
    Target(
        key="vps",
        label="VPS — your own server",
        summary="One command, no cloud account. Works on any Linux host with Docker.",
        cost="~$5/mo",
        status="ready",
        detail=(
            "Frontend, agent, Postgres and Redis as one compose stack over SSH. "
            "A rented VPS, a spare machine, or an EC2/GCE/Azure VM — they are all "
            "just Linux hosts with Docker."
        ),
    ),
    Target(
        key="langsmith",
        label="LangSmith Cloud",
        summary="Managed by LangChain. Hosts the agent only, not the chat UI.",
        cost="Plus plan + usage",
        status="planned",
        detail=(
            "A wrapper around `langgraph deploy`. LangChain runs the agent, its "
            "database and its scaling.\n\n"
            "The catch, and the reason it is not the default: it hosts the agent "
            "and not your chat UI, so the UI needs a home elsewhere. Serving it "
            "from inside the Agent Server is possible but costs the server-side "
            "API key, so it needs a custom auth handler first."
        ),
    ),
    Target(
        key="gcp",
        label="Google Cloud",
        summary="Cloud Run: the same two containers, as one service.",
        cost="~$40-70/mo",
        status="planned",
        detail=(
            "A Cloud Run service with the frontend and agent as sidecars, Cloud "
            "SQL for Postgres and Memorystore for Redis, emitted as reviewable "
            "Terraform.\n\n"
            "Cloud Run scales to zero by default, which loses queued background "
            "runs, so the generated config will pin a floor of one instance."
        ),
    ),
    Target(
        key="azure",
        label="Azure",
        summary="Container Apps: the same two containers, as one app.",
        cost="~$40-70/mo",
        status="planned",
        detail=(
            "A Container App holding both containers, Azure Database for "
            "PostgreSQL and Azure Cache for Redis, as Terraform. Minimum "
            "replicas pinned to one for the same reason as Cloud Run."
        ),
    ),
    Target(
        key="aws",
        label="AWS",
        summary="ECS Fargate: the same two containers, as one task.",
        cost="~$50-80/mo",
        status="planned",
        detail=(
            "An ECS Fargate service behind an ALB, with RDS and ElastiCache, as "
            "Terraform.\n\n"
            "Not to be confused with LangSmith BYOC on AWS: that is an "
            "Enterprise-plan arrangement where LangChain provisions their own "
            "platform into your account via Crossplane. It installs LangSmith, "
            "not your agent, and langctl cannot drive it."
        ),
    ),
)

#: Only this one actually deploys today.
DEFAULT = "vps"

BY_KEY = {target.key: target for target in TARGETS}


def get(key: str) -> Target | None:
    return BY_KEY.get(key)


def keys() -> list[str]:
    return [target.key for target in TARGETS]


def is_ready(key: str) -> bool:
    target = BY_KEY.get(key)
    return target is not None and target.status == "ready"
