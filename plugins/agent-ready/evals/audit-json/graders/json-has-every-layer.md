---
type: regex
match: contains
# The pattern sits here, not in the body, so the prose linter does not read it as a sentence.
pattern: '"layers":\s*\[(?=[\s\S]*"layer":\s*"tests")(?=[\s\S]*"layer":\s*"types")(?=[\s\S]*"layer":\s*"coverage")(?=[\s\S]*"layer":\s*"unit_integration_split")(?=[\s\S]*"layer":\s*"mutation")(?=[\s\S]*"layer":\s*"api_fuzzing")(?=[\s\S]*"layer":\s*"contract")(?=[\s\S]*"layer":\s*"smoke")(?=[\s\S]*"layer":\s*"sast")(?=[\s\S]*"layer":\s*"dependency_scan")(?=[\s\S]*"layer":\s*"secret_scan")(?=[\s\S]*"layer":\s*"intent")(?=[\s\S]*"layer":\s*"flow_metrics")(?=[\s\S]*"layer":\s*"dev_env")(?=[\s\S]*"layer":\s*"context")(?=[\s\S]*"layer":\s*"agent_config")(?=[\s\S]*"layer":\s*"codegen")'
---
