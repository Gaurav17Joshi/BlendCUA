"""
Central model configuration for BlendCUA-Hermes.

One place to swap models/providers. `blendcua_agent.py` and `mcp_dispatch_server.py`
both read MODELS["executor"] and MODELS["reviewer"].

Each entry is (provider, model) as accepted by hermes-agent's AIAgent:
  provider="anthropic"  -> native Anthropic Messages API, ANTHROPIC_API_KEY
  provider="openai"     -> native OpenAI API, OPENAI_API_KEY
  provider=None + OpenRouter-format model string ("anthropic/claude-sonnet-5")
                         -> routed through OpenRouter, OPENROUTER_API_KEY

Both roles on GPT-5.6 Luna at max reasoning effort. The reviewer is a real
hermes-agent conversation (run_agentic_reviewer in blendcua_core.py) that
already reads MODELS["reviewer"] dynamically and already branches on
OPENAI_REASONING_EFFORT for an "openai" provider, same as the executor —
no code changes needed to switch it, just this config.
"""

MODELS = {
    "executor": {"provider": "openai", "model": "gpt-5.6-luna"},
    # "executor": {"provider": "anthropic", "model": "claude-sonnet-5"},

    "reviewer": {"provider": "openai", "model": "gpt-5.6-luna"},
    # "reviewer": {"provider": "anthropic", "model": "claude-sonnet-5"},

    # Added for the self-improvement loop. The planner does one long
    # image-heavy call; the curator does one long code-reading call. Both are
    # cheap relative to a rollout, so neither is a place to economise.
    "planner": {"provider": "openai", "model": "gpt-5.6-luna"},
    "curator": {"provider": "openai", "model": "gpt-5.6-luna"},

    # Method b's CHECKER (Checker/checker_agent.py): looks at a finished model
    # and finds its defects. Image-heavy and judgement-heavy in the same way
    # the planner is, and it sits upstream of every remedy decision in the
    # loop -- a defect it misses is a defect the harness never learns from --
    # so it gets the same model rather than a cheaper one.
    "checker": {"provider": "openai", "model": "gpt-5.6-luna"},
}

# GPT-5.6 models support a reasoning_effort setting: none/low/medium/high/
# xhigh/max. Applied only when the executor's provider is "openai" (see
# blendcua_core.py) — Claude uses a different mechanism (thinking budget),
# untouched here.
OPENAI_REASONING_EFFORT = "max"

# hermes-agent's own built-in pricing table (agent/usage_pricing.py,
# "official_docs_snapshot") is a point-in-time snapshot and can go stale
# when a provider cuts prices — confirmed directly: our installed hermes-
# agent still prices gpt-5.6-luna at the PRE-CUT $1.00/$6.00 per million,
# but OpenAI's actual current price (checked 2026-08-04) is $0.20/$1.20 —
# an exact 80% cut on both input and output, i.e. hermes's reported cost
# for this model is 5x too high. Correction factors below are applied in
# blendcua_core.UsageAggregate.log_conversation_result() as a flat
# multiplier on hermes's reported estimated_cost_usd, the same pattern
# BlendCuagent2 used to correct the Claude SDK's own Sonnet-billed-at-Opus-
# rates bug. Remove/update the entry once hermes-agent ships a refreshed
# snapshot with the correct price.
COST_CORRECTION: dict[str, float] = {
    "gpt-5.6-luna": 0.2,
}

# The reviewer is now a real hermes-agent conversation (blendcua_core.
# run_agentic_reviewer), same as the Executor/Subagent — its cost comes
# through hermes-agent's own per-provider pricing engine via
# UsageAggregate.log_conversation_result(), same COST_CORRECTION table
# above if it ever needs a similar stale-price fix. No separate reviewer
# price table needed anymore.
