```csharp

using System.Collections.Generic;
using UnityEngine;

public class UnityMultiAgentDispatcher : MonoBehaviour
{
    public void HandleCommand(MovementCommand cmd)
    {
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
                simAgent.showDialogue(cmd.content);
                break;

            case "interact":
                simAgent.Interact(cmd.method, cmd.target, cmd.color);
                break;

            case "update_dialogue":
                if (DialogueManager.Instance != null && !string.IsNullOrEmpty(cmd.content))
                {
                    string[] lines = cmd.content.Split(new[] { '\n' }, System.StringSplitOptions.RemoveEmptyEntries);
                    List<string> linesList = new List<string>(lines);
                    DialogueManager.Instance.UpdateDialogue(linesList);
                }
                break;

            case "show_dialogue":
                simAgent.showDialogue(cmd.content);
                break;

            case "set_chatting":
                simAgent.IsInConversation = (cmd.content == "start");
                break;

            case "stop":
                simAgent.StopMotion();
                break;
        }
    }
}

```
