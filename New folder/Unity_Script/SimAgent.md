```csharp

using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using TMPro;
using System.Text.RegularExpressions;
using System.Globalization;

public class SimAgent : MonoBehaviour
{
    public float moveSpeed = 1.8f;
    public float convSpacing = 0.3f;

    private Pathfinding pathfinder;
    private Grid navGrid;
    private Coroutine movementRoutine;
    private Vector3 currentDestination;
    private Animator animator;

    public GameObject dialoguePanel;
    public GameObject sprite;
    public TMP_Text emojiText;

    public bool IsInConversation { get; set; } = false;
    public string ConversationPartner { get; private set; }

    void Start()
    {
        pathfinder = FindObjectOfType<Pathfinding>();
        navGrid = pathfinder.GetComponent<Grid>();
        animator = sprite.GetComponent<Animator>();
        dialoguePanel.SetActive(false);

        // Mark starting position as occupied
        if (navGrid != null)
        {
            navGrid.SetOccupied(transform.position, true);
        }
    }

    public void MoveTo(string targetName)
    {
        if (Environment.Instance == null)
        {
            Debug.LogError("Environment script is missing from the scene!");
            return;
        }

        Vector3 destination = Environment.Instance.GetValidPosition(targetName, gameObject.name);
        destination.z = transform.position.z;

        currentDestination = destination;

        if (destination != Vector3.zero)
        {
            if (!TryStartPath(destination))
            {
                GameObject exactTarget = GameObject.Find(targetName);
                if (exactTarget)
                {
                    currentDestination = exactTarget.transform.position;
                    TryStartPath(currentDestination);
                }
            }
        }
    }

    public void showDialogue(string text, string display_time)
    {
        if (dialoguePanel != null && emojiText != null && text != null)
        {
            string processedText = Regex.Unescape(text);

            dialoguePanel.SetActive(true);
            emojiText.text = processedText;

            float duration = 4f;
            if (!string.IsNullOrWhiteSpace(display_time) && float.TryParse(display_time, NumberStyles.Float, CultureInfo.InvariantCulture, out float parsed))
            {
                duration = parsed;
            }

            StartCoroutine(HideDialogueCoroutine(duration));
        }
    }

    private bool TryStartPath(Vector3 destination)
    {
        if (pathfinder == null)
        {
            return false;
        }

        // Temporarily clear our own occupancy so pathfinding can start from our current node
        navGrid.SetOccupied(transform.position, false);

        List<Vector3> path = pathfinder.FindPath(transform.position, destination);

        if (path == null || path.Count == 0)
        {
            // Restore occupancy if pathfinding fails
            navGrid.SetOccupied(transform.position, true);
            return false;
        }

        if (movementRoutine != null)
        {
            StopCoroutine(movementRoutine);
        }
        movementRoutine = StartCoroutine(FollowPath(path));
        return true;
    }

    public void SetConversationState(bool isChatting, string partner = null)
    {
        IsInConversation = isChatting;
        ConversationPartner = isChatting ? partner : null;

        if (isChatting && !string.IsNullOrEmpty(ConversationPartner))
        {
            GameObject partnerObj = GameObject.Find(ConversationPartner);
            if (partnerObj != null)
            {
                SimAgent partnerAgent = partnerObj.GetComponent<SimAgent>();
                if (partnerAgent != null && partnerAgent.IsInConversation && partnerAgent.ConversationPartner == name)
                {
                    ArrangeConversationPair(this, partnerAgent);
                }
            }
        }

        if (!isChatting && dialoguePanel != null)
        {
            dialoguePanel.SetActive(false);
        }
    }

    public static void ArrangeConversationPair(SimAgent a, SimAgent b)
    {
        if (a == null || b == null)
        {
            return;
        }

        a.StopMotion();
        b.StopMotion();

        float dir = a.transform.position.x < b.transform.position.x ? -1f : 1f;
        Vector3 midpoint = (a.transform.position + b.transform.position) / 2f;

        Vector3 posA = midpoint;
        Vector3 posB = midpoint;

        posA.x += (a.convSpacing / 2f) * dir;
        posB.x -= (b.convSpacing / 2f) * dir;

        a.transform.position = posA;
        b.transform.position = posB;

        Vector2 forward = (b.transform.position - a.transform.position);
        forward.Normalize();
        a.FaceTowards(b.transform.position);
        b.FaceTowards(a.transform.position);
    }

    private void FaceTowards(Vector3 targetPos)
    {
        Vector3 dir = targetPos - transform.position;
        if (Mathf.Abs(dir.x) > 0.001f)
        {
            transform.localScale = new Vector3(dir.x > 0 ? 1 : -1, 1, 1);
        }
    }

    private IEnumerator HideDialogueCoroutine(float duration)
    {
        yield return new WaitForSeconds(duration);
        if (dialoguePanel != null) dialoguePanel.SetActive(false);
    }

    IEnumerator FollowPath(List<Vector3> path)
    {
        int targetIndex = 0;
        animator.SetBool("isWalking", true);
        Vector3 lastOccupiedPos = transform.position;

        while (targetIndex < path.Count)
        {
            Vector3 targetPos = new Vector3(path[targetIndex].x, path[targetIndex].y, transform.position.z);

            // Update occupancy on grid as we move
            if (Vector3.Distance(transform.position, lastOccupiedPos) > 0.2f)
            {
                navGrid.SetOccupied(lastOccupiedPos, false);
                navGrid.SetOccupied(transform.position, true);
                lastOccupiedPos = transform.position;
            }

            // 1. Move the agent towards the target position
            transform.position = Vector3.MoveTowards(transform.position, targetPos, moveSpeed * Time.deltaTime);

            // 2. Handle Sprite Flipping
            Vector3 dir = targetPos - transform.position;
            if (Mathf.Abs(dir.x) > 0.001f)
            {
                sprite.transform.localScale = new Vector3(dir.x > 0 ? 1 : -1, 1, 1);
            }

            // 3. Check if we reached the current waypoint to move to the next one
            if (Vector3.Distance(transform.position, targetPos) < 0.2f)
            {
                targetIndex++;
            }

            yield return null;
        }

        navGrid.SetOccupied(lastOccupiedPos, false);
        navGrid.SetOccupied(transform.position, true); // Stay occupied at destination

        animator.SetBool("isWalking", false);
        movementRoutine = null;
        UnityTcpListener.SendToAgent(gameObject.name, $"ARRIVED:{gameObject.name}");
    }

    public void Interact(string method, string targetName, string color = null)
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
        if (movementRoutine != null)
        {
            StopCoroutine(movementRoutine);
            movementRoutine = null;
        }
        animator.SetBool("isWalking", false);
    }
}

```
