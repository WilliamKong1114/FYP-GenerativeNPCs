```csharp

using UnityEngine;
using System.Collections.Generic;
using Cinemachine;

public class HoverColorController2D : MonoBehaviour
{
    private string targetTag = "Agent";
    private Color hoverColor = new Color32(169, 169, 169, 255);

    private Dictionary<Transform, Color> originalColors = new Dictionary<Transform, Color>();
    private Transform currentHover = null;

    public CinemachineVirtualCamera virtualCamera;
    public Transform player;

    void Start()
    {
        GameObject[] targets = GameObject.FindGameObjectsWithTag(targetTag);

        foreach (GameObject obj in targets)
        {
            SpriteRenderer sr = obj.GetComponent<SpriteRenderer>();
            if (sr != null)
            {
                originalColors[obj.transform] = sr.color;
            }
        }
    }

    void Update()
    {
        DetectHover();
        ApplyColorChange();
        DetectClick();
    }

    void DetectHover()
    {
        Vector3 mouseWorld = Camera.main.ScreenToWorldPoint(Input.mousePosition);
        Vector2 mousePos = new Vector2(mouseWorld.x, mouseWorld.y);

        RaycastHit2D hit = Physics2D.Raycast(mousePos, Vector2.zero);

        if (hit.collider != null && hit.collider.CompareTag(targetTag))
        {
            currentHover = hit.collider.transform;
        }
        else
        {
            currentHover = null;
        }
    }

    void DetectClick()
    {
        if (virtualCamera == null)
            return;

        if (Input.GetMouseButtonDown(0) && currentHover != null)
        {
            virtualCamera.Follow = currentHover;
        }

        if (Input.GetMouseButtonDown(1))
        {
            virtualCamera.Follow = player;
        }
    }

    void ApplyColorChange()
    {
        foreach (var pair in originalColors)
        {
            Transform obj = pair.Key;
            SpriteRenderer sr = obj.GetComponentInChildren<SpriteRenderer>();

            if (sr == null)
                continue;

            if (obj == currentHover)
            {
                sr.color = hoverColor;
            }
            else
            {
                sr.color = pair.Value;
            }
        }
    }
}

```
