# AI Governance for Splunk

Splunk as the control plane for cloud-LLM governance — security auditing, adoption, and
cost across **multiple AI providers**. Events from every provider are normalized at index
time to one versioned contract (`ai.*`), so the dashboards, detections, and data model are
written once and work for whichever providers you install.

Anthropic Claude Enterprise ships today as the reference adapter. Adding OpenAI or Gemini
means writing an adapter and a config page — **no changes to the shared layer**.

## The apps

Three separately packaged apps, because they deploy to three different tiers.

| App | Version | Install on | What it is |
|---|---|---|---|
| `TA-anthropic_claude_enterprise` | 2.0.0 | IDM / heavy forwarder, **and** search heads | Collection add-on (UCC-built): config UI, 4 modular inputs, the Anthropic → `ai.*` adapter, the 14 `anthropic:*` sourcetypes, and two Claude-specific dashboards |
| `SA-ai-governance` | 1.0.0 | Search heads | The shared, **provider-neutral** layer: 3 dashboards, 10 detections, the `ai_governance_index` macro, and the accelerated `AI_Governance` data model |
| `TA-ai-governance-indexes` | 1.0.0 | Indexers | `indexes.conf` only — defines `cloud_llm_apis` |

Inputs are disabled on search heads; the TA is installed there for its search-time
knowledge (sourcetype props). Keeping `indexes.conf` in its own app leaves the other two
Splunk Cloud–vettable.

### Naming rule

Anything in the shared layer is provider-neutral — `ai_governance_*` objects, "AI Governance - *"
saved searches. Provider names are reserved for genuinely provider-specific artifacts, which
live in that provider's TA (its sourcetypes, its Claude Code / MCP dashboard, its ops view).
A build check enforces it: `grep -icE 'claude|anthropic'` over the packaged shared apps must
return **0**.

Provider identity travels as *values* in neutral fields — `ai.vendor="anthropic"` — never as
field or object names.

## Architecture

```
provider API → TA adapter → ai.* + raw.*  →  index=cloud_llm_apis  →  SA-ai-governance
               (index time)                                           (dashboards, alerts,
                                                                       AI_Governance model)
```

Each event is `{"ai": {…contract…}, "raw": {…provider-native, verbatim…}}`, flattened by
`KV_MODE=json` into dotted search-time fields (`ai.vendor`, `ai.actor.email`, `ai.cost.amount_usd`).
Nothing is lost: fields the contract does not model are preserved under `raw.*`.

The full contract — field list, the closed `ai.event_category` vocabulary
(`authentication`, `admin_change`, `content_access`, `usage`, `cost`, `policy`, `data_export`),
classification precedence, and adapter obligations — is **[docs/ai-schema.md](docs/ai-schema.md)**,
with an executable twin at `shared/ai_common/schema.py`. Treat it as the expensive-to-change
artifact: three adapters and an accelerated data model depend on it.

Two things the adapter owns so SPL never has to:

- **Nulls are omitted recursively.** No field ever indexes as the literal string `"null"`.
- **Money is converted once.** Provider cents become `ai.cost.amount_usd` at the adapter, so
  no `coalesce(..., tonumber(amount)/100)` fallbacks in panels.

Event classification is **data, not code**: `apps/<TA>/package/bin/event_categories.json` holds
ordered first-match-wins glob rules. A new provider event type is a data-only patch release.

## Layout

```
apps/
  TA-anthropic_claude_enterprise/   globalConfig.json + package/  (UCC source, not build output)
  SA-ai-governance/                 plain app, copied verbatim at build
  TA-ai-governance-indexes/         plain app, copied verbatim at build
shared/ai_common/                   schema, adapter base, rules engine, input utils, checkpointing
docs/                               ai-schema.md (the contract) · ucc-classification.md (build ledger)
build/                              build.sh · deploy.sh
tests/                              fixtures, conformance suite, regression runner, harness scripts
dist/ · build_out/                  build products (gitignored)
```

`shared/ai_common/` is copied into each TA's `bin/` at build time rather than imported across
apps — Splunk apps cannot reliably import each other's Python, so each TA stays
runtime-self-contained with one source of truth in git.

## Build and deploy

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt

build/build.sh                 # ucc-gen the TA, inject ai_common, package all 3 to dist/
build/build.sh --no-dist       # build only, skip tarballs

build/deploy.sh --dry-run      # always look first
build/deploy.sh --restart      # rsync to $SPLUNK_HOME/etc/apps (default /opt/splunk104), restart
build/deploy.sh --refresh      # KO-only changes: deploy, then print the /debug/refresh URL
```

> **The repo is the source of truth.** Apps under `etc/apps/` are build artifacts — never
> hand-edit their `default/`. The TA is regenerated by `ucc-gen` from `package/`, and the next
> build silently overwrites anything edited in a generated path.
> [docs/ucc-classification.md](docs/ucc-classification.md) records exactly which files are
> generated versus hand-authored.

`deploy.sh` excludes `local/` and `local.meta`, which is load-bearing: that is where instance
state lives — credentials, configured inputs, alert enables, and the test harness. It survives
every deploy. Never add `--delete-excluded`.

## Tests

Conformance runs anywhere, no Splunk required. It is the contract test every provider
adapter must pass:

```sh
python3 tests/test_adapter_conformance.py      # or: pytest tests/
```

It asserts each adapter output byte-matches its committed oracle (which pins key order),
required fields are present, vocabularies are closed, no nulls survive, and USD conversion
is exact. Regenerate oracles after an intentional adapter change with
`tests/generate_fixtures.py` (`--check` fails if they are stale).

The end-to-end suite needs a dev Splunk. There is **no test app** — the harness writes into
the main apps' `local/` layer, inside `# BEGIN/END ai-governance-harness` markers:

```sh
tests/setup_harness.sh                          # test index + 14 fixture monitors (restart once)
RUN_ID=$(tests/load_fixtures.sh | tail -1)      # spool fixtures, stamped with a fresh run id
export SPLUNK_TOKEN=…                           # or SPLUNK_USERNAME / SPLUNK_PASSWORD
tests/run_regression.py --run-id "$RUN_ID"      # every panel + saved search, run-scoped
tests/teardown_harness.sh                       # remove harness config and spool
```

`run_regression.py` extracts every dashboard panel query and saved search, repoints the index
macros at the test index, and asserts against `tests/expected.json`. It exits **2** on a
coverage gap — a panel with no expectation is a failure, not a pass.

## Adding a provider

1. Scaffold a UCC add-on under `apps/TA-<vendor>_<product>/`.
2. Subclass `ProviderAdapter` (`shared/ai_common/adapter.py`); set `vendor` / `product` and map
   the provider's payloads onto `ai.*`, leaving everything else in `raw.*`.
3. Write `package/bin/event_categories.json` mapping its native event vocabulary onto the
   contract's categories, actions, resource types, and outcomes.
4. Add raw fixtures under `tests/fixtures/<vendor>/raw/<kind>/`, generate the oracles, and make
   `test_adapter_conformance.py` pass.
5. Point its inputs at `cloud_llm_apis`.

`SA-ai-governance` and `TA-ai-governance-indexes` need no changes — the new provider appears in
the dashboards' provider selector automatically, because the choices come from the data.

Keep provider-specific views in the provider's TA. Some concepts genuinely do not generalize
(Claude Code tool-acceptance metrics have no OpenAI analogue); those belong beside their
provider, not in the shared app.
