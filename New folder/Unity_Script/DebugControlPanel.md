```csharp

using UnityEngine;
using UnityEditor;
using System.Collections.Generic;
using System.Linq;
using System.Collections;

public class DebugControlPanel : EditorWindow
{
    private Vector2 scrollPos;
    private GUIStyle wrapperStyle;

    [System.Serializable]
    public class AgentEntry
    {
        public string id;
        public bool isSelected;
        public int locationIndex;
    }

    private List<AgentEntry> agentList = new List<AgentEntry>
    {
        new AgentEntry { id = "Samson", isSelected = false },
        new AgentEntry { id = "Jimmy", isSelected = false }
    };

    private string newAgentName = "NewAgent";
    private string[] locations = new string[] {
        "House_Samson", "House_Jimmy", "Workshop", "River", "Garden", "Table_Samson", "Storage_Samson", "Table_Jimmy", "Storage_Jimmy", "Table_Workshop"
    };

    [MenuItem("FYP/Debug Control Panel")]
    public static void ShowWindow() => GetWindow<DebugControlPanel>("Debug Controls");

    void OnGUI()
    {
        if (wrapperStyle == null)
        {
            wrapperStyle = new GUIStyle(EditorStyles.label);
            wrapperStyle.wordWrap = true;
            wrapperStyle.richText = true;
        }

        GUILayout.Label("Agent Manager", EditorStyles.boldLabel);
        DrawAgentList();

        EditorGUILayout.Space();
        GUILayout.Label("Group Actions", EditorStyles.boldLabel);

        DrawGroupActions();

        EditorGUILayout.Space();
        GUILayout.Label("Dialogue Log", EditorStyles.boldLabel);

        EditorGUILayout.BeginVertical("box");
        scrollPos = EditorGUILayout.BeginScrollView(scrollPos, GUILayout.Height(150));

        string logText = (SimulationStarter.Instance != null) ?
                         SimulationStarter.Instance.lastConversationLog :
                         "NO LOG YET.";

        GUILayout.Label(logText, wrapperStyle, GUILayout.ExpandHeight(true));
        //EditorGUILayout.TextArea(logText, GUILayout.ExpandHeight(true));

        EditorGUILayout.EndScrollView();

        if (GUILayout.Button("Clear Log"))
        {
            if (SimulationStarter.Instance != null) SimulationStarter.Instance.lastConversationLog = "";
        }
        EditorGUILayout.EndVertical();
    }

    void DrawAgentList()
    {
        EditorGUILayout.BeginVertical("box");
        GUILayout.Label("Agents", EditorStyles.boldLabel);

        for (int i = 0; i < agentList.Count; i++)
        {
            EditorGUILayout.BeginHorizontal();

            agentList[i].isSelected = EditorGUILayout.Toggle(agentList[i].isSelected, GUILayout.Width(20));
            agentList[i].id = EditorGUILayout.TextField(agentList[i].id, GUILayout.Width(50));
            agentList[i].locationIndex = EditorGUILayout.Popup(agentList[i].locationIndex, locations);
            if (GUILayout.Button("TP", GUILayout.Width(35)))
            {
                MoveAgent(agentList[i].id, locations[agentList[i].locationIndex]);
            }

            GUI.backgroundColor = Color.red;
            if (GUILayout.Button("X", GUILayout.Width(25)))
            {
                bool ok = EditorUtility.DisplayDialog(
                    "Delete agent?", //title
                    $"Remove {agentList[i].id} from the list?", //msg
                    "Yes", "No");

                if (ok)
                {
                    agentList.RemoveAt(i);
                    EditorGUILayout.EndHorizontal();
                    break;
                }
            }
            GUI.backgroundColor = Color.white;
            EditorGUILayout.EndHorizontal();
        }

        EditorGUILayout.Space();
        EditorGUILayout.BeginHorizontal();
        newAgentName = EditorGUILayout.TextField(newAgentName);
        if (GUILayout.Button("Add Agent", GUILayout.Width(80)))
        {
            agentList.Add(new AgentEntry { id = newAgentName, isSelected = true });
            newAgentName = "Agent_" + (agentList.Count + 1);
        }
        EditorGUILayout.EndHorizontal();

        EditorGUILayout.EndVertical();
    }

    void DrawGroupActions()
    {
        if (!Application.isPlaying)
        {
            EditorGUILayout.HelpBox("Enter Play Mode to trigger actions.", MessageType.Info);
            return;
        }

        EditorGUILayout.BeginVertical("box");

        EditorGUILayout.EndVertical();

        EditorGUILayout.Space();

        EditorGUILayout.BeginHorizontal();

        var selectedAgents = agentList.Where(a => a.isSelected).ToList();
        string buttonText = $"Interact ({selectedAgents.Count})";

        if (GUILayout.Button(buttonText, GUILayout.Height(30)))
        {
            if (selectedAgents.Count < 2)
            {
                Debug.LogWarning("[Debug] Select at least 2 agents to start a conversation.");
            }
            else
            {
                TriggerConversation(selectedAgents[0], selectedAgents[1]);
            }
        }
        EditorGUILayout.EndHorizontal();

        EditorGUILayout.Space();

        EditorGUILayout.BeginHorizontal();

        if (GUILayout.Button("Show Detection Box", GUILayout.Height(30)))
        {
            if (selectedAgents.Count < 2)
            {
                Debug.LogWarning("[Debug] Select at least 2 agents to start a conversation.");
            }
            else
            {
                GameObject a1 = GameObject.Find(selectedAgents[0].id);
                GameObject a2 = GameObject.Find(selectedAgents[1].id);
                if (a1 && a2)
                {
                    a1.GetComponent<SimAgent>().IsInConversation = true;
                    a2.GetComponent<SimAgent>().IsInConversation = true;
                    Debug.Log($"[Debug] Visualizer flags enabled for {a1.name} and {a2.name}");
                }
            }
        }

        if (GUILayout.Button("Dismiss Detection Box", GUILayout.Height(30)))
        {
            if (selectedAgents.Count < 2)
            {
                Debug.LogWarning("[Debug] Select at least 2 agents to dismiss the detection box.");
            }
            else
            {
                GameObject a1 = GameObject.Find(selectedAgents[0].id);
                GameObject a2 = GameObject.Find(selectedAgents[1].id);
                if (a1 && a2)
                {
                    a1.GetComponent<SimAgent>().IsInConversation = false;
                    a2.GetComponent<SimAgent>().IsInConversation = false;
                    Debug.Log($"[Debug] Visualizer flags disabled for {a1.name} and {a2.name}");
                }
            }
        }
        EditorGUILayout.EndHorizontal();
    }

    void MoveAgent(string agentId, string targetName)
    {
        GameObject agentObj = GameObject.Find(agentId);
        GameObject targetObj = GameObject.Find(targetName);

        if (targetObj == null)
        {
            Transform placeParent = GameObject.Find("Place")?.transform;
            if (placeParent != null)
            {
                Transform t = placeParent.Find(targetName);
                if (t != null) targetObj = t.gameObject;
            }
        }

        if (agentObj && targetObj)
        {
            agentObj.GetComponent<SimAgent>().MoveTo(targetName);
            Debug.Log($"[Debug] Teleported {agentId} to {targetName}");
        }
        else
        {
            Debug.LogError($"[Debug] Move Failed: Could not find '{agentId}' or '{targetName}'");
        }
    }

    void TriggerConversation(AgentEntry initiator, AgentEntry receiver)
    {
        if (SimulationStarter.Instance != null)
        {
            string initLoc = locations[initiator.locationIndex];
            string recLoc = locations[receiver.locationIndex];

            SimulationStarter.Instance.StartCoroutine(
                SimulationStarter.Instance.RequestConversation(initiator.id, receiver.id, initLoc, recLoc, "Meeting triggered by Debug Panel")
            );
        }
        else
        {
            Debug.LogError("[Debug] SimulationStarter instance not found in scene.");
        }
    }
}

```
