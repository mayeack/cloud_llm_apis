# The `ai.*` contract — cloud-LLM governance event schema

**Version 1.0.0** · Executable twin: [`shared/ai_common/schema.py`](../shared/ai_common/schema.py)

Every provider TA (Anthropic today; OpenAI, Google later) emits events in this shape at
**index time**. The shared layer (`SA-ai-governance` dashboards, saved searches, the
`AI_Governance` data model) queries **only** `ai.*` fields — never provider field names.
Splunk's `KV_MODE = json` flattens the nested object into dotted search-time fields
(`ai.vendor`, `ai.actor.email`, …).

Versioning: semver. Adding optional fields or vocabulary values = minor. Renaming,
removing, or changing meaning = major (requires coordinated SA + adapters release).

## Event shape

```json
{
  "ai": {
    "time": "2026-07-16T19:16:51Z",
    "schema_version": "1.0.0",
    "vendor": "anthropic",
    "product": "claude_enterprise",
    "record": "activity",
    "event_category": "authentication",
    "event_type": "user_signed_in_sso",
    "event_id": "activity_01ABC...",
    "action": "login",
    "outcome": "success",
    "actor":    { "email": "alice@example.com", "id": "user_01...", "type": "user_actor",
                  "ip": "10.0.0.1", "user_agent": "Mozilla/5.0 ..." },
    "org":      { "id": "org_...", "uuid": "aaaaaaaa-..." },
    "resource": { "type": "chat", "id": "chat_01..." }
  },
  "raw": { "...every provider-native field not consumed by an ai.* mapping, verbatim..." }
}
```

Serialization rules (adapter obligations):

1. `ai` is the **first** key of the event; `ai.time` is the **first** key inside it
   (index-time timestamping reads it; fixtures rely on it).
2. **Null keys are omitted**, recursively. An `ai.*`/`raw.*` field is either present with
   a real value or absent — the literal string `"null"` must never be indexed.
3. Unmapped provider fields are preserved under `raw.*` with their native names and
   nesting. Mapped values live once, under `ai.*` (no duplication).
4. All timestamps are ISO 8601 UTC (`YYYY-MM-DDTHH:MM:SSZ`). Date-only provider values
   are normalized to midnight UTC.

## Envelope — required on every event (100% coverage)

| Field | Meaning |
|---|---|
| `ai.time` | Event time: provider event time; report-period start for aggregates; collection time for snapshots |
| `ai.schema_version` | This contract's version, stamped by the adapter |
| `ai.vendor` | `anthropic` \| `openai` \| `google` |
| `ai.product` | Provider product line, e.g. `claude_enterprise` (constant per TA — never clobbered by provider dimensions; the Anthropic analytics API's own `product` column lands in `raw.product`) |
| `ai.record` | Envelope kind — see vocabulary below |
| `ai.event_category` | Governance category — see vocabulary below |

### `ai.record` vocabulary

`activity` (audit feed) · `user` / `organization` / `group` (directory snapshots) ·
`chat` / `file` (content/metadata fetches) · `summary` / `usage` / `cost` /
`user_usage` / `user_cost` / `user_activity` (analytics reports) · `spend_limit` /
`spend_limit_request` (spend controls).

### `ai.event_category` vocabulary and assignment

`authentication` · `admin_change` · `content_access` · `usage` · `cost` · `policy` · `data_export`

- **`activity` records** are classified from `ai.event_type` by **ordered
  first-match-wins glob rules** (fnmatch, case-sensitive), shipped as data in each TA
  (`bin/event_categories.json`) so new provider event types are a data-only patch.
  Precedence order is contract semantics:
  1. authentication events (`user_signed_in_*`, `user_signed_out`, `sso_login_initiated`, …)
  2. data-export events (`compliance_api_accessed`, `*data_export*`)
  3. read-only access (`*_viewed`, `*_accessed`, `*_listed` → `content_access`)
  4. content families (`*file_*`, chat/conversation access → `content_access`)
  5. admin-change families (org/project/rbac/group/memory/mcp/integration/extension/
     billing prefixes, `*api_key_*`, `*_role_updated`, exact renames/deletes → `admin_change`)
  6. default → `usage`
- **All other records** get a fixed category per `ai.record`:

| `ai.record` | category | | `ai.record` | category |
|---|---|---|---|---|
| `user`, `organization`, `group` | `policy` | | `summary`, `usage`, `user_usage`, `user_activity` | `usage` |
| `chat`, `file` | `content_access` | | `cost`, `user_cost`, `spend_limit` | `cost` |
| | | | `spend_limit_request` | `policy` |

## Audit-feed fields (required on `record=activity`)

| Field | Meaning |
|---|---|
| `ai.event_type` | Provider-native event name, verbatim |
| `ai.event_id` | Provider-native unique id |
| `ai.action` | Normalized verb: `login` \| `logout` \| `login_attempt` \| `create` \| `update` \| `delete` \| `read` \| `export` \| `request` \| `unknown` (glob rules over `event_type` suffixes) |
| `ai.outcome` | `success` \| `failure` (`*_failed`/`*_denied`/`*_rejected`/`*_blocked` → failure) |

## Identity and scope (where the provider reports them)

| Field | Meaning |
|---|---|
| `ai.actor.email` / `.id` / `.type` / `.ip` / `.user_agent` | Acting identity (activity, per-user reports, spend limits). Actor-union extras (api-key ids, SCIM/IdP details) stay in `raw.*` |
| `ai.org.id` / `.uuid` | Tenancy |
| `ai.resource.type` | `org` \| `project` \| `user` \| `group` \| `identity` \| `api_key` \| `chat` \| `file` \| `memory` \| `integration` \| `other` (glob rules over `event_type`; fixed per record kind for snapshots) |
| `ai.resource.id` | Provider id of the touched object when determinable |

## Measures (report records)

| Field | On records | Meaning |
|---|---|---|
| `ai.model` | `usage` | Model id (omitted when the provider reports an `all` rollup) |
| `ai.usage.input_tokens` | `usage`, `user_usage` | Total input tokens (Anthropic: uncached + cache_read + cache_creation; splits stay in `raw.*`) |
| `ai.usage.output_tokens` / `.total_tokens` | `usage`, `user_usage` | Output / input+output |
| `ai.cost.amount_usd` | `cost`, `user_cost` | Cost in USD — converted **once, at the adapter** (provider cents never leak into SPL) |
| `ai.cost.currency` | cost records | ISO currency (`USD`) |
| `ai.cost.limit_usd` / `.spend_usd` / `.utilization_pct` | `spend_limit` | Effective limit, period-to-date spend, utilization (0-limit seats = 100.0) |
| `ai.cost.requested_limit_usd` | `spend_limit_request` | Requested new limit (period spend in `.spend_usd`) |
| `ai.adoption.daily_active_users` / `.weekly_active_users` / `.monthly_active_users` | `summary` | Active-user counts |
| `ai.adoption.seats` / `.pending_invites` | `summary` | Licensing state |
| `ai.adoption.daily_rate` / `.weekly_rate` / `.monthly_rate` | `summary` | Adoption percentages as reported |

## Anthropic reference mapping (informative)

Activity: `id→ai.event_id`, `created_at→ai.time`, `type→ai.event_type`,
`actor.{email_address,user_id,type,ip_address,user_agent}→ai.actor.*`,
`organization_id/uuid→ai.org.*`, `claude_project_id|claude_chat_id|file_id→ai.resource.id`
(type from event family). Detail fields (`filename`, `current_role`,
`claude_code_metrics.*`, …) → `raw.*`.
Reports: `starting_at|date→ai.time`, `email/user_id→ai.actor.*`,
`total_cost_usd→ai.cost.amount_usd`, `spend_limit_usd→ai.cost.limit_usd`,
`period_spend_usd→ai.cost.spend_usd`, token counters → `ai.usage.*`,
`daily_active_user_count→ai.adoption.daily_active_users`, etc.

## Conformance

An adapter is conformant when `tests/test_adapter_conformance.py` passes over its raw
fixtures: required coverage, closed vocabularies, no nulls/`"null"` anywhere, USD
conversion exactness, `ai`-first/`time`-first key order. The Anthropic fixtures under
`tests/fixtures/anthropic/` are the reference corpus.
