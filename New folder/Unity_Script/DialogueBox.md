```csharp

using System.Collections;
using System.Collections.Generic;
using TMPro;
using UnityEngine;

public class DialogueBox : MonoBehaviour
{
    public GameObject FollowObject;
    public Vector3 WorldOffset = new Vector3(0, 2.0f, 0);

    private RectTransform _rectTransform;
    private Camera _mainCamera;

    void Start()
    {
        _rectTransform = GetComponent<RectTransform>();
        _mainCamera = Camera.main;
    }

    void LateUpdate()
    {
        if (FollowObject == null || _mainCamera == null)
            return;

        Vector3 targetWorldPosition = FollowObject.transform.position + WorldOffset;
        Vector3 screenPosition = _mainCamera.WorldToScreenPoint(targetWorldPosition);

        if (screenPosition.z > 0)
        {
            if (!gameObject.activeSelf)
            {
                gameObject.SetActive(true);
            }
            _rectTransform.position = screenPosition;
        }
        else
        {
            _rectTransform.position = new Vector3(-10000, -10000, 0);
        }
    }
}
```
