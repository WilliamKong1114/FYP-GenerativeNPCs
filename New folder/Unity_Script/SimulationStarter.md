```csharp

using UnityEngine;
using UnityEngine.Networking;
using System.Collections;
using System.Text;
using System.Collections.Generic;
using System;

[System.Serializable]
public class ConversationRequest
{
    public string initiator;
    public string receiver;
    public string initLoc;
    public string recLoc;
    public string context;
}

public class SimulationStarter : MonoBehaviour
{
    public static SimulationStarter Instance;
    public string lastConversationLog = "No conversation recorded.";

    [System.Serializable]
    public class ConversationResponse { public List<string> dialogue; }

    [Header("Backend Configuration")]
    // Ensure this matches the port in your python debug_server.py (usually 8080 or 8000)
    public string backendUrl = "http://localhost:8080";

    void Awake()
    {
        // Singleton pattern: vital for Editor scripts to find this instance
        if (Instance == null)
        {
            Instance = this;
            DontDestroyOnLoad(gameObject); // Optional: keeps it alive if you change scenes
        }
        else
        {
            Destroy(gameObject);
        }
    }

    void Start()
    {
        // Optional: Ping the server to see if it's alive when game starts
        StartCoroutine(HealthCheck());
    }

    /// <summary>
    /// Checks if the Python server is running.
    /// </summary>
    IEnumerator HealthCheck()
    {
        using (UnityWebRequest request = UnityWebRequest.Get(backendUrl + "/health"))
        {
            yield return request.SendWebRequest();

            if (request.result == UnityWebRequest.Result.Success)
            {
                Debug.Log($"[SimStarter] Backend Connected: {request.downloadHandler.text}");
            }
            else
            {
                Debug.LogWarning($"[SimStarter] Could not reach backend at {backendUrl}. Is 'debug_server.py' running?");
            }
        }
    }

    [Serializable]
    public class AreaUpdatePayload
    {
        public string agentName;
        public string areaName;
        public string status;
    }

    public IEnumerator RequestAreaUpdate(List<string> msg)
    {
        string url = $"{backendUrl}/update_area";

        var payload = new AreaUpdatePayload
        {
            agentName = msg[0],
            areaName = msg[1],
            status = msg[2]
        };

        string json = JsonUtility.ToJson(payload);

        using (UnityWebRequest request = new UnityWebRequest(url, "POST"))
        {
            byte[] bodyRaw = Encoding.UTF8.GetBytes(json);
            request.uploadHandler = new UploadHandlerRaw(bodyRaw);
            request.downloadHandler = new DownloadHandlerBuffer();
            request.SetRequestHeader("Content-Type", "application/json");

            Debug.Log($"[SimStarter] Requesting updating area...");
            yield return request.SendWebRequest();

            if (request.result == UnityWebRequest.Result.Success)
            {
                string responseJson = request.downloadHandler.text;
                string resp = JsonUtility.FromJson<string>(responseJson);
                Debug.Log(resp);
            }
            else
            {
                Debug.LogError($"[SimStarter] Area Update Request Failed: {request.error}\nResponse: {request.downloadHandler.text}");
            }
        }
    }

    public IEnumerator RequestConversation(string initiator, string receiver, string initLoc, string recLoc, string context = "Casual chat")
    {
        string url = $"{backendUrl}/generate_conversation";

        GameObject initObj = GameObject.Find(initiator);
        GameObject recObj = GameObject.Find(receiver);
        SimAgent initAgent = initObj.GetComponent<SimAgent>();
        SimAgent recAgent = recObj.GetComponent<SimAgent>();

        ConversationRequest payload = new ConversationRequest
        {
            initiator = initiator,
            receiver = receiver,
            initLoc = initLoc,
            recLoc = recLoc,
            context = context
        };

        string json = JsonUtility.ToJson(payload);
        initAgent.IsInConversation = true;
        recAgent.IsInConversation = true;

        using (UnityWebRequest request = new UnityWebRequest(url, "POST"))
        {
            byte[] bodyRaw = Encoding.UTF8.GetBytes(json);
            request.uploadHandler = new UploadHandlerRaw(bodyRaw);
            request.downloadHandler = new DownloadHandlerBuffer();
            request.SetRequestHeader("Content-Type", "application/json");

            Debug.Log($"[SimStarter] Requesting conversation between {initiator} and {receiver}...");

            yield return request.SendWebRequest();

            if (request.result == UnityWebRequest.Result.Success)
            {
                string responseJson = request.downloadHandler.text;
                ConversationResponse resp = JsonUtility.FromJson<ConversationResponse>(responseJson);

                if (DialogueManager.Instance != null)
                {
                    if (resp != null && resp.dialogue != null && resp.dialogue.Count != 0)
                    {
                        DialogueManager.Instance.UpdateDialogueData(resp.dialogue);
                    }
                    else
                    {
                        lastConversationLog = "No Conversation";
                    }
                }

                yield return new WaitForSeconds(1.0f);

                //if (resp != null && resp.dialogue != null && resp.dialogue.Count != 0)
                //{
                //    string body = string.Join("\n", resp.dialogue);
                //    lastConversationLog = body + "\n--- END ---";

                //} else
                //{
                //    lastConversationLog = "No Conversation";
                //}

                //yield return new WaitForSeconds(4.0f);
            }
            else
            {
                Debug.LogError($"[SimStarter] Conversation Request Failed: {request.error}\nResponse: {request.downloadHandler.text}");
            }
        }

        if (initAgent != null) initAgent.IsInConversation = false;
        if (recAgent != null) recAgent.IsInConversation = false;
    }
}



```
