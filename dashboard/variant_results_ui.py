"""Evaluation Cycle — evaluate-loop variant results (T3.4) UI."""

from __future__ import annotations

from typing import Any, Optional

import streamlit as st


def render_variant_results(
    variants: list[dict],
    *,
    original_percentile: Optional[float] = None,
) -> None:
    """Render ranked evaluate-loop variants with one-click apply."""
    st.subheader(f"Variants ({len(variants)})")

    if not variants:
        st.info("No variants were generated.")
        return

    for i, variant in enumerate(variants, start=1):
        with st.container(border=True):
            header_col, metric_col = st.columns([3, 1])
            with header_col:
                label = "Top Variant" if i == 1 else f"Variant {i}"
                st.markdown(f"**{label}** &nbsp; `{variant.get('strategy_label', '')}`")
                st.write(variant.get("rationale", ""))
            with metric_col:
                pct = variant.get("predicted_engagement_percentile", 0)
                delta = (
                    f"{pct - original_percentile:+.0f}"
                    if original_percentile is not None
                    else None
                )
                st.metric("Percentile", f"{pct:.0f}", delta=delta)
                st.metric(
                    "Engagements",
                    variant.get("predicted_total_engagement", "—"),
                )

            st.text_area(
                f"v{i}",
                value=variant.get("variant_text", ""),
                height=110,
                label_visibility="collapsed",
            )

            if st.button(f"Use Variant {i}", key=f"apply_{i}", type="secondary"):
                st.session_state.draft_text = variant.get("variant_text", "")
                st.session_state.eval_result = None
                st.rerun()


def render_similar_posts_expander(similar_posts: list[Any], *, limit: int = 5) -> None:
    """Compact neighbor context expander."""
    with st.expander(
        f"Similar posts used as context ({len(similar_posts)} retrieved)",
        expanded=False,
    ):
        for j, post in enumerate(similar_posts[:limit], start=1):
            st.markdown(
                f"**#{j}** &nbsp; `{post.post_id}` · "
                f"p{post.engagement_percentile:.0f} · "
                f"distance={post.cosine_distance:.3f}"
            )
            preview = post.content[:300]
            if len(post.content) > 300:
                preview += "…"
            st.caption(preview)
            if j < min(limit, len(similar_posts)):
                st.divider()
