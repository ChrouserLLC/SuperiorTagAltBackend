using System.Collections;
using System.Collections.Generic;
using ExitGames.Client.Photon;
using GorillaNetworking;
using LitJson;
using Photon.Pun;
using Photon.Realtime;
using UnityEngine;
using UnityEngine.Networking;
using UnityEngine.SceneManagement;

public class ReportSender : MonoBehaviourPunCallbacks, IOnEventCallback
{
    public static ReportSender instance;
    public static bool SuppressSceneDestruction;

    public string BackendBaseUrl = "";
    public string ReportSecret = "";
    public bool EnableReports = true;
    public float MinReportIntervalSeconds = 15f;
    public float GlobalCooldownSeconds = 5f;

    private const byte InstaBanKickEventCode = 99;
    private readonly Dictionary<string, float> _lastSentAt = new Dictionary<string, float>();
    private float _lastGlobalSentAt;
    private bool _kickHandled;

    public static void EnsureCreated()
    {
        if (instance != null) return;
        GameObject go = new GameObject("ReportSender");
        ReportSender sender = go.AddComponent<ReportSender>();
        if (string.IsNullOrEmpty(sender.BackendBaseUrl))
        {
            sender.BackendBaseUrl = GetFallbackBackendUrl();
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
    }

    private static string GetFallbackBackendUrl()
    {
        // Reuse the SisterShip backend URL when the Inspector field is blank, so
        // the whole integration is configured in one place.
        // The original reflected on a "MetaAttestationv2" type that does not
        // exist in this project, so this silently returned "" and nothing was
        // ever reported.
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

    void IOnEventCallback.OnEvent(EventData photonEvent)
    {
        if (photonEvent == null || photonEvent.Code != InstaBanKickEventCode) return;
        object[] content = photonEvent.CustomData as object[];
        if (content == null || content.Length < 3) return;

        int actorNumber = -1;
        int hours = 24;
        string reportedId = "";
        string reason = "";
        try
        {
            actorNumber = System.Convert.ToInt32(content[0]);
            if (content.Length >= 2 && content[1] != null) reportedId = content[1].ToString();
            if (content.Length >= 3 && content[2] != null) hours = System.Convert.ToInt32(content[2]);
            if (content.Length >= 4 && content[3] != null) reason = content[3].ToString();
        }
        catch
        {
            return;
        }

        Player local = PhotonNetwork.LocalPlayer;
        string localId = GetPlayFabId(local);
        bool isMe = actorNumber >= 0 && local != null && actorNumber == local.ActorNumber;
        if (!isMe && reportedId.Length > 0 && localId == reportedId)
        {
            isMe = true;
        }

        if (isMe)
        {
            LocalBanKick(hours, reason);
        }
        else if (PhotonNetwork.IsMasterClient)
        {
            Player target = FindPlayerByActor(actorNumber);
            if (target != null)
            {
                PhotonNetwork.CloseConnection(target);
            }
        }
    }

    private static Player FindPlayerByActor(int actorNumber)
    {
        if (actorNumber < 0) return null;
        foreach (Player player in PhotonNetwork.PlayerList)
        {
            if (player != null && player.ActorNumber == actorNumber) return player;
        }
        return null;
    }

    private void LocalBanKick(int hours, string reason)
    {
        if (_kickHandled) return;
        _kickHandled = true;

        string message = "YOUR ACCOUNT HAS BEEN BANNED FROM UNTITLED TAG FOR "
            + Mathf.Max(1, hours) + " HOURS.\nREASON: [InstaBan] "
            + (string.IsNullOrEmpty(reason) ? "BANNED ACCOUNT" : reason);
        Debug.LogWarning("[ReportSender] InstaBan kicked: " + message);

        SuppressSceneDestruction = true;
        if (GorillaComputer.instance != null)
        {
            GorillaComputer.instance.UpdateFailureText(message);
        }
        StartCoroutine(KickDisconnect());
    }

    private IEnumerator KickDisconnect()
    {
        bool disconnected = false;
        try
        {
            System.Type controllerType = null;
            foreach (System.Reflection.Assembly asm in System.AppDomain.CurrentDomain.GetAssemblies())
            {
                controllerType = asm.GetType("PhotonNetworkController");
                if (controllerType != null) break;
            }
            if (controllerType != null)
            {
                object controllerInstance = controllerType.GetField("Instance", System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.Static).GetValue(null);
                if (controllerInstance != null)
                {
                    System.Reflection.MethodInfo disco = controllerType.GetMethod("AttemptDisconnect");
                    if (disco != null)
                    {
                        disco.Invoke(controllerInstance, null);
                        disconnected = true;
                    }
                }
            }
        }
        catch { }
        if (!disconnected)
        {
            PhotonNetwork.Disconnect();
        }
        yield break;
    }

    public void SendReport(string reasonButton, Player reportedPlayer, string reportedNickName)
    {
        if (!EnableReports || reportedPlayer == null || string.IsNullOrEmpty(reasonButton)) return;

        string reason = NormalizeReason(reasonButton);
        if (reason == null)
        {
            Debug.LogWarning("[ReportSender] Unknown report reason: " + reasonButton);
            return;
        }

        Player reporter = PhotonNetwork.LocalPlayer;
        string reporterId = GetPlayFabId(reporter);
        string reporterName = reporter != null ? reporter.NickName : "";
        string reportedId = GetPlayFabId(reportedPlayer);
        string reportedName = !string.IsNullOrEmpty(reportedNickName) ? reportedNickName
            : (reportedPlayer != null ? reportedPlayer.NickName : "");

        float now = Time.realtimeSinceStartup;
        string dedupeKey = (reporterId ?? reporterName ?? "unknown") + "|"
            + (reportedId ?? reportedName ?? "unknown");
        if (_lastSentAt.TryGetValue(dedupeKey, out float last)
            && now - last < MinReportIntervalSeconds)
        {
            return;
        }
        if (now - _lastGlobalSentAt < GlobalCooldownSeconds)
        {
            return;
        }
        _lastSentAt[dedupeKey] = now;
        _lastGlobalSentAt = now;

        StartCoroutine(PostReport(reason, reporterName, reporterId,
            reportedName, reportedId, reportedPlayer.ActorNumber));
    }

    private IEnumerator PostReport(string reason, string reporterName, string reporterId,
        string reportedName, string reportedId, int reportedActorNumber)
    {
        if (string.IsNullOrEmpty(ReportSecret) || string.IsNullOrEmpty(BackendBaseUrl))
        {
            yield break;
        }

        string url = BackendBaseUrl.TrimEnd('/') + "/api/report";

        bool isPrivate = false;
        string roomCode;
        int roomCount = 0;
        if (PhotonNetwork.CurrentRoom != null)
        {
            isPrivate = !PhotonNetwork.CurrentRoom.IsVisible;
            roomCode = isPrivate ? "-PRIVATE-" : PhotonNetwork.CurrentRoom.Name;
            roomCount = PhotonNetwork.CurrentRoom.PlayerCount;
        }
        else
        {
            roomCode = "";
        }

        Dictionary<string, object> payload = new Dictionary<string, object>
        {
            { "secret", ReportSecret },
            { "reason", reason },
            { "room_code", roomCode ?? "" },
            { "is_private", isPrivate },
            { "room_count", roomCount },
            { "game_mode", GetGameMode() ?? "" },
            { "scene", SceneManager.GetActiveScene().name ?? "" },
            { "zone", GetZoneName() ?? "" },
            { "reporter_name", reporterName ?? "" },
            { "reporter_id", reporterId ?? "" },
            { "reported_name", reportedName ?? "" },
            { "reported_id", reportedId ?? "" },
        };

        string json = JsonMapper.ToJson(payload);

        using (UnityWebRequest request = new UnityWebRequest(url, "POST"))
        {
            byte[] body = System.Text.Encoding.UTF8.GetBytes(json);
            request.uploadHandler = new UploadHandlerRaw(body);
            request.downloadHandler = new DownloadHandlerBuffer();
            request.SetRequestHeader("Content-Type", "application/json");
            request.timeout = 15;
            yield return request.SendWebRequest();

            if (request.result == UnityWebRequest.Result.Success)
            {
                Debug.Log("[ReportSender] sent " + reason + " report against "
                    + reportedName + " (" + reportedId + ")");
                BroadcastInstaBanKickIfBanned(request.downloadHandler.text,
                    reportedActorNumber, reportedId, reason);
            }
            else
            {
                Debug.LogWarning("[ReportSender] send failed: " + request.error
                    + " body=" + request.downloadHandler.text);
            }
        }
    }

    private void BroadcastInstaBanKickIfBanned(string responseJson,
        int reportedActorNumber, string reportedId, string reason)
    {
        if (reportedActorNumber < 0) return;
        try
        {
            JsonData root = JsonMapper.ToObject(responseJson);
            JsonData instaban = JsonDictGet(root, "instaban");
            if (instaban == null) return;
            JsonData banned = JsonDictGet(instaban, "banned");
            // NOTE: fully qualify LitJson.IJsonWrapper. This project also has a
            // global-namespace dummy `IJsonWrapper : MonoBehaviour` left behind by
            // AssetRipper, which an unqualified name would bind to instead.
            if (banned == null || !banned.IsBoolean
                || !((LitJson.IJsonWrapper)banned).GetBoolean()) return;

            int hours = 24;
            JsonData hoursData = JsonDictGet(instaban, "hours");
            if (hoursData != null && (hoursData.IsInt || hoursData.IsLong))
            {
                hours = hoursData.IsLong
                    ? (int)((LitJson.IJsonWrapper)hoursData).GetLong()
                    : ((LitJson.IJsonWrapper)hoursData).GetInt();
            }
            object[] content = { reportedActorNumber, reportedId ?? "", hours, reason ?? "" };
            PhotonNetwork.RaiseEvent(InstaBanKickEventCode, content,
                new RaiseEventOptions { Receivers = ReceiverGroup.All },
                SendOptions.SendReliable);
            Debug.Log("[ReportSender] InstaBan hit on actor " + reportedActorNumber
                + " (" + reportedId + ") - kick broadcast sent");
        }
        catch (System.Exception e)
        {
            Debug.LogWarning("[ReportSender] instaban response parse failed: " + e.Message);
        }
    }

    private static JsonData JsonDictGet(JsonData obj, string key)
    {
        if (obj == null || !obj.IsObject) return null;
        IDictionary dict = obj;
        if (dict == null || !dict.Contains(key)) return null;
        return dict[key] as JsonData;
    }

    private static string NormalizeReason(string buttonType)
    {
        if (string.IsNullOrEmpty(buttonType)) return null;
        switch (buttonType)
        {
            case "Cheating": return "Cheating";
            case "Toxicity": return "Toxicity";
            case "HateSpeech": return "HateSpeech";
            case "Bullying": return "Bullying";
            case "Doxing": return "Doxing";
            case "Impersonation": return "Impersonation";
            default: return null;
        }
    }

    private static string GetGameMode()
    {
        try
        {
            System.Type ggmType = null;
            foreach (System.Reflection.Assembly asm in System.AppDomain.CurrentDomain.GetAssemblies())
            {
                ggmType = asm.GetType("GorillaGameManager");
                if (ggmType != null) break;
            }
            if (ggmType != null)
            {
                object ggm = ggmType.GetField("instance", System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.Static).GetValue(null);
                if (ggm != null)
                {
                    System.Reflection.MethodInfo modeGetter = ggmType.GetMethod("GameMode");
                    if (modeGetter != null)
                    {
                        object modeValue = modeGetter.Invoke(ggm, null);
                        if (modeValue != null && !string.IsNullOrEmpty(modeValue.ToString())) return modeValue.ToString();
                    }
                }
            }
        }
        catch { }
        if (PhotonNetwork.CurrentRoom != null
            && PhotonNetwork.CurrentRoom.CustomProperties.TryGetValue("gameMode", out object modeObj)
            && modeObj != null)
        {
            return modeObj.ToString();
        }
        return "";
    }

    private static string GetZoneName()
    {
        if (PhotonNetwork.CurrentRoom == null
            || !PhotonNetwork.CurrentRoom.CustomProperties.TryGetValue("gameMode", out object modeObj)
            || modeObj == null)
        {
            return null;
        }
        string gameMode = modeObj.ToString();
        string[] mapNames = new string[]
        {
            "skyjungle", "cave", "canyon", "city", "mountain",
            "basement", "beach", "forest", "clouds", "ball"
        };
        foreach (string map in mapNames)
        {
            if (gameMode.StartsWith(map, System.StringComparison.OrdinalIgnoreCase))
            {
                return map;
            }
        }
        return null;
    }

    private static string GetPlayFabId(Player player)
    {
        if (player == null) return null;
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
}