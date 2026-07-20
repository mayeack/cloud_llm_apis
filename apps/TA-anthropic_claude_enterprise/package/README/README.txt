Anthropic Claude Enterprise Add-on for Splunk v2.0.0

Created by Manan Grover.

See README.md in the add-on source repo for installation, configuration, and troubleshooting.

Release notes:

v2.0.0 (BREAKING - new event shape and index):
- Events now emit the provider-neutral ai.* contract (nested ai/raw JSON,
  docs/ai-schema.md v1.0.0); flat provider fields are gone
- Default index is cloud_llm_apis; shared dashboards moved to SA-ai-governance
  (this add-on keeps Claude Code & MCP and TA Operations dashboards)
- Event classification is data-driven (bin/event_categories.json)
- Null values are omitted at the adapter (no more literal "null" strings);
  cents-to-USD conversion happens exactly once, at the adapter
- Stock CIM eventtypes/tags removed in favor of the AI_Governance data model

v1.1.0:
- Compliance Activity Feed, Directory Sync, Analytics Reports, and on-demand Content collection
- CIM Authentication and Change eventtypes
- Security Audit, Governance, and Tokenomics dashboards
