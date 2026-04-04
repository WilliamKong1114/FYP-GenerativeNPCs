```csharp

using UnityEngine;
using TMPro;

public class WorldClock : MonoBehaviour
{
    public static WorldClock Instance;
    [SerializeField] private TextMeshProUGUI clockText;

    private void Awake()
    {
        if (Instance == null)
        {
            Instance = this;
        }
        else
        {
            Destroy(gameObject);
        }
    }

    public void UpdateTime(string timeString)
    {
        if (clockText != null)
        {
            clockText.text = timeString;
        }
    }
}

```
