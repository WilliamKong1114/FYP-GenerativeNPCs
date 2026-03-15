```csharp

using UnityEngine;
using System.Collections;
using System.Collections.Generic;

public class Pathfinding : MonoBehaviour
{
    Grid grid;

    void Awake()
    {
        grid = GetComponent<Grid>();
    }

    public List<Vector3> FindPath(Vector3 startPos, Vector3 targetPos)
    {
        startPos.z = 0;
        targetPos.z = 0;

        // Refresh a local region so short-lived blockers are reflected before planning.
        float refreshRadius = Mathf.Max(grid.nodeRadius * 4f, 1f);
        grid.RefreshWalkabilityAround(startPos, refreshRadius);
        grid.RefreshWalkabilityAround(targetPos, refreshRadius);

        Node startNode = grid.FindNearestWalkableNode(startPos);
        Node targetNode = grid.FindNearestWalkableNode(targetPos);

        if (startNode == null || targetNode == null)
        {
            return new List<Vector3>();
        }

        foreach (Node node in grid.GetAllNodes())
        {
            node.gCost = int.MaxValue;
            node.hCost = 0;
            node.parent = null;
        }

        startNode.gCost = 0;

        List<Vector3> waypoints = new List<Vector3>();
        if (startNode.walkable && targetNode.walkable)
        {
            List<Node> openSet = new List<Node>();
            HashSet<Node> closedSet = new HashSet<Node>();
            openSet.Add(startNode);

            while (openSet.Count > 0)
            {
                Node currentNode = openSet[0];
                for (int i = 1; i < openSet.Count; i++)
                {
                    if (openSet[i].fCost < currentNode.fCost || openSet[i].fCost == currentNode.fCost && openSet[i].hCost < currentNode.hCost)
                    {
                        currentNode = openSet[i];
                    }
                }

                openSet.Remove(currentNode);
                closedSet.Add(currentNode);

                if (currentNode == targetNode)
                {
                    List<Vector3> path = RetracePath(startNode, targetNode);

                    if (path.Count > 0)
                    {
                        path[path.Count - 1] = targetPos;
                    }
                    else if (startNode == targetNode && Vector3.Distance(startPos, targetPos) > 0.05f)
                    {
                        path.Add(targetPos);
                    }

                    return path;
                }

                foreach (Node neighbor in grid.GetNeighbors(currentNode))
                {
                    if (!neighbor.walkable || closedSet.Contains(neighbor))
                    {
                        continue;
                    }

                    int newMovementCostToNeighbor = currentNode.gCost + GetDistance(currentNode, neighbor);
                    if (newMovementCostToNeighbor < neighbor.gCost || !openSet.Contains(neighbor))
                    {
                        neighbor.gCost = newMovementCostToNeighbor;
                        neighbor.hCost = GetDistance(neighbor, targetNode);
                        neighbor.parent = currentNode;

                        if (!openSet.Contains(neighbor))
                            openSet.Add(neighbor);
                    }
                }
            }
        }
        return new List<Vector3>();
    }

    public List<Vector3> RecalculatePath(Vector3 currentPos, Vector3 targetPos)
    {
        return FindPath(currentPos, targetPos);
    }

    List<Vector3> RetracePath(Node startNode, Node endNode)
    {
        List<Node> path = new List<Node>();
        Node currentNode = endNode;

        while (currentNode != null && currentNode != startNode)
        {
            path.Add(currentNode);
            currentNode = currentNode.parent;
        }

        if (currentNode == null)
        {
            return new List<Vector3>();
        }

        path.Reverse();

        List<Vector3> waypoints = new List<Vector3>();
        foreach (Node n in path) waypoints.Add(n.worldPosition);
        return waypoints;
    }

    int GetDistance(Node nodeA, Node nodeB)
    {
        int dstX = Mathf.Abs(nodeA.gridX - nodeB.gridX);
        int dstY = Mathf.Abs(nodeA.gridY - nodeB.gridY);

        if (dstX > dstY)
            return 14 * dstY + 10 * (dstX - dstY);
        return 14 * dstX + 10 * (dstY - dstX);
    }
}

```
