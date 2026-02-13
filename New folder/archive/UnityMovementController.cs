using System.Collections;
using UnityEngine;

public class UnityMovementController : MonoBehaviour
{
    public float moveSpeed = 1.0f;
    public float rotateSpeed = 180.0f;
    [Tooltip("Enable 2D mode: movement uses local X/Y (right/up) instead of forward/rotation")]
    public bool is2D = true;

    private Coroutine currentMotion = null;

    void Update()
    {
        if (is2D)
        {
            // WASD or arrow keys move on local X/Y (right/up) plane for 2D
            float up = Input.GetKey(KeyCode.W) || Input.GetKey(KeyCode.UpArrow) ? 1f : 0f;
            float down = Input.GetKey(KeyCode.S) || Input.GetKey(KeyCode.DownArrow) ? 1f : 0f;
            float left = Input.GetKey(KeyCode.A) || Input.GetKey(KeyCode.LeftArrow) ? 1f : 0f;
            float right = Input.GetKey(KeyCode.D) || Input.GetKey(KeyCode.RightArrow) ? 1f : 0f;

            if (up > 0f)
            {
                transform.position += transform.up * (moveSpeed * Time.deltaTime);
            }
            else if (down > 0f)
            {
                transform.position -= transform.up * (moveSpeed * Time.deltaTime);
            }

            if (right > 0f)
            {
                transform.position += transform.right * (moveSpeed * Time.deltaTime);
            }
            else if (left > 0f)
            {
                transform.position -= transform.right * (moveSpeed * Time.deltaTime);
            }
        }
        else
        {
            float forward = Input.GetKey(KeyCode.W) || Input.GetKey(KeyCode.UpArrow) ? 1f : 0f;
            float back = Input.GetKey(KeyCode.S) || Input.GetKey(KeyCode.DownArrow) ? 1f : 0f;
            float left = Input.GetKey(KeyCode.A) || Input.GetKey(KeyCode.LeftArrow) ? 1f : 0f;
            float right = Input.GetKey(KeyCode.D) || Input.GetKey(KeyCode.RightArrow) ? 1f : 0f;

            if (forward > 0f)
            {
                transform.position += transform.forward * (moveSpeed * Time.deltaTime);
            }
            else if (back > 0f)
            {
                transform.position -= transform.forward * (moveSpeed * Time.deltaTime);
            }

            float turn = right - left;
            if (Mathf.Abs(turn) > 0f)
            {
                transform.Rotate(0f, turn * rotateSpeed * Time.deltaTime, 0f, Space.Self);
            }
        }
    }

    public void MoveForward(float distance = 1.0f)
    {
        StartMotion(TranslateDistance(transform.forward, distance));
    }

    public void MoveBackward(float distance = 1.0f)
    {
        StartMotion(TranslateDistance(-transform.forward, distance));
    }

    /// <summary>
    /// Move up (local Y) by 'distance' metres.
    /// </summary>
    public void MoveUp(float distance = 1.0f)
    {
        StartMotion(TranslateDistance(transform.up, distance));
    }

    /// <summary>
    /// Move down (local Y) by 'distance' metres.
    /// </summary>
    public void MoveDown(float distance = 1.0f)
    {
        StartMotion(TranslateDistance(-transform.up, distance));
    }

    /// <summary>
    /// Move right (local X) by 'distance' metres.
    /// </summary>
    public void MoveRight(float distance = 1.0f)
    {
        StartMotion(TranslateDistance(transform.right, distance));
    }

    /// <summary>
    /// Move left (local X) by 'distance' metres.
    /// </summary>
    public void MoveLeft(float distance = 1.0f)
    {
        StartMotion(TranslateDistance(-transform.right, distance));
    }

    public void Turn(float angle = 90f)
    {
        StartMotion(RotateAngle(angle));
    }

    /// <summary>
    /// Stop any ongoing motion (translate or rotate) immediately.
    /// </summary>
    public void StopMotion()
    {
        if (currentMotion != null)
        {
            StopCoroutine(currentMotion);
            currentMotion = null;
        }
    }

    private void StartMotion(IEnumerator routine)
    {
        StopMotion();
        currentMotion = StartCoroutine(RunMotion(routine));
    }

    private IEnumerator RunMotion(IEnumerator routine)
    {
        yield return StartCoroutine(routine);
        currentMotion = null;
    }

    private IEnumerator TranslateDistance(Vector3 dir, float distance)
    {
        float remaining = Mathf.Abs(distance);
        float sign = Mathf.Sign(distance);
        Vector3 direction = dir.normalized * sign;
        while (remaining > 0f)
        {
            float step = moveSpeed * Time.deltaTime;
            float move = Mathf.Min(step, remaining);
            transform.position += direction * move;
            remaining -= move;
            yield return null;
        }
    }

    private IEnumerator RotateAngle(float angle)
    {
        float remaining = Mathf.Abs(angle);
        float dir = Mathf.Sign(angle);
        while (remaining > 0f)
        {
            float step = rotateSpeed * Time.deltaTime;
            float rot = Mathf.Min(step, remaining);
            transform.Rotate(0f, rot * dir, 0f, Space.Self);
            remaining -= rot;
            yield return null;
        }
    }
}
