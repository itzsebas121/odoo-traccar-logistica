"""Optimizador de rutas con OR-Tools (un deposito, capacidad)."""
from ortools.constraint_solver import pywrapcp, routing_enums_pb2

OPTIMIZATION_VERSION = "ortools-cvrp-1"
MAX_TIME_LIMIT_S = 30


def unassigned_reason(demand, residuals):
    """Motivo de una parada sin asignar. `residuals`: capacidad libre de cada vehiculo en la
    solucion devuelta. sin_capacidad si la parada no cabe en ninguno; sin_ruta si cabria."""
    return "sin_ruta" if any(demand <= r for r in residuals) else "sin_capacidad"


def optimize(dist, dur, demands, capacities, time_limit_s):
    """dist/dur: matrices (nodo 0 = deposito). demands[i] para paradas 1..n.
    time_limit_s: segundos (puede ser fraccionario) para la busqueda.
    Devuelve (rutas, no_asignadas) por indices.
    rutas: [(vehiculo_idx, [nodos], distancia_m, duracion_s, carga)]
    no_asignadas: [(nodo, motivo)]"""
    n = len(dist)
    nv = len(capacities)
    manager = pywrapcp.RoutingIndexManager(n, nv, 0)
    routing = pywrapcp.RoutingModel(manager)

    def dist_cb(i, j):
        return dist[manager.IndexToNode(i)][manager.IndexToNode(j)]

    cb = routing.RegisterTransitCallback(dist_cb)
    routing.SetArcCostEvaluatorOfAllVehicles(cb)

    def dem_cb(i):
        node = manager.IndexToNode(i)
        return 0 if node == 0 else demands[node]

    dcb = routing.RegisterUnaryTransitCallback(dem_cb)
    routing.AddDimensionWithVehicleCapacity(dcb, 0, list(capacities), True, "Capacity")

    max_d = max((max(r) for r in dist), default=0)
    penalty = (max_d + 1) * (n + 1) * 10
    for node in range(1, n):
        routing.AddDisjunction([manager.NodeToIndex(node)], penalty)

    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    limit_s = max(1.0, min(float(time_limit_s), MAX_TIME_LIMIT_S))
    params.time_limit.FromMilliseconds(int(limit_s * 1000))
    solution = routing.SolveWithParameters(params)

    routes, assigned = [], set()
    if solution:
        for v in range(nv):
            idx = routing.Start(v)
            nodes, d, t, load = [], 0, 0, 0
            while not routing.IsEnd(idx):
                nxt = solution.Value(routing.NextVar(idx))
                a, b = manager.IndexToNode(idx), manager.IndexToNode(nxt)
                d += dist[a][b]
                t += dur[a][b]
                if a != 0:
                    nodes.append(a)
                    load += demands[a]
                idx = nxt
            if nodes:
                routes.append((v, nodes, d, t, load))
                assigned.update(nodes)

    loads = {v: load for v, _, _, _, load in routes}
    residuals = [cap - loads.get(v, 0) for v, cap in enumerate(capacities)]
    unassigned = [(node, unassigned_reason(demands[node], residuals))
                  for node in range(1, n) if node not in assigned]
    return routes, unassigned
