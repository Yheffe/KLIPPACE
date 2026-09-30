# Agent Guidelines & Local Model Delegation

## Local LLM Delegation (LM Studio / Gemma 4)
The user has a powerful local instance of Google Gemma 4 running in LM Studio via the `lmstudio` MCP server.
To conserve cloud tokens, always adhere to the following workflow:

1. **Delegate Heavy Reasoning & Analysis to Gemma**:
   - For log troubleshooting, error analysis, and root-cause diagnostics, feed the relevant log snippets to `lmstudio:ask_gemma`.
   - For writing substantial code blocks, complex scripts, or new macros, use `lmstudio:generate_code`.
   - For reviewing diffs, bug audits, or refactoring suggestions, use `lmstudio:review_code`.

2. **Antigravity (Cloud Agent) Responsibilities**:
   - Act as the orchestrator: fetch relevant files, extract key log lines, and maintain environment integrity.
   - Execute file edits, remote printer commands, and deployments.
   - Keep final user responses concise, clear, and direct without duplicating lengthy explanations already computed by Gemma.
