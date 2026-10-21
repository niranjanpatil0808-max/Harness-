"""Context graph.

Parse every source file with `ast`, record what is defined where (functions,
classes, methods, module constants) and how those definitions connect (calls,
name references, imports). For a task, rank the graph with PageRank
personalized to the names the tests and description mention (the idea behind
Aider's repo map), then show the model:

- the full text of the most relevant files (these are the files it may edit),
- read-only snippets of closely related definitions from other files,
- a one-line-per-symbol map of everything else.
"""

from __future__ import annotations

import ast
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .loop import Task

REVERSE_WEIGHT = 0.3  # callers of a seed matter too, but less than what it calls
DAMPING = 0.85
FILE_SHARE = 0.3  # a file is shown in full if it scores at least this share of the top file
SNIPPETS = 4
SNIPPET_SHARE = 0.05  # snippets must score at least this share of the best node


@dataclass
class Node:
    id: str  # "file.py::name" or "file.py::Class.method"
    file: str
    name: str  # bare name used for resolution
    kind: str  # function | class | method | constant
    signature: str
    source: str


@dataclass
class ContextGraph:
    nodes: dict[str, Node] = field(default_factory=dict)
    edges: dict[str, dict[str, str]] = field(default_factory=lambda: defaultdict(dict))  # src -> {dst: kind}
    budget_chars: int = 8000

    # --- building ---------------------------------------------------------

    @classmethod
    def build(cls, sources: dict[str, str], budget_chars: int = 8000) -> "ContextGraph":
        graph = cls(budget_chars=budget_chars)
        trees = {}
        for path, code in sources.items():
            try:
                trees[path] = ast.parse(code)
            except SyntaxError:
                continue  # an unparsable file still shows up in the map as a plain file
            graph._collect_defs(path, code, trees[path])
        by_name: dict[str, list[str]] = defaultdict(list)
        for node in graph.nodes.values():
            by_name[node.name].append(node.id)
        for path, tree in trees.items():
            graph._collect_edges(path, tree, by_name)
        return graph

    def _add(self, path: str, code: str, item: ast.AST, name: str, kind: str, prefix: str = "") -> None:
        source = ast.get_source_segment(code, item) or ""
        signature = source.splitlines()[0].strip() if source else name
        node_id = f"{path}::{prefix}{name}"
        self.nodes[node_id] = Node(node_id, path, name, kind, signature, source)

    def _collect_defs(self, path: str, code: str, tree: ast.Module) -> None:
        module = path.removesuffix(".py").replace("/", ".")
        self.nodes[f"{path}::<module>"] = Node(f"{path}::<module>", path, module, "module", path, "")
        for item in tree.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._add(path, code, item, item.name, "function")
            elif isinstance(item, ast.ClassDef):
                self._add(path, code, item, item.name, "class")
                for sub in item.body:
                    if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        self._add(path, code, sub, sub.name, "method", prefix=f"{item.name}.")
            elif isinstance(item, (ast.Assign, ast.AnnAssign)):
                targets = item.targets if isinstance(item, ast.Assign) else [item.target]
                for target in targets:
                    if isinstance(target, ast.Name):
                        self._add(path, code, item, target.id, "constant")

    def _owner_scopes(self, path: str, tree: ast.Module):
        """Yield (node_id, ast_subtree) for every top-level definition and method."""
        for item in tree.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                yield f"{path}::{item.name}", item
            elif isinstance(item, ast.ClassDef):
                yield f"{path}::{item.name}", item
                for sub in item.body:
                    if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        yield f"{path}::{item.name}.{sub.name}", sub
            elif isinstance(item, (ast.Assign, ast.AnnAssign)):
                targets = item.targets if isinstance(item, ast.Assign) else [item.target]
                for target in targets:
                    if isinstance(target, ast.Name):
                        yield f"{path}::{target.id}", item

    def _collect_edges(self, path: str, tree: ast.Module, by_name: dict[str, list[str]]) -> None:
        module_names = {n.name: n.file for n in self.nodes.values() if n.kind == "module"}
        for owner, subtree in self._owner_scopes(path, tree):
            for sub in ast.walk(subtree):
                if isinstance(sub, ast.Call):
                    func = sub.func
                    name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else None
                    self._link(owner, name, by_name, "calls")
                elif isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load):
                    self._link(owner, sub.id, by_name, "references")
                elif isinstance(sub, ast.Attribute):
                    self._link(owner, sub.attr, by_name, "references")
        # Imports: file -> imported definition (from x import y) or file -> file (import x).
        here = f"{path}::<module>"
        for item in ast.walk(tree):
            if isinstance(item, ast.ImportFrom) and item.module in module_names:
                target_file = module_names[item.module]
                for alias in item.names:
                    target = f"{target_file}::{alias.name}"
                    if target not in self.nodes:
                        target = f"{target_file}::<module>"
                    self.edges[here][target] = "imports"
            elif isinstance(item, ast.Import):
                for alias in item.names:
                    if alias.name in module_names:
                        self.edges[here][f"{module_names[alias.name]}::<module>"] = "imports"

    def _link(self, owner: str, name: str | None, by_name: dict[str, list[str]], kind: str) -> None:
        if not name or owner not in self.nodes:
            return
        for target in by_name.get(name, []):
            if target != owner and target not in self.edges[owner]:
                self.edges[owner][target] = kind

    # --- ranking ----------------------------------------------------------

    def rank(self, seeds: set[str], iterations: int = 40) -> dict[str, float]:
        """Personalized PageRank; `seeds` are node ids the random walk restarts from."""
        ids = list(self.nodes)
        if not ids:
            return {}
        seeds = {s for s in seeds if s in self.nodes} or set(ids)
        restart = {i: (1 / len(seeds) if i in seeds else 0.0) for i in ids}
        weighted: dict[str, dict[str, float]] = defaultdict(dict)
        for src, targets in self.edges.items():
            for dst in targets:
                if src in self.nodes and dst in self.nodes:
                    weighted[src][dst] = weighted[src].get(dst, 0) + 1.0
                    weighted[dst][src] = weighted[dst].get(src, 0) + REVERSE_WEIGHT
        score = dict(restart)
        for _ in range(iterations):
            nxt = {i: (1 - DAMPING) * restart[i] for i in ids}
            for src in ids:
                out = weighted.get(src)
                if not out:
                    # Dangling node: send its mass back to the seeds.
                    for i in ids:
                        nxt[i] += DAMPING * score[src] * restart[i]
                    continue
                total = sum(out.values())
                for dst, w in out.items():
                    nxt[dst] += DAMPING * score[src] * w / total
            score = nxt
        return score

    def seeds_for(self, task: "Task") -> set[str]:
        """Definitions named in the tests or the description."""
        mentioned: set[str] = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", task.description))
        for code in task.tests.values():
            try:
                tree = ast.parse(code)
            except SyntaxError:
                continue
            for item in ast.walk(tree):
                if isinstance(item, ast.ImportFrom):
                    mentioned.update(alias.name for alias in item.names)
                elif isinstance(item, ast.Call):
                    func = item.func
                    if isinstance(func, ast.Name):
                        mentioned.add(func.id)
                    elif isinstance(func, ast.Attribute):
                        mentioned.add(func.attr)
        return {node.id for node in self.nodes.values() if node.name in mentioned}

    # --- rendering --------------------------------------------------------

    def context_for(self, task: "Task") -> tuple[str, list[str]]:
        """Return (prompt text, files shown in full). Only those files may be edited."""
        if not self.nodes:
            return _full(task.sources), sorted(task.sources)
        scores = self.rank(self.seeds_for(task))
        file_score: dict[str, float] = defaultdict(float)
        for node_id, value in scores.items():
            file_score[self.nodes[node_id].file] += value
        ranked_files = sorted(file_score, key=lambda f: -file_score[f])
        top = file_score[ranked_files[0]]

        full: list[str] = []
        used = 0
        for path in ranked_files:
            size = len(task.sources[path])
            if full and (file_score[path] < FILE_SHARE * top or used + size > self.budget_chars):
                continue
            full.append(path)
            used += size

        floor = SNIPPET_SHARE * max(scores.values())
        snippets = [
            self.nodes[node_id] for node_id in sorted(scores, key=lambda n: -scores[n])
            if scores[node_id] > floor and self.nodes[node_id].file not in full and self.nodes[node_id].kind not in ("class", "module")
        ][:SNIPPETS]
        shown_ids = {n.id for n in self.nodes.values() if n.file in full} | {n.id for n in snippets}
        links = sorted(
            f"{_label(src)} {kind} {_label(dst)}"
            for src, targets in self.edges.items() for dst, kind in targets.items()
            if src in shown_ids and dst in self.nodes and self.nodes[src].file != self.nodes[dst].file
        )
        others = [n for n in self.nodes.values() if n.file not in full and n not in snippets and n.kind not in ("method", "module")]

        parts = [_full({p: task.sources[p] for p in full})]
        if snippets:
            parts.append("Related definitions from other files (read-only, for reference):\n" +
                         "\n\n".join(f"```python\n# from {n.file}\n{n.source}\n```" for n in snippets))
        if links:
            parts.append("How these pieces connect:\n" + "\n".join(f"- {line}" for line in links))
        if others:
            by_file: dict[str, list[str]] = defaultdict(list)
            for node in others:
                by_file[node.file].append(node.signature)
            parts.append("Other files (signatures only):\n" + "\n".join(
                f"{path}: " + "; ".join(sigs) for path, sigs in sorted(by_file.items())))
        return "\n\n".join(parts), full

    def describe(self) -> str:
        """Human-readable dump for the CLI."""
        lines = [f"{len(self.nodes)} definitions, {sum(len(t) for t in self.edges.values())} edges"]
        for src in sorted(self.edges):
            for dst, kind in sorted(self.edges[src].items()):
                lines.append(f"  {_label(src)} --{kind}--> {_label(dst)}")
        return "\n".join(lines)


def _label(node_id: str) -> str:
    path, name = node_id.split("::", 1)
    return f"{path.removesuffix('.py')}.{name}"


def _full(files: dict[str, str]) -> str:
    return "\n\n".join(f"```python\n# file: {path}\n{code.rstrip()}\n```" for path, code in files.items())
