import heapq
from collections import defaultdict


def topo_order(graph):
    deps = {node: set(ds) for node, ds in graph.items()}
    for ds in list(deps.values()):
        for dep in ds:
            deps.setdefault(dep, set())
    users = defaultdict(list)
    for node, ds in deps.items():
        for dep in ds:
            users[dep].append(node)
    waiting = {node: len(ds) for node, ds in deps.items()}
    ready = [node for node, count in waiting.items() if count == 0]
    heapq.heapify(ready)
    order = []
    while ready:
        node = heapq.heappop(ready)
        order.append(node)
        for user in users[node]:
            waiting[user] -= 1
            if waiting[user] == 0:
                heapq.heappush(ready, user)
    if len(order) != len(deps):
        raise ValueError("dependency cycle")
    return order
