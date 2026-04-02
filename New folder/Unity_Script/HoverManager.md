```csharp

using UnityEngine;
using System.Collections.Generic;
using Cinemachine;

public class HoverColorController2D : MonoBehaviour
{
    private string targetTag = "Agent";
    private Color hoverColor = new Color32(169, 169, 169, 255);

    private Dictionary<Transform, Color> originalColors = new Dictionary<Transform, Color>();
    private SpriteRenderer lastHoverRenderer;
    private GameObject hoverObject;
    private Color originalColor = Color.white;

    public CinemachineVirtualCamera virtualCamera;
    public Transform player;

    public GameObject InteractIndicator;

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
        DetectClick();
    }

    void DetectHover()
    {
        Vector3 mouseWorld = Camera.main.ScreenToWorldPoint(Input.mousePosition);
        Vector2 mousePos = new Vector2(mouseWorld.x, mouseWorld.y);
        RaycastHit2D hit = Physics2D.Raycast(mousePos, Vector2.zero);

        if (hit.collider != null && hit.collider.CompareTag(targetTag))
        {
            hoverObject = hit.collider.transform.gameObject;
            SpriteRenderer sr = hoverObject.GetComponent<SpriteRenderer>();

            if (lastHoverRenderer != null && lastHoverRenderer != sr)
                lastHoverRenderer.color = originalColor;

            lastHoverRenderer = sr;
            sr.color = hoverColor;
        }
        else
        {
            hoverObject = null;
            if (lastHoverRenderer != null)
            {
                lastHoverRenderer.color = originalColor;
                lastHoverRenderer = null;
            }
        }
    }

    bool interactMode = false;
    GameObject prefClickObject = null;

    void DetectClick()
    {
        if (Input.GetKeyDown(KeyCode.I))
        {
            interactMode = !interactMode;
            InteractIndicator.SetActive(interactMode);
            prefClickObject = null;
            return;
        }

        if (interactMode)
        {
            //InteractIndicator.SetActive(false);
            if (Input.GetMouseButtonDown(0) && hoverObject != null)
            {
                bool isInteractionActive = InteractionManager.Instance != null && InteractionManager.Instance.InteractionPanel.activeSelf;
                if (prefClickObject != null && hoverObject == prefClickObject && isInteractionActive)
                {
                    Debug.Log("You are clicking the same agent.");
                    return;
                }
                else
                {
                    checkInteraction(hoverObject);
                    prefClickObject = hoverObject;
                    return;
                }
            }
        }

        if (Input.GetMouseButtonDown(0) && hoverObject != null)
        {
            virtualCamera.Follow = hoverObject.transform;
        }

        if (Input.GetMouseButtonDown(1))
        {
            virtualCamera.Follow = player;
            hoverObject = null;
        }
    }

    void checkInteraction(GameObject agent)
    {
        if (agent == null)
            return;

        if (InteractionManager.Instance != null)
        {
            InteractionManager.Instance.StartInteraction(agent.transform.parent.name);
        }
    }
}

```
