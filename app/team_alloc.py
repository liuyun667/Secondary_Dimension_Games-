"""队伍全局资源分配（Hungarian + 贪心回溯）——对应 §3.7.2。

纯 Python 实现，零依赖。真实落地时收益由 RF 评分替代示例评分函数。
"""
from __future__ import annotations


def hungarian_maximize(profit: list[list[float]]) -> list[int]:
    """最大化总收益的分配。返回 assignment[i] = 装备下标；-1 = 未分配。"""
    n = len(profit)
    m = len(profit[0]) if n else 0
    if n == 0 or m == 0:
        return [-1] * n

    size = max(n, m)
    cost = [[0.0] * size for _ in range(size)]
    for i in range(n):
        for j in range(m):
            cost[i][j] = -profit[i][j]

    u = [0.0] * (size + 1)
    v = [0.0] * (size + 1)
    p = [0] * (size + 1)
    way = [0] * (size + 1)

    for i in range(1, size + 1):
        p[0] = i
        j0 = 0
        minv = [float("inf")] * (size + 1)
        used = [False] * (size + 1)
        while True:
            used[j0] = True
            i0 = p[j0]
            delta = float("inf")
            j1 = 0
            for j in range(1, size + 1):
                if not used[j]:
                    cur = cost[i0 - 1][j - 1] - u[i0] - v[j]
                    if cur < minv[j]:
                        minv[j] = cur
                        way[j] = j0
                    if minv[j] < delta:
                        delta = minv[j]
                        j1 = j
            for j in range(size + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while j0:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1

    assignment = [-1] * n
    for j in range(1, size + 1):
        if p[j] and p[j] <= n and j <= m:
            assignment[p[j] - 1] = j - 1
    return assignment


def greedy_with_backtrack(profit: list[list[float]]) -> list[int]:
    """贪心 + 冲突回溯（队伍小时的轻量替代）。"""
    n = len(profit)
    m = len(profit[0]) if n else 0
    assignment = [-1] * n
    used = [False] * m

    order = sorted(range(n), key=lambda i: max(profit[i]) if profit[i] else 0.0,
                   reverse=True)
    for i in order:
        cand = sorted(range(m), key=lambda j: profit[i][j], reverse=True)
        placed = False
        for j in cand:
            if not used[j]:
                assignment[i] = j
                used[j] = True
                placed = True
                break
        if placed:
            continue
        for j in cand:
            owner = next((k for k in range(n) if assignment[k] == j), None)
            if owner is None:
                continue
            alt = next(
                (j2 for j2 in sorted(range(m), key=lambda jj: profit[owner][jj],
                                     reverse=True)
                 if not used[j2] and j2 != j), None)
            if alt is not None:
                assignment[owner] = alt
                used[alt] = True
                assignment[i] = j
                placed = True
                break
        if not placed:
            assignment[i] = -1
    return assignment
