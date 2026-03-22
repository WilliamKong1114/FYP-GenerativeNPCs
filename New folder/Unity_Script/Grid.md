```csharp
using UnityEngine;
using System.Collections.Generic;

public class Grid : MonoBehaviour
{
    public LayerMask unwalkableMask;
    public Vector2 gridWorldSize;
    public float nodeRadius;
    public bool visualizeGrid = true;
    Node[,] grid;

    float nodeDiameter;
    int gridSizeX, gridSizeY;

    void Awake()
    {
        nodeDiameter = nodeRadius * 2;
        gridSizeX = Mathf.RoundToInt(gridWorldSize.x / nodeDiameter);
        gridSizeY = Mathf.RoundToInt(gridWorldSize.y / nodeDiameter);
        CreateGrid();
    }

    private bool IsWalkableAt(Vector3 worldPoint)
    {
        return !(Physics2D.OverlapCircle(worldPoint, nodeRadius, unwalkableMask));
    }

    public int MaxSize
    {
        get { return gridSizeX * gridSizeY; }
    }

    void CreateGrid()
    {
        grid = new Node[gridSizeX, gridSizeY];
        // In 2D, bottom left is: pos - Right*width/2 - Up*height/2
        Vector3 worldBottomLeft = transform.position - Vector3.right * gridWorldSize.x / 2 - Vector3.up * gridWorldSize.y / 2;

        for (int x = 0; x < gridSizeX; x++)
        {
            for (int y = 0; y < gridSizeY; y++)
            {
                Vector3 worldPoint = worldBottomLeft + Vector3.right * (x * nodeDiameter + nodeRadius) + Vector3.up * (y * nodeDiameter + nodeRadius);

                bool walkable = IsWalkableAt(worldPoint);
                grid[x, y] = new Node(walkable, worldPoint, x, y);
            }
        }
    }

    public List<Node> GetNeighbors(Node node)
    {
        List<Node> neighbors = new List<Node>();

        for (int x = -1; x <= 1; x++)
        {
            for (int y = -1; y <= 1; y++)
            {
                if (x == 0 && y == 0) continue;

                int checkX = node.gridX + x;
                int checkY = node.gridY + y;

                if (checkX >= 0 && checkX < gridSizeX && checkY >= 0 && checkY < gridSizeY)
                {
                    // Prevent corner cutting: diagonal move is valid only if both side-adjacent nodes are walkable.
                    if (x != 0 && y != 0)
                    {
                        Node sideA = grid[node.gridX + x, node.gridY];
                        Node sideB = grid[node.gridX, node.gridY + y];
                        if (!sideA.walkable || !sideB.walkable)
                        {
                            continue;
                        }
                    }

                    neighbors.Add(grid[checkX, checkY]);
                }
            }
        }
        return neighbors;
    }

    public IEnumerable<Node> GetAllNodes()
    {
        foreach (Node n in grid)
        {
            yield return n;
        }
    }

    public bool IsInsideGrid(int x, int y)
    {
        return x >= 0 && x < gridSizeX && y >= 0 && y < gridSizeY;
    }

    public bool IsWalkableWorldPoint(Vector3 worldPosition)
    {
        Node node = NodeFromWorldPoint(worldPosition);
        return node != null && node.walkable && !node.occupied;
    }

    public void SetOccupied(Vector3 worldPosition, bool occupied)
    {
        Node node = NodeFromWorldPoint(worldPosition);
        if (node != null)
        {
            node.occupied = occupied;
        }
    }

    public Node FindNearestWalkableNode(Vector3 worldPosition, int maxSearchRadius = 6)
    {
        Node origin = NodeFromWorldPoint(worldPosition);
        if (origin == null)
        {
            return null;
        }

        if (origin.walkable && !origin.occupied)
        {
            return origin;
        }

        for (int radius = 1; radius <= maxSearchRadius; radius++)
        {
            int minX = origin.gridX - radius;
            int maxX = origin.gridX + radius;
            int minY = origin.gridY - radius;
            int maxY = origin.gridY + radius;

            for (int x = minX; x <= maxX; x++)
            {
                for (int y = minY; y <= maxY; y++)
                {
                    bool onRing = x == minX || x == maxX || y == minY || y == maxY;
                    if (!onRing || !IsInsideGrid(x, y))
                    {
                        continue;
                    }

                    Node candidate = grid[x, y];
                    if (candidate.walkable && !candidate.occupied)
                    {
                        return candidate;
                    }
                }
            }
        }

        return null;
    }

    public void RefreshWalkabilityAround(Vector3 center, float radius)
    {
        Vector3 bottomLeft = transform.position - Vector3.right * gridWorldSize.x / 2 - Vector3.up * gridWorldSize.y / 2;
        Vector3 topRight = transform.position + Vector3.right * gridWorldSize.x / 2 + Vector3.up * gridWorldSize.y / 2;

        float minX = Mathf.Max(center.x - radius, bottomLeft.x);
        float maxX = Mathf.Min(center.x + radius, topRight.x);
        float minY = Mathf.Max(center.y - radius, bottomLeft.y);
        float maxY = Mathf.Min(center.y + radius, topRight.y);

        Node minNode = NodeFromWorldPoint(new Vector3(minX, minY, 0f));
        Node maxNode = NodeFromWorldPoint(new Vector3(maxX, maxY, 0f));

        int startX = Mathf.Min(minNode.gridX, maxNode.gridX);
        int endX = Mathf.Max(minNode.gridX, maxNode.gridX);
        int startY = Mathf.Min(minNode.gridY, maxNode.gridY);
        int endY = Mathf.Max(minNode.gridY, maxNode.gridY);

        for (int x = startX; x <= endX; x++)
        {
            for (int y = startY; y <= endY; y++)
            {
                if (!IsInsideGrid(x, y))
                {
                    continue;
                }

                Node node = grid[x, y];
                node.walkable = IsWalkableAt(node.worldPosition);
            }
        }
    }

    public Node NodeFromWorldPoint(Vector3 worldPosition)
    {
        Vector3 worldBottomLeft = transform.position - Vector3.right * gridWorldSize.x / 2 - Vector3.up * gridWorldSize.y / 2;

        float percentX = (worldPosition.x - worldBottomLeft.x) / gridWorldSize.x;
        float percentY = (worldPosition.y - worldBottomLeft.y) / gridWorldSize.y;
        percentX = Mathf.Clamp01(percentX);
        percentY = Mathf.Clamp01(percentY);

        int x = Mathf.RoundToInt((gridSizeX - 1) * percentX);
        int y = Mathf.RoundToInt((gridSizeY - 1) * percentY);
        return grid[x, y];
    }

void OnDrawGizmos()
{
    Gizmos.DrawWireCube(transform.position, new Vector3(gridWorldSize.x, gridWorldSize.y, 1));

    if (grid == null)
    {
        // Only calculate if visualized explicitly check on
        if (visualizeGrid)  // <-- Updated from visuliseGrid
        {
            float d = nodeRadius * 2;
            int xCount = Mathf.RoundToInt(gridWorldSize.x / d);
            int yCount = Mathf.RoundToInt(gridWorldSize.y / d);
            // Safety check to avoid zero division or massive loop
            if (d <= 0.01f) return;

            Vector3 bottomLeft = transform.position - Vector3.right * gridWorldSize.x / 2 - Vector3.up * gridWorldSize.y / 2;

            for (int x = 0; x < xCount; x++)
            {
                for (int y = 0; y < yCount; y++)
                {
                    Vector3 worldPoint = bottomLeft + Vector3.right * (x * d + nodeRadius) + Vector3.up * (y * d + nodeRadius);
                    // Can skip physics for quicker viz if needed, or keep it
                    bool walkable = IsWalkableAt(worldPoint);  // <-- Updated to use new method
                    Gizmos.color = walkable ? Color.white : Color.red;
                    Gizmos.DrawCube(worldPoint, Vector3.one * (d - 0.1f));
                }
            }
        }
    }
    else
    {
        // Grid is not null (Play Mode)
        if (visualizeGrid)  // <-- Added for consistency
        {
            foreach (Node n in grid)
            {
                if (n == null) continue; // Safety check
                Gizmos.color = n.walkable ? Color.white : Color.red;
                Gizmos.DrawCube(n.worldPosition, Vector3.one * (nodeDiameter - .1f));
            }
        }
    }
}

```
