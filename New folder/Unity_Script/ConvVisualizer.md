```csharp

using System.Collections.Generic;
using TMPro;
using UnityEngine;
using UnityEngine.UI;

public class ConvVisualizer : MonoBehaviour
{
    public float TriggerDistance = 3.0f;
    public GameObject boxPrefab;
    public Canvas canvas;

    private Dictionary<string, GameObject> activeBoxes = new Dictionary<string, GameObject>();
    private SimAgent[] agents;

    private float timer = 0f;
    private int dotCount = 0;

    void Start()
    {
        agents = FindObjectsOfType<SimAgent>();
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
                UpdateBox(pairId, a1, a2);
            }
        }
    }

    void removePair(HashSet<string> currentPairs)
    {
        List<string> toRemove = new List<string>();
        foreach (var pairId in activeBoxes.Keys)
        {
            if (!currentPairs.Contains(pairId)) toRemove.Add(pairId);
        }

        foreach (var id in toRemove)
        {
            if (activeBoxes[id] != null) Destroy(activeBoxes[id]);
            activeBoxes.Remove(id);
        }
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

                Button btn = box.GetComponent<Button>() ?? box.GetComponentInChildren<Button>();
                if (btn != null)
                {
                    btn.onClick.RemoveAllListeners();
                    btn.onClick.AddListener(() => OnConvButtonClicked(a1, a2));
                }
            }
        }

        if (box == null) return;

        if (!box.activeSelf) box.SetActive(true);

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

    void OnConvButtonClicked(SimAgent a1, SimAgent a2)
    {
        //Debug.Log($"[ConvVisualizer] Clicked conversation between {a1.name} and {a2.name}");
        if (DialogueManager.Instance != null)
        {
            DialogueManager.Instance.StartDialogueSession(a1.name, a2.name);
        }
    }
}

```
