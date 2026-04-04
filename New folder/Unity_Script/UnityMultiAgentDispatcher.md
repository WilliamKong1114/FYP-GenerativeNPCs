```csharp

using System.Collections.Generic;
using System.Linq;
using UnityEngine;

public class UnityMultiAgentDispatcher : MonoBehaviour
{
    public void HandleCommand(MovementCommand cmd)
    {
        if (cmd.action.ToLower() == "time_update")
        {
            if (WorldClock.Instance != null)
            {
                WorldClock.Instance.UpdateTime(cmd.content);
            }
            return;
        }

        GameObject agentObj = GameObject.Find(cmd.agent);
        if (agentObj == null)
        {
            return;
        }
        SimAgent simAgent = agentObj.GetComponent<SimAgent>();
        Debug.Log($"Doing {cmd.action} by {cmd.agent}; Emoji: {cmd.content}");

        switch (cmd.action.ToLower())
        {
            case "move_to":
                Debug.Log($"[Dispatcher] Processing move_to for {cmd.agent}: target={cmd.target}, content={cmd.content}");
                simAgent.MoveTo(cmd.target);
                simAgent.showDialogue(cmd.content, cmd.display_time);
                break;

            case "show_dialogue":
                simAgent.showDialogue(cmd.content, cmd.display_time);
                break;

            case "set_chatting":
                bool isChatting = (cmd.content == "start");
                string partner = isChatting ? cmd.partner : null;
                simAgent.SetConversationState(isChatting, partner);
                break;

            case "show_dialogue":
                simAgent.showDialogue(cmd.content, cmd.display_time);
                break;

            case "interact":
                simAgent.Interact(cmd.method, cmd.target, cmd.color);
                break;

            case "update_dialogue":
                if (DialogueManager.Instance != null && !string.IsNullOrEmpty(cmd.content))
                {
                    string[] lines = cmd.content.Split(new[] {'\n'}, System.StringSplitOptions.RemoveEmptyEntries);
                    List<string> linesList = new List<string>(lines);
                    DialogueManager.Instance.UpdateDialogue(cmd.agent_ids, linesList);
                    DialogueManager.Instance.OnDataReceived();
                }
                break;

            case "user_chat_response":
                if (InteractionManager.Instance != null)
                {
                    InteractionManager.Instance.HandleBackendResponse(cmd.content, cmd.request_id);
                }
                break;

            case "set_chatting":
                bool isChatting = (cmd.content == "start");
                string partner = isChatting ? cmd.partner : null;
                simAgent.SetConversationState(isChatting, partner);
                break;

            case "action_recorded":
                if (ActionLogPanel.Instance != null)
                {
                    ActionLogPanel.Instance.AddEntry(
                        cmd.agent,
                        cmd.action_text,
                        cmd.location,
                        cmd.day,
                        cmd.time_str
                    );
                }
                break;

            case "stop":
                simAgent.StopMotion();
                break;
        }
    }
}

```
