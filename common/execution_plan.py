from __future__ import annotations
from pydantic import BaseModel, model_validator
from typing import Dict, List, Optional, Any


class NodeMeta(BaseModel):
    depends_on: List[str] = []
    condition: Optional[str] = None   # e.g. "weather_agent.temperature > 35"
    input_from: List[str] = []        # which upstream agent outputs to forward


class ExecutionPlan(BaseModel):
    nodes: Dict[str, NodeMeta]        # agent_name → metadata
    entry_points: List[str]           # nodes with no dependencies
    metadata: Dict[str, Any] = {}    # runtime bookkeeping: visited, depth, max_hops

    @model_validator(mode="after")
    def check_no_cycles(self) -> "ExecutionPlan":
        if not validate_no_cycles({k: v.model_dump() for k, v in self.nodes.items()}):
            raise ValueError("ExecutionPlan contains a cycle — dependencies must be acyclic.")
        return self

    @model_validator(mode="after")
    def check_entry_points_exist(self) -> "ExecutionPlan":
        for ep in self.entry_points:
            if ep not in self.nodes:
                raise ValueError(f"Entry point '{ep}' is not declared in nodes.")
        return self


def validate_no_cycles(nodes: dict) -> bool:
    """
    DFS-based cycle detection on the dependency graph.
    nodes: dict of agent_name → {depends_on: [...], ...}
    Returns True if NO cycle exists, False if a cycle is found.
    """
    visited: set[str] = set()
    rec_stack: set[str] = set()

    def dfs(node: str) -> bool:
        visited.add(node)
        rec_stack.add(node)
        for dep in nodes.get(node, {}).get("depends_on", []):
            if dep not in visited:
                if dfs(dep):
                    return True
            elif dep in rec_stack:
                return True
        rec_stack.discard(node)
        return False

    return not any(dfs(n) for n in nodes if n not in visited)