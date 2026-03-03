```csharp

using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using TMPro;
using System.Text.RegularExpressions;

public class SimAgent : MonoBehaviour
{
    public float moveSpeed = 2.0f;
    private Pathfinding pathfinder;
    public GameObject dialoguePanel;
    public TMP_Text emojiText;

    public bool IsInConversation { get; set; } = false;

    void Start()
    {
        pathfinder = FindObjectOfType<Pathfinding>();
        if (pathfinder == null)
        {
            Debug.LogError("No Pathfinding script found in scene!");
        }
        if (dialoguePanel != null)
        {
            dialoguePanel.SetActive(false);
        };
    }

    public void MoveTo(string targetName)
    {
        if (Environment.Instance == null)
        {
            Debug.LogError("Environment script is missing from the scene!");
            return;
        }

        Vector3 destination = Environment.Instance.GetValidPosition(targetName);

        if (destination != Vector3.zero)
        {
            List<Vector3> path = pathfinder.FindPath(transform.position, destination);

            if (path != null && path.Count > 0)
            {
                StopAllCoroutines();
                StartCoroutine(FollowPath(path));
            }
            else
            {
                // Fallback: If random point is unwalkable, try exact center
                GameObject exactTarget = GameObject.Find(targetName);
                if (exactTarget)
                {
                    path = pathfinder.FindPath(transform.position, exactTarget.transform.position);
                    if (path != null && path.Count > 0)
                    {
                        StopAllCoroutines();
                        StartCoroutine(FollowPath(path));
                    }
                }
            }
        }
    }

    public void showDialogue(string text)
    {
        if (dialoguePanel != null && emojiText != null && text != null)
        {
            string processedText = Regex.Unescape(text);
            dialoguePanel.SetActive(true);
            emojiText.text = processedText;
            StartCoroutine(HideDialogueCoroutine());
        }
    }

    private IEnumerator HideDialogueCoroutine()
    {
        yield return new WaitForSeconds(4.0f);
        if (dialoguePanel != null) dialoguePanel.SetActive(false);
    }

    IEnumerator FollowPath(List<Vector3> path)
    {
        int targetIndex = 0;
        while (targetIndex < path.Count)
        {
            Vector3 targetPos = new Vector3(path[targetIndex].x, path[targetIndex].y, transform.position.z);

            transform.position = Vector3.MoveTowards(transform.position, targetPos, moveSpeed * Time.deltaTime);
            Vector3 dir = targetPos - transform.position;

            if (dir.sqrMagnitude > 0.001f)
            {
                float angle = Mathf.Atan2(dir.y, dir.x) * Mathf.Rad2Deg;
                transform.rotation = Quaternion.AngleAxis(angle, Vector3.forward);
            }

            if (Vector2.Distance(transform.position, targetPos) < 0.1f)
            {
                targetIndex++;
            }
            yield return null;
        }

        UnityTcpListener.SendToAgent(gameObject.name, $"ARRIVED:{gameObject.name}");
    }

    public void Interact(string method, string targetName, string color=null)
    {
        if (string.IsNullOrEmpty(targetName))
        {
            Debug.LogWarning($"[SimAgent {name}] Interaction command missing target.");
            return;
        }

        Debug.Log($"[{name}] Interacting with {targetName} via method: {method}");

        GameObject targetObj = GameObject.Find(targetName);
        if (targetObj != null)
        {
            var interactable = targetObj.GetComponent<InteractableObject>();
            if (interactable != null)
            {
                interactable.Interact(method, color);
            }
            else
            {
                Debug.LogWarning($"Object {targetName} has no InteractableObject script. Trying SendMessage.");
                targetObj.SendMessage(method, SendMessageOptions.DontRequireReceiver);
            }
        }
        else
        {
            Debug.LogError($"Target object not found: {targetName}");
        }
    }

    public void StopMotion()
    {
        StopAllCoroutines();
    }
}

```
