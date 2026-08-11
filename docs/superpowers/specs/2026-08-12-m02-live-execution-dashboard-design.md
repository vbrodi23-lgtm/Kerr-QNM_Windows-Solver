# M02 Live Execution Dashboard Design

## Problem

The merged dashboard is checkpoint-centric. It redraws after a completed precision stage or leaf transition, so a live promoted Julia solve can consume CPU for minutes while the screen still presents only the last completed leaf.

## Selected design

Keep `LATEST COMPLETED LEAF` checkpoint-derived and add two independent live sections:

- `CURRENTLY EXECUTING`: root, mechanism, precision presentation, phase, running state, promotion reason, seed provenance, branch status, worker, precision-tier elapsed time, and last real worker activity.
- `LIVE ROOT SOLVE`: Newton index/limit, determinant count, current ω, current/best |D|, and active suboperation.

Promoted branch validity is `PENDING` until the worker returns authenticated branch evidence. `AUTHENTICATED_BACKGROUND` is shown as authenticated seed lineage, not as a completed branch verdict.

## Progress transport

The Python Julia adapter emits a display-only worker heartbeat every 2 seconds while the child remains alive. Julia stdout progress and heartbeats are serialized through the adapter's main waiting loop before reaching the reporter. This keeps elapsed time moving during a long silent call such as `r-from-rho` without changing the Julia request, solver state, checkpoint, or evidence.

## Alternatives rejected

- Redraw only on existing Julia events: still freezes throughout one long synchronous suboperation.
- Julia-side heartbeat task: scheduling is not dependable while the main Julia task is CPU-bound.
- Process polling as scientific evidence: CPU/memory observations remain external diagnostics and do not enter the solver contract.

## Verification

Synthetic subprocess tests must prove heartbeats occur without starting Julia and that real worker events remain ordered. Reporter tests must prove completed and active sections coexist, elapsed time advances on heartbeats, and unknown root evidence renders as pending/placeholders. No solver, determinant, Julia, or PowerShell campaign is run.
