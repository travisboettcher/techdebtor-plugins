---
type: regex
match: not_contains
---
"layer":\s*"(?!(tests|types|coverage|unit_integration_split|mutation|api_fuzzing|contract|smoke|sast|dependency_scan|secret_scan|intent|flow_metrics|dev_env|context|agent_config|codegen)")[^"]*"
