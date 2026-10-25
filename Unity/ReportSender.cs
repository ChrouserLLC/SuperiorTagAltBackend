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
using VoicePatrol.Scripts.VoicePatrol.Scripts.Runtime;

/// <summary>
/// Sends in-game reports to the Superior Tag Alt backend and carries out
/// insta-ban kicks.
///
/// TRUST MODEL
///   * The reporter is identified by their PlayFab SESSION TICKET, which the
///     backend checks with PlayFab. The PlayFab IDs in the request body are
///     informational only; the backend never authorises anything from them.
///   * The kick broadcast (Photon event 99) is only a HINT. Any client can raise
///     a Photon event, so receiving one proves nothing. Before acting, the
///     receiver asks the backend (which asks PlayFab) whether the player really
///     is banned. A forged event therefore cannot kick anyone.
///   * ReportSecret is an app key that ships in the APK. It is not a secret and
///     guards nothing important; admin endpoints use a separate server-only key.
/// </summary>
public class ReportSender : MonoBehaviourPunCallbacks, IOnEventCallback
{
    public static ReportSender instance;
    public static bool SuppressSceneDestruction;

    // Default backend. This component builds itself through EnsureCreated(), so
    // there is usually no scene object to set these on and they would otherwise
    // stay blank and drop every report. Both can still be overridden in the
    // Inspector if you place one in a scene.
    public string BackendBaseUrl = "https://superiortagaltbackend.vercel.app/";

    // App key, NOT a credential: anyone can read it out of the APK. It must match
    // API_SECRET on the backend. Real authority comes from the session ticket.
    public string ReportSecret = "vqeQrzStXB1U7wpojlC8Yaewmsae6YAcs3nEXfHFUJt0co1176gPQddh4qAwdqDA";
    public bool EnableReports = true;
    public float MinReportIntervalSeconds = 15f;
    public float GlobalCooldownSeconds = 5f;

    [Tooltip("Ignore repeat kick hints for the same player for this long, so a " +
             "client spamming event 99 cannot make everyone hammer the backend.")]
    public float KickHintCooldownSeconds = 10f;

    private const byte InstaBanKickEventCode = 99;
    private const string GameName = "SUPERIOR TAG";

    private readonly Dictionary<string, float> _lastSentAt = new Dictionary<string, float>();
    private readonly Dictionary<string, float> _lastKickHintAt = new Dictionary<string, float>();
    private readonly HashSet<string> _banChecksInFlight = new HashSet<string>();
    private float _lastGlobalSentAt;
    private bool _kickHandled;

    public static void EnsureCreated()
    {
        if (instance != null) return;
        GameObject go = new GameObject("ReportSender");
        go.AddComponent<ReportSender>();
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
            Debug.LogError("[ReportSender] BackendBaseUrl is empty. Set it on the " +
                "ReportSender component to the Superior Tag Alt backend (the Vercel " +
                "URL). Reports are disabled until you do. Note this is NOT the SisterShip " +
                "backend, which serves /api/v1/* and has no /api/report route.");
        }
        if (string.IsNullOrEmpty(ReportSecret))
        {
            Debug.LogError("[ReportSender] ReportSecret is empty. Set it on the " +
                "ReportSender component to the same value as the API_SECRET " +
                "environment variable on the backend.");
        }
    }

    // ------------------------------------------------------------------
    // Kick hints
    // ------------------------------------------------------------------

    void IOnEventCallback.OnEvent(EventData photonEvent)
    {
        if (photonEvent == null || photonEvent.Code != InstaBanKickEventCode) return;
        object[] content = photonEvent.CustomData as object[];
        if (content == null || content.Length < 1) return;

        int actorNumber;
        try
        {
            actorNumber = System.Convert.ToInt32(content[0]);
        }
        catch
        {
            return;
        }
        if (actorNumber < 0) return;

        // Hours, reason and the PlayFab ID in the event are deliberately ignored:
        // they are whatever the sender chose to put there. Only the backend's
        // answer decides whether anyone is banned, and for how long.
        Player local = PhotonNetwork.LocalPlayer;
        bool isMe = local != null && actorNumber == local.ActorNumber;

        if (isMe)
        {
            string myId = GetPlayFabId(local);
            if (string.IsNullOrEmpty(myId) || !TakeKickHint(myId)) return;
            StartCoroutine(VerifyBanThen(myId, true, null));
        }
        else if (PhotonNetwork.IsMasterClient)
        {
            Player target = FindPlayerByActor(actorNumber);
            if (target == null) return;

            // Resolve the ID from the target's own Photon identity (set by
            // PlayFab custom auth), never from the event payload. Otherwise a
            // forged event could name a banned ID next to an innocent actor.
            string targetId = GetPlayFabId(target);
            if (string.IsNullOrEmpty(targetId) || !TakeKickHint(targetId)) return;
            StartCoroutine(VerifyBanThen(targetId, false, target));
        }
    }

    /// <summary>Per-player throttle for kick hints. True if this one may proceed.</summary>
    private bool TakeKickHint(string playFabId)
    {
        if (_banChecksInFlight.Contains(playFabId)) return false;
        float now = Time.realtimeSinceStartup;
        if (_lastKickHintAt.TryGetValue(playFabId, out float last)
            && now - last < KickHintCooldownSeconds)
        {
            return false;
        }
        _lastKickHintAt[playFabId] = now;
        return true;
    }

    /// <summary>
    /// Asks the backend whether <paramref name="playFabId"/> is really banned and
    /// only then acts. Any failure (no session, network, backend error) means
    /// "do nothing": a kick is never carried out on an unverified claim.
    /// </summary>
    private IEnumerator VerifyBanThen(string playFabId, bool isSelf, Player target)
    {
        _banChecksInFlight.Add(playFabId);
        try
        {
            string ticket = GetSessionTicket();
            if (string.IsNullOrEmpty(ticket) || string.IsNullOrEmpty(BackendBaseUrl)
                || string.IsNullOrEmpty(ReportSecret))
            {
                Debug.LogWarning("[ReportSender] kick hint ignored: cannot verify (no session or backend).");
                yield break;
            }

            Dictionary<string, object> payload = new Dictionary<string, object>
            {
                { "secret", ReportSecret },
                { "session_ticket", ticket },
                { "playfab_id", playFabId },
            };

            string url = BackendBaseUrl.TrimEnd('/') + "/api/ban-status";
            using (UnityWebRequest request = BuildJsonPost(url, JsonMapper.ToJson(payload)))
            {
                yield return request.SendWebRequest();

                if (request.result != UnityWebRequest.Result.Success)
                {
                    Debug.LogWarning("[ReportSender] ban check failed (" + request.error
                        + "); kick hint ignored.");
                    yield break;
                }

                bool banned;
                int hours;
                bool permanent;
                string reason;
                if (!TryParseBanStatus(request.downloadHandler.text, playFabId,
                        out banned, out hours, out permanent, out reason))
                {
                    Debug.LogWarning("[ReportSender] ban check returned an unexpected body; kick hint ignored.");
                    yield break;
                }

                if (!banned)
                {
                    Debug.LogWarning("[ReportSender] kick hint for a player who is NOT banned - ignored"
                        + (isSelf ? " (someone tried to kick you)." : "."));
                    yield break;
                }

                if (isSelf)
                {
                    LocalBanKick(hours, permanent, reason);
                }
                else if (PhotonNetwork.IsMasterClient && target != null
                         && FindPlayerByActor(target.ActorNumber) != null)
                {
                    Debug.Log("[ReportSender] verified ban for actor " + target.ActorNumber
                        + " - closing their connection.");
                    PhotonNetwork.CloseConnection(target);
                }
            }
        }
        finally
        {
            _banChecksInFlight.Remove(playFabId);
        }
    }

    private static bool TryParseBanStatus(string json, string expectedId, out bool banned,
        out int hours, out bool permanent, out string reason)
    {
        banned = false;
        hours = 0;
        permanent = false;
        reason = "";
        try
        {
            JsonData root = JsonMapper.ToObject(json);
            if (!GetBool(JsonDictGet(root, "success"))) return false;

            // The answer must be about the player we asked about.
            JsonData id = JsonDictGet(root, "playfab_id");
            if (id == null || !id.IsString || (string)id != expectedId) return false;

            banned = GetBool(JsonDictGet(root, "banned"));
            permanent = GetBool(JsonDictGet(root, "permanent"));
            JsonData h = JsonDictGet(root, "hours");
            if (h != null && h.IsInt) hours = ((LitJson.IJsonWrapper)h).GetInt();
            else if (h != null && h.IsLong) hours = (int)((LitJson.IJsonWrapper)h).GetLong();
            JsonData r = JsonDictGet(root, "reason");
            if (r != null && r.IsString) reason = (string)r;
            return true;
        }
        catch (System.Exception e)
        {
            Debug.LogWarning("[ReportSender] ban-status parse failed: " + e.Message);
            return false;
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

    private void LocalBanKick(int hours, bool permanent, string reason)
    {
        if (_kickHandled) return;
        _kickHandled = true;

        string duration = permanent ? "PERMANENTLY" : "FOR " + Mathf.Max(1, hours) + " HOURS";
        string message = "YOUR ACCOUNT HAS BEEN BANNED FROM " + GameName + " " + duration + ".\nREASON: "
            + (string.IsNullOrEmpty(reason) ? "BANNED ACCOUNT" : reason.ToUpperInvariant());
        Debug.LogWarning("[ReportSender] verified ban, disconnecting: " + message);

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

    // ------------------------------------------------------------------
    // Reports
    // ------------------------------------------------------------------

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
        if (reporter != null && reportedPlayer.ActorNumber == reporter.ActorNumber) return;

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

        SubmitVoiceEvidence(reportedId, reason);

        StartCoroutine(PostReport(reason, reporterName, reporterId,
            reportedName, reportedId, reportedPlayer.ActorNumber));
    }

    /// <summary>
    /// Attaches VoicePatrol's rolling audio buffer to the report so the moderation
    /// team gets the last ~2 minutes of what the reporter actually heard.
    ///
    /// The offender ID is resolved from the networked Player object above (the same
    /// PlayFab ID VoicePatrol was initialised with on that client's own device), so it
    /// is not attacker-supplied text. The existing PlayFab ban chain stays authoritative;
    /// this only supplies audio evidence alongside it.
    /// </summary>
    private static void SubmitVoiceEvidence(string reportedId, string reason)
    {
        try
        {
            if (string.IsNullOrEmpty(reportedId))
            {
                // Offender has no resolvable PlayFab ID, so there is no identity to tag
                // the evidence with. Skip rather than file an untagged clip.
                return;
            }

            if (!VoicePatrolWrapper.IsSdkRunning()) return;

            string result = VoicePatrolWrapper.SubmitPlayerReport(reportedId, reason);
            Debug.Log("[ReportSender] voice evidence: " + result);
        }
        catch (System.Exception e)
        {
            // Never let evidence submission block the actual report.
            Debug.LogWarning("[ReportSender] voice evidence failed: " + e.Message);
        }
    }

    private IEnumerator PostReport(string reason, string reporterName, string reporterId,
        string reportedName, string reportedId, int reportedActorNumber)
    {
        if (string.IsNullOrEmpty(ReportSecret) || string.IsNullOrEmpty(BackendBaseUrl))
        {
            // Logged once per attempt rather than silently dropped - a blank
            // BackendBaseUrl used to be auto-filled with the SisterShip URL,
            // which 404s because that server has no /api/report route.
            Debug.LogWarning("[ReportSender] report dropped: BackendBaseUrl=\"" +
                (BackendBaseUrl ?? "") + "\" ReportSecret=\"" +
                (string.IsNullOrEmpty(ReportSecret) ? "<empty>" : "<set>") + "\"");
            yield break;
        }

        string ticket = GetSessionTicket();
        if (string.IsNullOrEmpty(ticket))
        {
            // Still sent, so moderators see it, but the backend will mark it
            // unverified and it can never trigger an insta-ban.
            Debug.LogWarning("[ReportSender] no PlayFab session ticket yet; report will be unverified.");
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
            { "session_ticket", ticket ?? "" },
            { "reason", reason },
            { "room_code", roomCode ?? "" },
            { "is_private", isPrivate },
            { "room_count", roomCount },
            { "game_mode", GetGameMode() ?? "" },
            { "scene", SceneManager.GetActiveScene().name ?? "" },
            { "zone", GetZoneName() ?? "" },
            { "reporter_name", reporterName ?? "" },
            // Informational only. The backend derives the reporter from the ticket.
            { "reporter_id", reporterId ?? "" },
            { "reported_name", reportedName ?? "" },
            { "reported_id", reportedId ?? "" },
        };

        using (UnityWebRequest request = BuildJsonPost(url, JsonMapper.ToJson(payload)))
        {
            yield return request.SendWebRequest();

            if (request.result == UnityWebRequest.Result.Success)
            {
                Debug.Log("[ReportSender] sent " + reason + " report against "
                    + reportedName + " (" + reportedId + ")");
                BroadcastKickHintIfBanned(request.downloadHandler.text, reportedActorNumber);
            }
            else
            {
                Debug.LogWarning("[ReportSender] send failed: " + request.error
                    + " body=" + request.downloadHandler.text);
            }
        }
    }

    /// <summary>
    /// After a report that produced a ban, tell the room so the banned player
    /// (and the master client) can go and check. The event carries only the
    /// actor number; receivers verify with the backend before doing anything.
    /// </summary>
    private void BroadcastKickHintIfBanned(string responseJson, int reportedActorNumber)
    {
        if (reportedActorNumber < 0) return;
        try
        {
            JsonData root = JsonMapper.ToObject(responseJson);
            JsonData instaban = JsonDictGet(root, "instaban");
            if (instaban == null || !GetBool(JsonDictGet(instaban, "banned"))) return;

            object[] content = { reportedActorNumber };
            PhotonNetwork.RaiseEvent(InstaBanKickEventCode, content,
                new RaiseEventOptions { Receivers = ReceiverGroup.All },
                SendOptions.SendReliable);
            Debug.Log("[ReportSender] InstaBan hit on actor " + reportedActorNumber
                + " - kick hint sent");
        }
        catch (System.Exception e)
        {
            Debug.LogWarning("[ReportSender] instaban response parse failed: " + e.Message);
        }
    }

    // ------------------------------------------------------------------
    // Helpers
    // ------------------------------------------------------------------

    private static UnityWebRequest BuildJsonPost(string url, string json)
    {
        UnityWebRequest request = new UnityWebRequest(url, "POST");
        request.uploadHandler = new UploadHandlerRaw(System.Text.Encoding.UTF8.GetBytes(json));
        request.downloadHandler = new DownloadHandlerBuffer();
        request.SetRequestHeader("Content-Type", "application/json");
        request.timeout = 15;
        return request;
    }

    private static string GetSessionTicket()
    {
        PlayFabAuthenticator auth = PlayFabAuthenticator.instance;
        return auth != null ? auth.SessionTicket : null;
    }

    // NOTE: fully qualify LitJson.IJsonWrapper. This project also has a
    // global-namespace dummy `IJsonWrapper : MonoBehaviour` left behind by
    // AssetRipper, which an unqualified name would bind to instead.
    private static bool GetBool(JsonData data)
    {
        return data != null && data.IsBoolean && ((LitJson.IJsonWrapper)data).GetBoolean();
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
