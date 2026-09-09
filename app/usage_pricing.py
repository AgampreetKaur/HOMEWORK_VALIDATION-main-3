"""
Gemini pricing, for computing cost_usd on every token_usage_logs row.

Rates are USD per 1,000,000 tokens, Standard paid tier. Gemini 3.6 Flash's
rate is the introductory rate through December 31, 2026; it rises to
$1.50 / $7.50 after that — update PRICING when it does. New rows pick up
the new rate automatically; existing rows keep the cost that was true when
they were logged, since cost_usd is stored once, not recalculated.

Add a model here when it's introduced, or its rows will show cost_usd as
NULL rather than an incorrect $0.00.
"""

from typing import Optional


# input / output, USD per 1,000,000 tokens
PRICING = {
    "gemini-3.6-flash": {"input": 0.75, "output": 3.75},
    "gemini-3.5-flash": {"input": 1.50, "output": 9.00},
    "gemini-3.7-flash": {"input": 0.75, "output": 3.75},
    "gemini-3.5-flash-lite": {"input": 0.15, "output": 1.25},
    "gemini-3.1-pro": {"input": 2.00, "output": 12.00},
    "gemini-2.5-flash": {"input": 0.30, "output": 2.50},
    "gemini-2.5-flash-lite": {"input": 0.10, "output": 0.40},
    "gemini-2.5-pro": {"input": 1.25, "output": 10.00},
}


def estimate_cost_usd(
    model: str,
    input_tokens: int,
    output_tokens: int,
    thoughts_tokens: int = 0,
) -> Optional[float]:
    """
    Returns the estimated cost in USD for one request, or None if `model`
    isn't in PRICING (rather than guessing).

    Thinking tokens are billed at the OUTPUT rate (Google's own pricing
    docs are explicit about this), so they're added to output_tokens here
    rather than ignored — this is exactly the gap that made total_tokens
    look inflated before thoughts_tokens was captured separately.
    """

    rates = PRICING.get(model)
    if not rates:
        return None

    billable_output = (output_tokens or 0) + (thoughts_tokens or 0)

    cost = (
        (input_tokens or 0) / 1_000_000 * rates["input"]
        + billable_output / 1_000_000 * rates["output"]
    )

    return round(cost, 8)
