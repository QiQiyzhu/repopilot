from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any

from .security import redact, resolve_inside, visible_files


def token_estimate(text: str) -> int:
    # Conservative byte-based estimate; usage returned by providers remains authoritative.
    return max(1, math.ceil(len(text.encode("utf-8")) / 3))


class RepositoryContext:
    def __init__(self, root: Path):
        self.root = root

    def retrieve(self, query: str) -> list[dict[str, Any]]:
        terms = set(re.findall(r"[\w-]+", query.lower()))
        candidates: list[dict[str, Any]] = []
        files = visible_files(self.root)
        candidates.append(
            {
                "source": "repository-tree",
                "path": "<tree>",
                "start_line": 1,
                "content": "\n".join(files),
                "score": 2.0,
            }
        )
        for file in files:
            try:
                path = resolve_inside(self.root, file)
                if path.stat().st_size > 300000:
                    continue
                lines = path.read_text(encoding="utf-8").splitlines()
            except (UnicodeError, ValueError, OSError):
                continue
            if Path(file).suffix.lower() not in {
                ".py",
                ".ts",
                ".tsx",
                ".js",
                ".json",
                ".md",
                ".yaml",
                ".yml",
                ".toml",
                ".txt",
            }:
                continue
            for start in range(0, len(lines), 55):
                content = "\n".join(lines[start : start + 65])
                words = re.findall(r"[\w-]+", content.lower())
                frequency = {term: words.count(term) for term in terms}
                score = sum(
                    2.2 * n / (n + 1.2 * (0.25 + 0.75 * len(words) / 250))
                    for n in frequency.values()
                    if n
                )
                score += sum(2 for term in terms if term in file.lower())
                is_doc = file.lower().endswith("readme.md") or file.startswith("docs/")
                score += 0.8 if is_doc else 0
                symbol = bool(re.search(r"\b(?:class|function|def|interface|export)\b", content))
                candidates.append(
                    {
                        "source": "docs"
                        if is_doc
                        else "symbol-search"
                        if symbol
                        else "keyword-search",
                        "path": file,
                        "start_line": start + 1,
                        "content": content,
                        "score": round(score, 4),
                    }
                )
        return candidates


class ContextBuilder:
    def __init__(self, root: Path, budget: int, strategy: str = "structured"):
        self.source = RepositoryContext(root)
        self.budget = budget
        self.strategy = strategy

    def build(
        self,
        query: str,
        *,
        observations: list[str] | None = None,
        diff: str = "",
        failures: list[str] | None = None,
        memories: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        candidates = self.source.retrieve(query)
        for source, contents in [
            ("previous-tool-result", (observations or [])[-3:]),
            ("failing-test-output", (failures or [])[-2:]),
            ("git-diff", [diff] if diff else []),
        ]:
            candidates.extend(
                {
                    "source": source,
                    "path": "<observation>",
                    "start_line": 1,
                    "content": text,
                    "score": 30.0,
                }
                for text in contents
            )
        for memory in memories or []:
            candidates.append(
                {
                    "source": "trusted-memory",
                    "path": memory["id"],
                    "start_line": 1,
                    "content": memory["content"],
                    "provenance": memory["provenance"],
                    "score": 20.0,
                }
            )
        if self.strategy == "structured":
            candidates.sort(key=lambda x: (-x["score"], x["path"], x["start_line"]))
        selected, discarded, used = [], [], 0
        for item in candidates:
            item["content"] = redact(item["content"])
            cost = token_estimate(item["content"]) + 30
            if used + cost <= self.budget:
                item["tokens"] = cost
                selected.append(item)
                used += cost
            else:
                discarded.append(
                    {
                        "path": item["path"],
                        "start_line": item["start_line"],
                        "tokens": cost,
                        "reason": "context_budget",
                    }
                )
        return {
            "strategy": self.strategy,
            "token_estimator": "utf8-bytes/3 + metadata",
            "budget": self.budget,
            "context_tokens": used,
            "retrieved_files": sorted(
                {c["path"] for c in selected if not c["path"].startswith("<")}
            ),
            "retrieved_chunks": selected,
            "discarded_context": discarded,
        }
