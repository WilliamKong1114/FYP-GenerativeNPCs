```csharp

using System.Collections.Generic;
using System.Net.Sockets;
using System.Text;
using UnityEngine;
public class AreaDetector : MonoBehaviour
{
    private string areaName;

    private void Start()
    {
        areaName = gameObject.name;
    }

    private void OnTriggerEnter2D(Collider2D other)
    {
        SimAgent agent = other.GetComponent<SimAgent>();

        if (agent != null)
        {
            string agentId = other.gameObject.name;
            //Debug.Log($"{agentId} entered the {areaName}!");
            sendUpdate(agentId, "enter");
        }
    }

    private void OnTriggerExit2D(Collider2D other)
    {
        SimAgent agent = other.GetComponent<SimAgent>();

        if (agent != null)
        {
            string agentId = other.gameObject.name;
            //Debug.Log($"{agentId} Leave the {areaName}!");
            sendUpdate(agentId, "exit");
        }
    }

    public void sendUpdate(string agentName, string status)
    {
        try
        {
            using (TcpClient client = new TcpClient("127.0.0.1", 5006))
            using (NetworkStream stream = client.GetStream())
            {
                string msg = $"[\"{agentName}\", \"{areaName}\", \"{status}\"]\n";
                byte[] data = Encoding.UTF8.GetBytes(msg);
                stream.Write(data, 0, data.Length);
            }
        }
        catch (System.Exception e)
        {
            Debug.LogWarning($"Secondary error in sendUpdate: {e.Message}");
        }
    }
}

```
