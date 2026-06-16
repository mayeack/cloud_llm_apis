[anthropic_compliance_activity://<name>]
* Ingests the Anthropic Compliance API Activity Feed.
api_key = <password>
* Compliance Access Key or Admin API key with read:compliance_activities.
* Moved to encrypted storage/passwords on first run; never stored in clear text.
base_url = <string>
* Default https://api.anthropic.com
endpoint = <string>
* Default /v1/compliance/activities
index = <string>
interval = <integer>
* Polling interval in seconds. Default 60.
limit = <integer>
* Page size, max 5000. Default 5000.
initial_lookback_minutes = <integer>
* Used only when no checkpoint exists. Default 60.
activity_types = <comma-separated list>
* Optional filter, sent as repeated activity_types[] params.
organization_ids = <comma-separated list>
* Optional filter.
actor_ids = <comma-separated list>
* Optional filter.
checkpoint_key = <string>
* Unique checkpoint namespace. Defaults to the stanza name.
include_raw_content = <boolean>
* Default false. Raw content endpoints require additional scopes.
redact_actor_email = <boolean>
* Default false. When true, actor email is pseudonymized before indexing.
redact_ip_address = <boolean>
* Default false. When true, actor IP is masked before indexing.
timeout = <integer>
* HTTP timeout seconds. Default 30.
verify_ssl = <boolean>
* Default true.
proxy = <string>
* Optional https proxy URL.

[anthropic_admin_usage://<name>]
* Ingests the Claude Console Usage and Cost Admin API.
api_key = <password>
* Admin API key (sk-ant-admin...). Moved to encrypted storage/passwords.
base_url = <string>
* Default https://api.anthropic.com
anthropic_version = <string>
* Default 2023-06-01
index = <string>
interval = <integer>
* Default 300.
bucket_width = <string>
* 1m, 1h, or 1d. Default 1m.
initial_lookback_minutes = <integer>
* Default 60.
group_by_usage = <comma-separated list>
* Default model,workspace_id,api_key_id,service_tier,context_window,inference_geo
group_by_cost = <comma-separated list>
* Default workspace_id,description
models = <comma-separated list>
workspace_ids = <comma-separated list>
api_key_ids = <comma-separated list>
service_tiers = <comma-separated list>
context_windows = <comma-separated list>
inference_geos = <comma-separated list>
speeds = <comma-separated list>
collect_usage = <boolean>
* Default true.
collect_cost = <boolean>
* Default true.
checkpoint_key = <string>
timeout = <integer>
verify_ssl = <boolean>
proxy = <string>

[anthropic_enterprise_analytics://<name>]
* Ingests the Claude Enterprise Analytics API.
api_key = <password>
* Analytics API key with read:analytics. Moved to encrypted storage/passwords.
base_url = <string>
* Default https://api.anthropic.com/v1/organizations/analytics
index = <string>
interval = <integer>
* Default 3600.
bucket_width = <string>
* Default 1h for usage; cost is collected daily.
initial_lookback_hours = <integer>
* Default 24. Window is clamped to the API maximum of 31 days.
collect_usage_report = <boolean>
collect_cost_report = <boolean>
collect_user_usage_report = <boolean>
collect_user_cost_report = <boolean>
collect_engagement_users = <boolean>
* Default false (higher sensitivity).
collect_engagement_summaries = <boolean>
collect_engagement_projects = <boolean>
collect_engagement_skills = <boolean>
collect_engagement_connectors = <boolean>
usage_group_by = <comma-separated list>
cost_group_by = <comma-separated list>
products = <comma-separated list>
models = <comma-separated list>
user_ids = <comma-separated list>
exclude_deleted_users = <boolean>
engagement_delay_days = <integer>
* Default 3. Engagement data has a 3-day lag.
engagement_initial_lookback_days = <integer>
* Default 7.
redact_actor_email = <boolean>
checkpoint_key = <string>
timeout = <integer>
verify_ssl = <boolean>
proxy = <string>
