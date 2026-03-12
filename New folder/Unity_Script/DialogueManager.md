```csharp
using UnityEngine;
using TMPro;
using UnityEngine.UI;
using System.Collections.Generic;
using UnityEngine.EventSystems;

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
    private string sessionAgent;
    private readonly Dictionary<string, Sprite> portraitCache = new Dictionary<string, Sprite>();

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

    public void StartDialogueSession(string agentName)
    {
        sessionAgent = agentName;
        dialoguePanel.SetActive(true);
        dialogueLines.Clear();
        currentIndex = -1;
        isWaitingForData = true;
        dotCount = 0;
        timer = 0f;
        UpdateLoadingText();
    }

    public void UpdateDialogue(List<string> lines)
    {
        if (lines == null || lines.Count == 0) return;
        dialogueLines = lines;
        isWaitingForData = false;
        if (currentIndex == -1)
        {
            currentIndex = 0;
            DisplayLine();
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
            dialoguePanel.SetActive(false);
            EndDialogue();
            currentIndex = -1;
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
        dialoguePanel.SetActive(false);
        portraitCache.Clear();
        MovementCommand cmd = new MovementCommand
        {
            action = "conversation_finished",
            agent = sessionAgent
        };

        UnityTcpListener.SendToAgent(cmd.agent, JsonUtility.ToJson(cmd));
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
        } else
        {
            Debug.Log("Portrait not found");
            portraitImage.gameObject.SetActive(false);
        }
        return;
    }

    public void CloseDialoguePanel()
    {
        if (isWaitingForData)
        {
            dialoguePanel.SetActive(false);
        }
        else
        {
            EndDialogue();
        }
    }
}
```
