# Kubernetes Platform

## Clusters

Production runs in two clusters, `prod-east-1` and `prod-west-2`. Staging runs in `stage-east-1`,
which mirrors production topology at smaller scale. Each team gets one namespace per environment,
named after the team, and cannot create resources outside it.

## Resource Requests

Every container must declare CPU and memory requests and a memory limit. CPU limits are not set,
because CPU throttling under a limit causes latency spikes that are hard to diagnose. Pods without
requests are rejected by the admission controller.

## Autoscaling

Services scale horizontally with the HorizontalPodAutoscaler, targeting 70% CPU utilisation.
Every production deployment runs at least 3 replicas spread across availability zones, and has a
PodDisruptionBudget allowing at most one replica to be unavailable during node maintenance.

## Health Checks

Readiness probes gate traffic; liveness probes restart stuck containers. A liveness probe must
never depend on a downstream service, or an outage in that dependency will restart every pod.

## Images

Only images from the internal registry may run in production. Images are scanned on push, and an
image with a critical vulnerability older than 7 days is blocked from new deployments.
