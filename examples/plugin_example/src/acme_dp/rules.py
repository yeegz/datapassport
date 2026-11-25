"""Importing this module registers the rules and the metric."""

import datapassport as dp


@dp.rule("no_lowercase")
def no_lowercase(ctx: dp.RuleContext) -> dp.Outcome:
    """Column-scoped: values must not contain lower-case letters (e.g. SKUs)."""
    bad = ctx.count_where(f"{ctx.col} IS NOT NULL AND {ctx.col} <> upper({ctx.col})")
    return dp.Outcome(passed=bad == 0, observed=bad, failing_rows=bad, message=f"{bad} values with lower case")


@dp.rule("max_share_of_top_value")
def max_share_of_top_value(ctx: dp.RuleContext) -> dp.Outcome:
    """Column-scoped, profile-only: the most frequent value may not exceed `max` of rows."""
    limit = float(ctx.params.get("max", 0.5))
    cats = ctx.passport.columns[ctx.column].categories
    share = (cats.counts[0] / ctx.passport.rows) if cats and cats.counts else 0.0
    return dp.Outcome(passed=share <= limit, observed=round(share, 4),
                      message=f"top value covers {share:.1%} of rows (limit {limit:.0%})")


@dp.metric("p_whitespace_padded", types=["string"])
def p_whitespace_padded(ctx: dp.MetricContext) -> float:
    return ctx.scalar(f"avg(CASE WHEN {ctx.col} <> trim({ctx.col}) THEN 1.0 ELSE 0.0 END)")
