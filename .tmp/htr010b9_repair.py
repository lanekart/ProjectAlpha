from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"{path}: expected one repair anchor, found {count}: {old[:80]!r}"
        )
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


bridge = "alpha/benchmark_replay/governed_adaptive_publication_bridge.py"

replace_once(
    bridge,
    "    eligibility = tuple(\n"
    "        {\n"
    "            \"recommendation_symbol\": item.recommendation_symbol,\n",
    "    eligibility: tuple[dict[str, object], ...] = tuple(\n"
    "        {\n"
    "            \"recommendation_symbol\": item.recommendation_symbol,\n",
)

replace_once(
    bridge,
    "            \"- Recommendation, approval, portfolio, execution and production influence remain false.\",\n",
    "            (\n"
    "                \"- Recommendation, approval, portfolio, execution and \"\n"
    "                \"production influence remain false.\"\n"
    "            ),\n",
)
