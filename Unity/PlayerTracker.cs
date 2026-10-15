using System.Collections;
using System.Collections.Generic;
using GorillaNetworking;
using LitJson;
using Photon.Pun;
using Photon.Realtime;
using UnityEngine;
using UnityEngine.Networking;
using UnityEngine.SceneManagement;

public class PlayerTracker : MonoBehaviourPunCallbacks
{
    public static PlayerTracker instance;

    public string BackendBaseUrl = "";
    public string TrackerSecret = "";
    public bool EnableTracking = true;
    public float MinReportIntervalSeconds = 5f;

    private readonly Dictionary<string, float> _lastSentAt = new Dictionary<string, float>();
    private float _roomJoinedAt = -1f;
    private string _lastGameMode = "";

    public static void EnsureCreated()
    {
        if (instance != null) return;
        GameObject go = new GameObject("PlayerTracker");
        PlayerTracker tracker = go.AddComponent<PlayerTracker>();
        if (string.IsNullOrEmpty(tracker.BackendBaseUrl))
        {
            tracker.BackendBaseUrl = GetFallbackBackendUrl();
        }
    }

    [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
    private static void Bootstrap()
    {
        EnsureCreated();
    }

    private void Awake()
    {
        if (instance != null && instance != this)
        {
            Destroy(gameObject);
            return;
        }
        instance = this;
        DontDestroyOnLoad(gameObject);
    }

    private void Start()
    {
        if (string.IsNullOrEmpty(BackendBaseUrl))
        {
            BackendBaseUrl = GetFallbackBackendUrl();
        }
        StartCoroutine(CountOfPlayersLoop());
    }

    private static string GetFallbackBackendUrl()
    {
        // Reuse the SisterShip backend URL when the Inspector field is blank, so
        // the tracker only needs configuring in one place.
        // The original script reflected on a "MetaAttestationv2" type that does
        // not exist in this project, so the fallback silently produced "" and
        // tracking never sent anything.
        try
        {
            if (SisterShip.SisterShipManager.Instance != null)
            {
                return SisterShip.SisterShipManager.Instance.BackendUrl ?? "";
            }
        }
        catch
        {
            // SisterShip not present; fall through to the empty result.
        }

        return "";
    }

    private IEnumerator CountOfPlayersLoop()
    {
        while (true)
        {
            yield return new WaitForSeconds(15f);
            if (!EnableTracking || string.IsNullOrEmpty(BackendBaseUrl)) continue;
            yield return StartCoroutine(ReportCountOfPlayers());
        }
    }

    private IEnumerator ReportCountOfPlayers()
    {
        int count = PhotonNetwork.IsConnected ? PhotonNetwork.CountOfPlayers : 0;
        if (count <= 0) yield break;

        Dictionary<string, object> payload = new Dictionary<string, object>
        {
            { "secret", TrackerSecret },
            { "count", count },
        };

        string url = BackendBaseUrl.TrimEnd('/') + "/api/online-count";
        string json = JsonMapper.ToJson(payload);

        using (UnityWebRequest request = new UnityWebRequest(url, "POST"))
        {
            byte[] body = System.Text.Encoding.UTF8.GetBytes(json);
            request.uploadHandler = new UploadHandlerRaw(body);
            request.downloadHandler = new DownloadHandlerBuffer();
            request.SetRequestHeader("Content-Type", "application/json");
            yield return request.SendWebRequest();

            if (request.result != UnityWebRequest.Result.Success)
            {
                Debug.LogWarning("[PlayerTracker] online-count send failed: " + request.error);
            }
        }
    }

    public override void OnJoinedRoom()
    {
        base.OnJoinedRoom();
        if (!EnableTracking) return;
        _roomJoinedAt = Time.realtimeSinceStartup;
        StartCoroutine(ReportJoinedRoomWhenReady());
    }

    private IEnumerator ReportJoinedRoomWhenReady()
    {
        float deadline = Time.realtimeSinceStartup + 2.5f;
        while (Time.realtimeSinceStartup < deadline
               && string.IsNullOrEmpty(GetGameMode()))
        {
            yield return null;
        }
        ReportEvent("joined_room", PhotonNetwork.LocalPlayer,
            PhotonNetwork.CurrentRoom?.Name ?? "lobby");
    }

    public override void OnLeftRoom()
    {
        base.OnLeftRoom();
        if (!EnableTracking) return;
        int secondsInLobby = 0;
        if (_roomJoinedAt > 0)
        {
            secondsInLobby = (int)(Time.realtimeSinceStartup - _roomJoinedAt);
        }
        ReportEvent("left_room", PhotonNetwork.LocalPlayer, "lobby", secondsInLobby);
    }

    public override void OnPlayerEnteredRoom(Player newPlayer)
    {
        base.OnPlayerEnteredRoom(newPlayer);
        if (!EnableTracking || newPlayer == null) return;
        if (newPlayer == PhotonNetwork.LocalPlayer) return;
        ReportEvent("player_joined", newPlayer,
            PhotonNetwork.CurrentRoom?.Name ?? "lobby");
    }

    public override void OnPlayerLeftRoom(Player otherPlayer)
    {
        base.OnPlayerLeftRoom(otherPlayer);
        if (!EnableTracking || otherPlayer == null) return;
        if (otherPlayer == PhotonNetwork.LocalPlayer) return;
        ReportEvent("player_left", otherPlayer,
            PhotonNetwork.CurrentRoom?.Name ?? "lobby");
    }

    public void ReportEvent(string eventType, Player player, string room,
        int secondsInLobby = -1)
    {
        if (player == null) return;

        string playerName = player.NickName;
        string playFabId = GetPlayFabId(player);

        string cooldownKey = playFabId ?? player.UserId ?? playerName;
        if (cooldownKey != null)
        {
            if (_lastSentAt.TryGetValue(cooldownKey, out float last)
                && Time.realtimeSinceStartup - last < MinReportIntervalSeconds)
            {
                return;
            }
            _lastSentAt[cooldownKey] = Time.realtimeSinceStartup;
        }

        int playerCount = PhotonNetwork.CurrentRoom?.PlayerCount ?? 0;
        int maxPlayers = PhotonNetwork.CurrentRoom?.MaxPlayers ?? 10;

        StartCoroutine(SendEvent(eventType, room, playerName, playFabId,
            playerCount, maxPlayers, secondsInLobby));
    }

    private static string GetPlayFabId(Player player)
    {
        if (player == PhotonNetwork.LocalPlayer
            && PlayFabAuthenticator.instance != null
            && !string.IsNullOrEmpty(PlayFabAuthenticator.instance._playFabPlayerIdCache))
        {
            return PlayFabAuthenticator.instance._playFabPlayerIdCache;
        }
        string userId = player.UserId;
        if (!string.IsNullOrEmpty(userId) && IsLikelyPlayFabId(userId))
        {
            return userId;
        }
        return null;
    }

    private static bool IsLikelyPlayFabId(string id)
    {
        if (string.IsNullOrEmpty(id) || id.Length > 32) return false;
        foreach (char c in id)
        {
            bool isHex = (c >= '0' && c <= '9')
                || (c >= 'a' && c <= 'f')
                || (c >= 'A' && c <= 'F');
            if (!isHex) return false;
        }
        return id.Length >= 12;
    }

    private IEnumerator SendEvent(string eventType, string room, string playerName,
        string playFabId, int playerCount, int maxPlayers, int secondsInLobby)
    {
        if (string.IsNullOrEmpty(TrackerSecret) || string.IsNullOrEmpty(BackendBaseUrl))
        {
            yield break;
        }

        Dictionary<string, object> payload = new Dictionary<string, object>
        {
            { "secret", TrackerSecret },
            { "event", eventType },
            { "room", room ?? "" },
            { "player_name", playerName ?? "" },
            { "playfab_id", playFabId ?? "" },
            { "player_count", playerCount },
            { "max_players", maxPlayers },
            { "game_mode", GetGameMode() },
            { "scene", SceneManager.GetActiveScene().name },
            { "region", PhotonNetwork.CloudRegion ?? "" },
            { "platform", GetPlatform() },
            { "players", GetRoomPlayerNames() },
            { "seconds_in_lobby", secondsInLobby },
        };

        string url = BackendBaseUrl.TrimEnd('/') + "/api/tracker";
        string json = JsonMapper.ToJson(payload);

        using (UnityWebRequest request = new UnityWebRequest(url, "POST"))
        {
            byte[] body = System.Text.Encoding.UTF8.GetBytes(json);
            request.uploadHandler = new UploadHandlerRaw(body);
            request.downloadHandler = new DownloadHandlerBuffer();
            request.SetRequestHeader("Content-Type", "application/json");
            yield return request.SendWebRequest();

            if (request.result == UnityWebRequest.Result.Success)
            {
                Debug.Log("[PlayerTracker] sent " + eventType + " for " + playerName);
            }
            else
            {
                Debug.LogWarning("[PlayerTracker] send failed: " + request.error);
            }
        }
    }

    private string GetGameMode()
    {
        if (PhotonNetwork.CurrentRoom != null
            && PhotonNetwork.CurrentRoom.CustomProperties.TryGetValue("gameMode", out object mode)
            && mode != null)
        {
            string raw = mode.ToString();
            if (!string.IsNullOrEmpty(raw))
            {
                _lastGameMode = raw;
            }
            return raw;
        }
        return _lastGameMode;
    }

    private static string GetPlatform()
    {
        switch (Application.platform)
        {
            case RuntimePlatform.Android:
                return "Quest";
            case RuntimePlatform.WindowsPlayer:
            case RuntimePlatform.OSXPlayer:
            case RuntimePlatform.LinuxPlayer:
                return "PC";
            case RuntimePlatform.WindowsEditor:
            case RuntimePlatform.OSXEditor:
            case RuntimePlatform.LinuxEditor:
                return "Editor";
            default:
                return "Unknown";
        }
    }

    private static List<string> GetRoomPlayerNames()
    {
        List<string> names = new List<string>();
        if (PhotonNetwork.CurrentRoom == null) return names;
        foreach (Player p in PhotonNetwork.CurrentRoom.Players.Values)
        {
            if (p == null || string.IsNullOrEmpty(p.NickName)) continue;
            names.Add(p.NickName);
        }
        return names;
    }
}