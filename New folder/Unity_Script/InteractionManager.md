```csharp

using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;
using TMPro;
using Unity.VisualScripting;

public class InteractionManager : MonoBehaviour
{
    public static InteractionManager Instance;

    public GameObject InteractionPanel;
    public TMP_Text nameText;
    public TMP_Text dialogueText;
    public Image portraitImage;

    public Transform questionSelectionRoot;
    public Transform replySelectionRoot;
    public string openingText = "Hi! How are you feeling today?";
    public string CurrentSessionId { get; private set; }
    public string CurrentAgentId { get; private set; }
    public List<InteractionOption> CurrentOptions { get; private set; } = new List<InteractionOption>();

    [Serializable]
    public class InteractionOption
    {
        public string id;
        public string text;
    }

    [Serializable]
    private class BackendResponse
    {
        public string command;
        public string status;
        public string message;
        public string agent_id;
        public bool available;
        public string session_id;
        public string agent_text;
        public bool agent_question;
        public bool ended;
        public List<InteractionOption> options;
    }

    private readonly List<Button> questionButtons = new List<Button>();
    private readonly List<Button> replyButtons = new List<Button>();

    void Awake()
    {
        Instance = this;
        CacheButtons(questionSelectionRoot, questionButtons);
        CacheButtons(replySelectionRoot, replyButtons);
        InteractionPanel.SetActive(false);
    }

    public void StartInteraction(string agentId)
    {
        if (string.IsNullOrWhiteSpace(agentId))
        {
            Debug.Log("No agent name detected.");
            return;
        }

        CurrentAgentId = agentId;
        CurrentSessionId = null;
        CurrentOptions.Clear();

        SendCommand(new MovementCommand
        {
            //request_id = Guid.NewGuid().ToString(),
            action = "user_chat",
            agent = agentId,
            user_text = openingText,
        });
    }

    public void handleResponse(string jsonContent, string requestId)
    {
        if (string.IsNullOrWhiteSpace(jsonContent))
        {
            Debug.Log("Null Content");
            return;
        }

        BackendResponse payload = JsonUtility.FromJson<BackendResponse>(jsonContent);
        if (payload == null)
            return;

        if (payload.status != null && payload.status != "success")
        {
            Debug.Log($"[Interaction] Request failed: {payload.message}");
            return;
        }

        if (payload.ended)
        {
            Debug.Log($"Interaction Ended: {payload.message}");
            EndInteraction(payload.agent_id);
            return;
        }

        ApplyResponse(payload);
        Debug.Log($"[Interaction] {payload.agent_id}: {payload.agent_text}");
    }

    private void ApplyResponse(BackendResponse payload)
    {
        CurrentAgentId = payload.agent_id;
        CurrentSessionId = payload.session_id;
        CurrentOptions = payload.options ?? new List<InteractionOption>();

        InteractionPanel.SetActive(true);

        if (nameText != null)
            nameText.text = payload.agent_id ?? string.Empty;

        if (dialogueText != null)
            dialogueText.text = payload.agent_text ?? string.Empty;

        bool isQuestion = payload.agent_question;
        BindOptions(CurrentOptions, isQuestion);
    }

    private void BindOptions(List<InteractionOption> options, bool isQuestion)
    {
        if (questionSelectionRoot != null)
            questionSelectionRoot.gameObject.SetActive(!isQuestion);

        if (replySelectionRoot != null)
            replySelectionRoot.gameObject.SetActive(isQuestion);

        SetButtonGroup(questionButtons, !isQuestion ? options : null);
        SetButtonGroup(replyButtons, isQuestion ? options : null);
    }

    private void SetButtonGroup(List<Button> buttons, List<InteractionOption> options)
    {
        for (int i = 0; i < buttons.Count; i++)
        {
            Button button = buttons[i];
            button.onClick.RemoveAllListeners();

            if (options != null && i < options.Count && options[i] != null)
            {
                button.gameObject.SetActive(true);
                InteractionOption option = options[i];
                TMP_Text text = button.GetComponentInChildren<TMP_Text>();
                if (text != null)
                    text.text = option.text;

                string optionId = option.id;
                int optionIndex = i;
                button.onClick.AddListener(() =>
                {
                    if (options != null && optionIndex == options.Count - 1)
                    {
                        EndInteraction(CurrentAgentId);
                    }
                    else
                    {
                        ChooseOption(optionId);
                    }
                });
            }
            else
            {
                button.gameObject.SetActive(false);
            }
        }
    }

    public void ChooseOption(string optionId)
    {
        if (string.IsNullOrWhiteSpace(CurrentSessionId) || string.IsNullOrWhiteSpace(optionId))
            return;

        string selectedText = optionId;
        InteractionOption selected = CurrentOptions.Find(o => o.id == optionId);
        if (selected != null && !string.IsNullOrWhiteSpace(selected.text))
        {
            selectedText = selected.text;
        }

        SendCommand(new MovementCommand
        {
            action = "user_chat",
            agent = CurrentAgentId,
            session_id = CurrentSessionId,
            user_text = selectedText,
            //request_id = Guid.NewGuid().ToString()
        });
    }

    public void CloseInteractionPanel()
    {
        InteractionPanel.SetActive(false);
        EndInteraction(CurrentAgentId);
    }

    public void EndInteraction(string agentId)
    {
        Debug.Log($"End interact with {agentId}.");

        if (!string.IsNullOrWhiteSpace(CurrentAgentId))
        {
            SendCommand(new MovementCommand
            {
                action = "conversation_finished",
                agent = CurrentAgentId,
                request_id = Guid.NewGuid().ToString()
            });
        }

        CurrentSessionId = null;
        CurrentAgentId = null;
        CurrentOptions.Clear();
        InteractionPanel.SetActive(false);
    }


    private void CacheButtons(Transform root, List<Button> cache)
    {
        cache.Clear();
        if (root == null)
            return;

        for (int i = 0; i < root.childCount; i++)
        {
            Transform child = root.GetChild(i);
            Button btn = child.GetComponent<Button>() ?? child.GetComponentInChildren<Button>(true);
            if (btn != null)
                cache.Add(btn);
        }
    }

    private void SendCommand(MovementCommand cmd)
    {
        if (cmd == null || string.IsNullOrWhiteSpace(cmd.agent))
        {
            Debug.LogWarning("[Interaction] Cannot send command without agent id.");
            return;
        }

        UnityTcpListener.SendToAgent(cmd.agent, JsonUtility.ToJson(cmd));
    }
}


```
