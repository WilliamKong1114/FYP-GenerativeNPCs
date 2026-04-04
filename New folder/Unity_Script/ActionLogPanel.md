```csharp

using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using TMPro;
using UnityEngine.UI;

public class ActionLogPanel : MonoBehaviour
{
    public static ActionLogPanel Instance;

    [Header("UI References")]
    public Transform logContent;          // SCROLL VIEW > Viewport > Content
    public GameObject logEntryPrefab;     // Prefab with TMP_Text
    public ScrollRect scrollRect;         // The Scroll View component

    [Header("Dropdown Toggle")]
    public GameObject scrollArea;         // The whole SCROLL VIEW object
    private bool isOpen = false;

    private List<ActionEntry> allEntries = new List<ActionEntry>();
    private const int MAX_ENTRIES = 200;

    struct ActionEntry
    {
        public string agentId;
        public string text;
        public string location;
        public int day;
        public string time;
        public string formatted;

        public ActionEntry(string agent, string action, string loc, int d, string t)
        {
            agentId = agent;
            text = action;
            location = loc;
            day = d;
            time = t;
            formatted = $"<color=#FF0000>[Day {day}, {time}]</color> {agentId}: {text} at {location}";
        }
    }

    void Awake()
    {
        if (Instance == null) Instance = this;
        else
        {
            Destroy(gameObject);
            return;
        }

        if (scrollArea != null)
            scrollArea.SetActive(false);
    }

    public void ToggleDropdown()
    {
        isOpen = !isOpen;

        if (scrollArea != null)
            scrollArea.SetActive(isOpen);

        if (isOpen)
            RefreshDisplay();
    }

    public void AddEntry(string agentId, string actionText, string location, int day, string timeStr)
    {
        ActionEntry newEntry = new ActionEntry(agentId, actionText, location, day, timeStr);
        allEntries.Add(newEntry);

        if (allEntries.Count > MAX_ENTRIES)
            allEntries.RemoveAt(0);

        RefreshDisplay();
    }

    private void RefreshDisplay()
    {
        if (logContent == null || logEntryPrefab == null) return;

        // Clear old UI items
        for (int i = logContent.childCount - 1; i >= 0; i--)
        {
            Destroy(logContent.GetChild(i).gameObject);
        }

        // Recreate all entries
        foreach (ActionEntry entry in allEntries)
        {
            CreateUIEntry(entry.formatted);
        }

        StartCoroutine(RebuildAndScroll());
    }

    private void CreateUIEntry(string text)
    {
        GameObject newObj = Instantiate(logEntryPrefab, logContent, false);

        TMP_Text tmp = newObj.GetComponent<TMP_Text>();
        if (tmp == null)
            tmp = newObj.GetComponentInChildren<TMP_Text>();

        if (tmp != null)
        {
            tmp.text = text;
        }
        else
        {
            Debug.LogWarning("logEntryPrefab has no TMP_Text component.");
        }
    }

    private IEnumerator RebuildAndScroll()
    {
        yield return null;
        yield return new WaitForEndOfFrame();

        Canvas.ForceUpdateCanvases();

        RectTransform contentRect = logContent as RectTransform;
        if (contentRect != null)
            LayoutRebuilder.ForceRebuildLayoutImmediate(contentRect);

        if (scrollRect != null)
            scrollRect.verticalNormalizedPosition = 0f;
    }

    private IEnumerator ScrollToBottomNextFrame()
    {
        yield return null;

        Canvas.ForceUpdateCanvases();

        RectTransform contentRect = logContent as RectTransform;
        if (contentRect != null)
            LayoutRebuilder.ForceRebuildLayoutImmediate(contentRect);

        if (scrollRect != null)
            scrollRect.verticalNormalizedPosition = 0f;
    }

    public void ClearLog()
    {
        allEntries.Clear();

        for (int i = logContent.childCount - 1; i >= 0; i--)
        {
            Destroy(logContent.GetChild(i).gameObject);
        }
    }
}

```
