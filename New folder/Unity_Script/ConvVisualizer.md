```csharp

using System.Collections.Generic;
using TMPro;
using UnityEngine;
using UnityEngine.UI;

public class ConvVisualizer : MonoBehaviour
{
    public float TriggerDistance = 3.0f;
    public float BoxAutoDismissSeconds = 5.0f;
    public GameObject boxPrefab;
    public Canvas canvas;

    private Dictionary<string, GameObject> activeBoxes = new Dictionary<string, GameObject>();
    private readonly Dictionary<string, float> boxEntryTimes = new Dictionary<string, float>();
    private readonly Dictionary<string, string[]> pairAgents = new Dictionary<string, string[]>();
    private readonly HashSet<string> dismissedPairs = new HashSet<string>();
    private SimAgent[] agents;

    private float timer = 0f;
    private int dotCount = 0;

    void Start()
    {
        agents = FindObjectsOfType<SimAgent>();

        if (boxPrefab == null)
        {
            Debug.LogWarning("[ConvVisualizer] boxPrefab is not assigned.");
        }
        if (canvas == null)
        {
            Debug.LogWarning("[ConvVisualizer] canvas is not assigned.");
        }
    }

    void Update()
    {
        if (agents == null || agents.Length == 0) return;

        timer += Time.deltaTime;
        if (timer > 0.5f)
        {
            dotCount = (dotCount + 1) % 4;
            timer = 0f;
        }

        HashSet<string> currentPairs = new HashSet<string>();
        checkPair(currentPairs);
        removePair(currentPairs);
    }

    void checkPair(HashSet<string> currentPairs)
    {
        for (int i = 0; i < agents.Length; i++)
        {
            SimAgent a1 = agents[i];
            if (!a1.IsInConversation || string.IsNullOrEmpty(a1.ConversationPartner))
            {
                continue;
            }

            GameObject partnerObj = GameObject.Find(a1.ConversationPartner);
            if (partnerObj == null)
            {
                continue;
            }

            SimAgent a2 = partnerObj.GetComponent<SimAgent>();
            if (a2 == null)
            {
                continue;
            }

            if (!a2.IsInConversation || a2.ConversationPartner != a1.name)
            {
                continue;
            }

            string pairId = GetPairId(a1, a2);
            if (currentPairs.Contains(pairId))
            {
                continue;
            }

            float dist = Vector3.Distance(a1.transform.position, a2.transform.position);
            if (dist < TriggerDistance && a1.IsInConversation && a2.IsInConversation)
            {
                a1.dialoguePanel.SetActive(false);
                a2.dialoguePanel.SetActive(false);

                currentPairs.Add(pairId);

                // If user ignored this pair once, keep it hidden until pair state resets.
                if (dismissedPairs.Contains(pairId))
                {
                    continue;
                }

                UpdateBox(pairId, a1, a2);
            }
        }
    }

    void removePair(HashSet<string> currentPairs)
    {
        List<string> toRemove = new List<string>();
        float now = Time.time;

        foreach (var pairId in activeBoxes.Keys)
        {
            float startTime;
            if (boxEntryTimes.TryGetValue(pairId, out startTime))
            {
                if (startTime < 0)
                {
                    // Check if this pair's data arrived
                    string[] agentsForPair;
                    if (DialogueManager.Instance != null
                        && pairAgents.TryGetValue(pairId, out agentsForPair)
                        && agentsForPair.Length == 2
                        && DialogueManager.Instance.HasConversationDataForPair(agentsForPair[0], agentsForPair[1]))
                    {
                        boxEntryTimes[pairId] = now;
                    }
                    UpdateLoadingBar(pairId, false, 0f);
                    continue;
                }

                float elapsed = now - startTime;
                float remainingRatio = Mathf.Clamp01(1f - (elapsed / BoxAutoDismissSeconds));
                UpdateLoadingBar(pairId, true, remainingRatio);

                if (elapsed >= BoxAutoDismissSeconds)
                {
                    dismissedPairs.Add(pairId);
                    toRemove.Add(pairId);
                    Debug.Log($"[ConvVisualizer] Auto-dismissed unclicked indicator for {pairId} after {BoxAutoDismissSeconds:0.0}s of data arrival");
                }
            }
        }

        foreach (var id in toRemove)
        {
            if (activeBoxes[id] != null) Destroy(activeBoxes[id]);
            activeBoxes.Remove(id);
            boxEntryTimes.Remove(id);
            pairAgents.Remove(id);
        }

        // Allow indicator to appear again only when pair exits active conversation state.
        dismissedPairs.RemoveWhere(id => !currentPairs.Contains(id));
    }

    string GetPairId(SimAgent a1, SimAgent a2)
    {
        return (string.Compare(a1.name, a2.name) < 0)
            ? $"{a1.name}_{a2.name}"
            : $"{a2.name}_{a1.name}";
    }

    void UpdateBox(string pairId, SimAgent a1, SimAgent a2)
    {
        GameObject box;
        if (!activeBoxes.TryGetValue(pairId, out box) || box == null)
        {
            if (boxPrefab != null && canvas != null)
            {
                box = Instantiate(boxPrefab, canvas.transform);
                activeBoxes[pairId] = box;
                boxEntryTimes[pairId] = -1f; // Marker to wait for data arrival
                pairAgents[pairId] = new[] { a1.name, a2.name };

                Button btn = box.GetComponent<Button>();
                if (btn == null)
                {
                    btn = box.GetComponentInChildren<Button>(true);
                }
                if (btn != null)
                {
                    btn.onClick.RemoveAllListeners();
                    string agent1 = a1.name;
                    string agent2 = a2.name;
                    btn.onClick.AddListener(() => OnConvButtonClicked(pairId, agent1, agent2));
                }
                else
                {
                    Debug.LogWarning($"[ConvVisualizer] No Button found on indicator prefab for pair {pairId}.");
                }
            }
        }

        if (box == null) return;
        box.transform.position = (a1.transform.position + a2.transform.position) / 2f;
        updateButtonText(box);
    }

    void updateButtonText(GameObject box)
    {
        string textStr = "";
        if (dotCount == 1) textStr = ".";
        else if (dotCount == 2) textStr = "..";
        else if (dotCount == 3) textStr = "...";

        TMP_Text tmpText = box.GetComponentInChildren<TMP_Text>();
        if (tmpText != null)
        {
            tmpText.text = textStr;
        }
    }

    void UpdateLoadingBar(string pairId, bool visible, float fillAmount)
    {
        GameObject box;
        if (!activeBoxes.TryGetValue(pairId, out box) || box == null)
        {
            return;
        }

        Image[] images = box.GetComponentsInChildren<Image>(true);
        foreach (Image img in images)
        {
            if (img == null || img.type != Image.Type.Filled)
            {
                continue;
            }

            img.gameObject.SetActive(visible);
            if (visible)
            {
                img.fillAmount = fillAmount;
            }
            break;
        }
    }

    void OnConvButtonClicked(string pairId, string agent1, string agent2)
    {
        if (activeBoxes.TryGetValue(pairId, out GameObject box) && box != null)
        {
            Destroy(box);
        }
        activeBoxes.Remove(pairId);
        boxEntryTimes.Remove(pairId);
        pairAgents.Remove(pairId);
        Debug.Log($"[ConvVisualizer] Clicked conversation between {agent1} and {agent2}");
        if (DialogueManager.Instance != null)
        {
            DialogueManager.Instance.StartDialogueSession(agent1, agent2);
        }
    }
}

```
