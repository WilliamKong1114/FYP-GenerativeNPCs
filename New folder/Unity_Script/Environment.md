```csharp

using System;
using UnityEngine;
using System.Collections.Generic;

public class Environment : MonoBehaviour
{
    public static Environment Instance;

    public float radius = 2.5f;
    public bool rangePreview = true;
    public Color rangeColor = new Color(0.2f, 0.8f, 1f, 0.9f);

    public Grid pathfindingGrid;
    private Dictionary<string, Vector3> interactionPoints = new Dictionary<string, Vector3>();
    private string previewTargetName;

    void Awake()
    {
        if (Instance == null)
        {
            Instance = this;
        }
        else if (Instance != this)
        {
            Destroy(gameObject);
            return;
        }

        if (pathfindingGrid == null) pathfindingGrid = FindObjectOfType<Grid>();
        objectList = new List<GameObject>(FindObjectsOfType<GameObject>());
        GetInteractionPoint();
    }

    List<GameObject> objectList = new List<GameObject>();

    private List<GameObject> GetInteractionPoint()
    {
        objectList = new List<GameObject>(FindObjectsOfType<GameObject>());
        interactionPoints.Clear();

        List<GameObject> pointlist = new List<GameObject>();
        foreach (GameObject o in objectList)
        {
            if (o == null)
            {
                continue;
            }

            bool hasIPTag = string.Equals(o.tag, "IP", StringComparison.Ordinal);
            bool hasIPName = string.Equals(o.name, "IP", StringComparison.Ordinal);
            if (hasIPTag || hasIPName)
            {
                pointlist.Add(o);

                Transform parent = o.transform.parent;
                if (parent != null && !interactionPoints.ContainsKey(parent.name))
                {
                    interactionPoints[parent.name] = o.transform.position;
                }
            }
        }
        return pointlist;
    }

    public Vector3 GetValidPosition(string targetName, string agentId = null)
    {
        previewTargetName = targetName;

        GameObject targetObj = GameObject.Find(targetName);
        if (targetObj == null)
        {
            Debug.LogWarning($"Target '{targetName}' not found.");
            return Vector3.zero;
        }

        List<GameObject> pointlist = GetInteractionPoint();
        Vector3 center = targetObj.transform.position;
        bool foundIP = false;

        foreach (GameObject o in pointlist)
        {
            if (o == null)
            {
                continue;
            }

            Transform parent = o.transform.parent;
            if (parent != null && parent == targetObj.transform)
            {
                center = o.transform.position;
                foundIP = true;
                break;
            }
        }

        if (!foundIP)
        {
            Debug.LogWarning($"Target '{targetName}' has no child IP. Using target pivot fallback.");
            return targetObj.transform.position;
        }

        const int sampleAttempts = 10;
        for (int i = 0; i < sampleAttempts; i++)
        {
            Vector2 offset = UnityEngine.Random.insideUnitCircle * radius;
            Vector3 candidatePos = center + new Vector3(offset.x, offset.y, 0f);
            if (IsWalkable(candidatePos))
            {
                return candidatePos;
            }
        }

        return targetObj.transform.position;


    }

    private bool IsWalkable(Vector3 worldPos)
    {
        if (pathfindingGrid == null) return true; // Safety
        Node node = pathfindingGrid.NodeFromWorldPoint(worldPos);
        return node != null && node.walkable;
    }

void OnDrawGizmos()
{
    if (!rangePreview) return;

    GameObject[] allObjects = GameObject.FindObjectsOfType<GameObject>();
    Gizmos.color = rangeColor;

    foreach (GameObject o in allObjects)
    {
        if (o == null) continue;

        bool isIP = string.Equals(o.name, "IP", StringComparison.Ordinal) ||
                    string.Equals(o.tag, "IP", StringComparison.Ordinal);

        if (isIP)
        {
            Vector3 pos = o.transform.position;
            pos.z = 0f; // Ensure it's on the 2D plane
            Gizmos.DrawWireSphere(pos, radius);
        }
    }
}

void OnDrawGizmosSelected()
{
    OnDrawGizmos();
}

```
