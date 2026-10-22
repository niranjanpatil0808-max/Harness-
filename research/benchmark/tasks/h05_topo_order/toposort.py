def topo_order(graph):
    order, seen = [], set()

    def visit(node):
        if node in seen:
            return
        seen.add(node)
        for dep in graph.get(node, []):
            visit(dep)
        order.append(node)

    for node in graph:
        visit(node)
    return order
