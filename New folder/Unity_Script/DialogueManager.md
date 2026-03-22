```csharp

using UnityEngine;
using TMPro;
using UnityEngine.UI;
using System.Collections.Generic;
using UnityEngine.EventSystems;
using System.Linq;

public class DialogueManager : MonoBehaviour, IPointerClickHandler
{
    public static DialogueManager Instance;

    public GameObject dialoguePanel;
    public TMP_Text nameText;
    public TMP_Text dialogueText;
    public Image portraitImage;
    public Button closeBtn;

    private List<string> dialogueLines = new List<string>();
    private int currentIndex = -1;
    private bool isWaitingForData = false;
    private bool isSessionActive = false;
    private string sessionAgent;
    private string partnerAgent;
    private readonly Dictionary<string, Sprite> portraitCache = new Dictionary<string, Sprite>();

    [System.Serializable]
    public class ConversationRecord
    {
        public List<string> agent_ids;
        public List<string> lines;
    }

    private List<ConversationRecord> convList = new List<ConversationRecord>();

    private string GetConvKey(string a, string b)
    {
        var agents = new List<string> { a, b };
        agents.Sort();
        return string.Join("_", agents);
    }

    void Awake()
    {
        Instance = this;
        dialoguePanel.SetActive(false);
    }

    private float timer = 0f;
    private int dotCount = 0;

    void Update()
    {
        if (isWaitingForData)
        {
            timer += Time.deltaTime;
            if (timer >= 0.5f)
            {
                timer = 0f;
                dotCount = (dotCount % 3) + 1;
                UpdateLoadingText();
            }
        }
    }

    void UpdateLoadingText()
    {
        string dots = new string('.', dotCount);
        nameText.text = dots;
        dialogueText.text = "Loading conversation" + dots;
    }

    public void StartDialogueSession(string agent1, string agent2)
    {
        sessionAgent = agent1;
        partnerAgent = agent2;
        isSessionActive = true;
        dialoguePanel.SetActive(true);
        dialogueLines.Clear();
        currentIndex = -1;
        isWaitingForData = true;
        dotCount = 0;
        timer = 0f;
        //UpdateLoadingText();

        ConversationRecord match = convList.LastOrDefault(c => c.agent_ids.Contains(agent1) && c.agent_ids.Contains(agent2));
        if (match != null)
        {
            dialogueLines = new List<string>(match.lines);
            isWaitingForData = false;
            currentIndex = 0;
            DisplayLine();
        }

        convList.RemoveAll(c => c.agent_ids.Contains(agent1) || c.agent_ids.Contains(agent2));

        if (isWaitingForData)
        {
            UpdateLoadingText();
        }
    }

    public bool HasActiveSession()
    {
        return isSessionActive;
    }

    public void ShowDialoguePanel()
    {
        if (!isSessionActive) return;

        dialoguePanel.SetActive(true);

        if (isWaitingForData)
        {
            UpdateLoadingText();
            return;
        }

        if (dialogueLines != null && dialogueLines.Count > 0 && currentIndex >= 0)
        {
            DisplayLine();
        }
    }

    public void UpdateDialogue(List<string> agent_ids, List<string> lines)
    {
        if (agent_ids == null || agent_ids.Count < 2) return;

        bool isCurrentSession = isSessionActive && agent_ids.Contains(sessionAgent) && agent_ids.Contains(partnerAgent);

        convList.Add(new ConversationRecord { agent_ids = agent_ids, lines = lines });

        if (isCurrentSession && isWaitingForData)
        {
            dialogueLines = new List<string>(lines);
            isWaitingForData = false;

            convList.RemoveAll(c => c.agent_ids.Contains(sessionAgent) || c.agent_ids.Contains(partnerAgent));

            if (!dialoguePanel.activeSelf)
            {
                EndDialogue();
                return;
            }

            if (currentIndex == -1)
            {
                currentIndex = 0;
                DisplayLine();
            }
        }
        else if (!isCurrentSession)
        {
            // Conversation finished for a pair the user hasn't opened — auto-dismiss the floating button
            string agent1 = agent_ids[0];
            string agent2 = agent_ids[1];

            SimAgent sa = GameObject.Find(agent1)?.GetComponent<SimAgent>();
            SimAgent pa = GameObject.Find(agent2)?.GetComponent<SimAgent>();
            sa?.SetConversationState(false);
            pa?.SetConversationState(false);

            MovementCommand cmd = new MovementCommand { action = "conversation_finished" };
            cmd.agent = agent1;
            UnityTcpListener.SendToAgent(agent1, JsonUtility.ToJson(cmd));
            cmd.agent = agent2;
            UnityTcpListener.SendToAgent(agent2, JsonUtility.ToJson(cmd));

            convList.RemoveAll(c => c.agent_ids.Contains(agent1) || c.agent_ids.Contains(agent2));
        }
    }

    public void OnPointerClick(PointerEventData eventData)
    {
        if (isWaitingForData || dialogueLines == null || dialogueLines.Count == 0) return;

        if (currentIndex < dialogueLines.Count - 1)
        {
            currentIndex++;
            DisplayLine();
        }
        else
        {
            EndDialogue();
        }
    }

    void DisplayLine()
    {
        string rawLine = dialogueLines[currentIndex];
        if (rawLine == null) return;
        if (rawLine.Contains(":"))
        {
            string[] split = rawLine.Split(new[] { ':' }, 2);
            string speaker = split[0].Trim();
            nameText.text = speaker;
            dialogueText.text = split[1].Trim().Trim('"');
            UpdatePortrait(speaker);
        }
        else
        {
            dialogueText.text = rawLine;
        }
    }

    void EndDialogue()
    {
        if (!isSessionActive) return;

        isSessionActive = false;
        isWaitingForData = false;
        currentIndex = -1;
        dialogueLines.Clear();
        dialoguePanel.SetActive(false);
        portraitCache.Clear();

        SimAgent sa = GameObject.Find(sessionAgent)?.GetComponent<SimAgent>();
        SimAgent pa = GameObject.Find(partnerAgent)?.GetComponent<SimAgent>();
        sa?.SetConversationState(false);
        pa?.SetConversationState(false);

        MovementCommand cmd = new MovementCommand { action = "conversation_finished" };

        cmd.agent = sessionAgent;
        UnityTcpListener.SendToAgent(sessionAgent, JsonUtility.ToJson(cmd));

        cmd.agent = partnerAgent;
        UnityTcpListener.SendToAgent(partnerAgent, JsonUtility.ToJson(cmd));
    }

    void UpdatePortrait(string speakerName)
    {
        if (portraitCache.TryGetValue(speakerName, out Sprite sprite))
        {
            portraitImage.sprite = sprite;
            portraitImage.gameObject.SetActive(true);
            return;
        }

        Sprite loadedPortrait = Resources.Load<Sprite>($"Portraits/{speakerName}");
        if (loadedPortrait != null)
        {
            portraitImage.sprite = loadedPortrait;
            portraitCache[speakerName] = loadedPortrait;
            portraitImage.gameObject.SetActive(true);
        }
        else
        {
            Debug.Log("Portrait not found");
            portraitImage.gameObject.SetActive(false);
        }
        return;
    }

    public void CloseDialoguePanel()
    {
        if (isSessionActive && isWaitingForData)
        {
            dialoguePanel.SetActive(false);
            return;
        }

        if (isSessionActive && (dialogueLines == null || dialogueLines.Count == 0))
        {
            dialoguePanel.SetActive(false);
            return;
        }

        EndDialogue();
    }
}

```
