# Work Cubbies

A source-controlled RAPP neighborhood for clocking work without mixing one
neighbor's record into another's.

**Neighborhood address**

```text
rapp://neighborhood/work-cubbies@github.com/kody-w/rapp-work-cubbies
```

- Git: <https://github.com/kody-w/rapp-work-cubbies>
- Manifest: <https://raw.githubusercontent.com/kody-w/rapp-work-cubbies/main/neighborhood.json>
- Cubby protocol: [`rapp-cubby/1.0`](https://raw.githubusercontent.com/kody-w/rapp-spine/main/specs/CUBBY.md)
- Neighborhood protocol: [`rapp-neighborhood-protocol/1.0`](https://raw.githubusercontent.com/kody-w/rapp-neighborhood-protocol/main/NEIGHBORHOOD_PROTOCOL.md)

## What a work cubby records

Each member owns exactly one directory:

```text
cubbies/<member-id>/
  cubby.json
  neighborhoods/work-cubbies.json
  show-and-tell/work-ledger.jsonl
```

`cubby.json` is the canonical `rapp-cubby/1.0` manifest. The ledger is an
append-only, sha256-linked show-and-tell artifact. It records:

- `cubby.join`
- `cubby.clock_in`
- `cubby.clock_out`

Clock-out records contain UTC start/end timestamps, exact elapsed seconds and
`HH:MM:SS`, a work summary, and evidence such as commits, PRs, workflow runs,
or public reports. Historical imports are explicitly marked
`"reconstructed": true`; they never pretend an inferred timestamp was observed.

## Join

Fork the repo if you are not a collaborator, then:

```bash
git clone https://github.com/<you>/rapp-work-cubbies
cd rapp-work-cubbies

MEMBER="<your-stable-member-id>"
git worktree add "../work-cubby-$MEMBER" -b "cubby/$MEMBER/join"
cd "../work-cubby-$MEMBER"

WORK_CUBBY_MEMBER="$MEMBER" python3 work_cubby.py init \
  --member "$MEMBER" \
  --github-login "<your-github-login>" \
  --display-name "<your display name>" \
  --purpose "Track my work shifts and evidence"

python3 scripts/rebuild_super_rar.py
python3 scripts/validate.py
git add "cubbies/$MEMBER" super-rar/index.json
git commit -m "join: $MEMBER work cubby"
git push -u origin "cubby/$MEMBER/join"
gh pr create --base main
```

The validator rejects a `cubby/<member-id>/...` branch that writes another
member's directory. The only shared file a member branch may change is the
deterministically generated `super-rar/index.json`.

## Clock in and out

Use a fresh worktree branch for a shift:

```bash
MEMBER="<your-stable-member-id>"
git worktree add "../work-cubby-$MEMBER-shift" \
  -b "cubby/$MEMBER/$(date -u +%Y%m%dT%H%M%SZ)"
cd "../work-cubby-$MEMBER-shift"

WORK_CUBBY_MEMBER="$MEMBER" python3 work_cubby.py clock-in \
  --member "$MEMBER" \
  --task "What I am starting"

# Do the work.

WORK_CUBBY_MEMBER="$MEMBER" python3 work_cubby.py clock-out \
  --member "$MEMBER" \
  --summary "What changed and why" \
  --evidence "https://github.com/owner/repo/pull/123" \
  --evidence "commit:0123456789abcdef"

python3 work_cubby.py verify
git add "cubbies/$MEMBER/show-and-tell/work-ledger.jsonl"
git commit -m "clock: $MEMBER shift"
git push -u origin HEAD
gh pr create --base main
```

## Local cubby

The public repo is the neighborhood projection. Mirror your own sanitized
cubby into the canonical local shelf:

```bash
python3 work_cubby.py mirror-local --member "$MEMBER"
```

That writes only to `~/.brainstem/cubbies/<member-id>/`. It never writes into
the brainstem grail repo and never streams an agent.

## Verify

```bash
python3 -m unittest discover -s tests -v
python3 scripts/rebuild_super_rar.py --check
python3 scripts/validate.py
```

No secrets or private transcripts belong here. Evidence should be a public URL,
commit SHA, PR, workflow run, or sanitized artifact reference.

