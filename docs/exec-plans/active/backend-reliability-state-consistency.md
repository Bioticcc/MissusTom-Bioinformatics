# Backend reliability and UI state consistency

## Scope

Address the post-rc.26 idle-load and contradictory-state failures without
altering active workflow data, ONT stage edits, or scientific validation rules.

## Plan

1. Separate cheap dependency-install lifecycle reads from explicit, expensive
   dependency verification. Cache and coalesce an explicit verification, then
   invalidate its result when an installation changes the environment.
2. Make health a cheap liveness/readiness signal and expose active local work
   for accurate UI/diagnostics state.
3. Apply endpoint-specific client timeouts; preserve validation streaming and
   report save versus run-plan failure independently.
4. Improve operator visibility, log following, and the two reported UI defects.
5. Add focused regressions, run the full check suite, independently review the
   resulting diff, then commit and push only after validation succeeds.

## Safety boundaries

- Do not touch existing user edits, especially `AGENT_TODO.md`, ONT stages, or
  biological-result removals.
- Keep installation/run admission locks and final execution preflight intact.
- Do not create a release tag until the committed branch passes required CI.
