# Jig Configuration

## Team

```yaml
name: monkeynaut-ai
platform: claude
git-host: github          # github | gitlab | bitbucket
ticket-system: github
# ticket-prefix:
```

## Pipeline

```yaml
stages:
  - discover
  - brainstorm
  - plan
  - execute
  - review
  - ship
  - learn
```

### Stage Overrides by Work Type

```yaml
bug:
  skip: [brainstorm-full, learn]
  brainstorm: light
task:
  skip: [brainstorm, learn]
  review: light
```

## Branching

```yaml
format: "{username}/gh-{number}-{kebab-title}"
main-branch: main
```

## Concerns Checklist

Map your engineering concerns to skills or specialists.
These surface during brainstorming for features and improvements.
Uncomment and point to your team skills as you create them.

```yaml
- i18n: manual
- analytics: manual
- feature-flags: manual
- migrations: manual
- caching: manual
- webhooks: manual
- event-publishing: manual
- security-auth: manual
- responsive: manual
- error-handling: core/specialists/error-handling
- security: core/specialists/security
- test-strategy: manual
```

## Review

```yaml
swarm-tiers:
  fast-pass: [security, dead-code, error-handling]
  full: all
deep-review-model: opus
specialist-model-default: haiku
```

## Execution

```yaml
parallel-threshold: 3
default-strategy: team-dev
teammate-mode: tmux
```

## Commit

```yaml
convention: conventional
format: "type(scope): message"
types: [feat, fix, docs, chore, refactor, test]
require-ticket-reference: true
co-author: true
# co-author-domain: yourcompany.com    # "commit with alex" → alex@yourcompany.com
```

## Estimates

```yaml
# scale: [0, 1, 2, 4, 16, 32]    # your team's estimate values
# unit: hours                      # hours | points | t-shirt
```

## Tracker

Add a section matching your `ticket-system` value above.
Tracker packs read IDs from here. See packs/ for setup instructions.

```yaml
# ## Tracker
# Add tracker-specific config here when ready.
# See packs/ for tracker integration setup.
```
