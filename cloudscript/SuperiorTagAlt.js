/**
 * Superior Tag Alt - PlayFab CloudScript
 *
 * Merge of the original Tracker.js and instaban.js.
 *
 *   InstaBanReport      - bans a reported player, but ONLY when the reporter
 *                         is on the allowlist below. The allowlist is the
 *                         authorisation boundary: without it, any client
 *                         could ban anyone.
 *   GetTrackedPlayers   - returns the role lists
 *   SetTrackedPlayer    - add/update a role (admins only)
 *   RemoveTrackedPlayer - remove a role (admins only)
 *   GetTrackerAdmins    - list admins
 *   SetTrackerAdmin     - grant/revoke admin (master admin only)
 *
 * Deploy: PlayFab Dashboard -> Automation -> CloudScript -> upload this file.
 */

var CONFIG = {
    TitleDataKey: "TrackedPlayers",
    AdminKey: "TrackerAdmins",
    MasterAdminKey: "MasterAdminId",
    MaxTracked: 500
};

// ---------------------------------------------------------------------------
// Insta-ban
// ---------------------------------------------------------------------------

// REPLACE THESE with the PlayFab IDs allowed to use insta-ban.
var INSTABAN_REPORTERS = ["YOUR_PLAYFAB_ID"];
var INSTABAN_HOURS = 24;

function canInstaBan(playerId) {
    return INSTABAN_REPORTERS.indexOf(playerId) !== -1;
}

handlers.InstaBanReport = function (args) {
    // The reporter is ALWAYS the player this CloudScript runs as. Never take it
    // from args: CloudScript handlers can be called straight from any game
    // client (Client/ExecuteCloudScript), so an args value is attacker-chosen -
    // anyone could pass a moderator's PlayFab ID and ban whoever they like.
    // currentPlayerId is set by PlayFab from the caller's own session (or, for
    // the backend's Server/ExecuteCloudScript call, from the PlayFab ID the
    // backend verified from the reporter's session ticket).
    var reporterId = currentPlayerId;
    var reportedId = args && args.reportedPlayFabId;
    var reason = String((args && args.reason) || "").substring(0, 64);

    if (!reportedId) {
        return { success: false, banned: false, reason: "reportedPlayFabId required" };
    }
    if (!reporterId) {
        return { success: false, banned: false, reason: "no calling player" };
    }
    if (args && args.reporterPlayFabId && args.reporterPlayFabId !== reporterId) {
        return { success: false, banned: false, reason: "reporter_mismatch" };
    }
    if (reportedId === reporterId) {
        return { success: false, banned: false, reason: "cannot_ban_self" };
    }
    // Authorisation lives here, not in the Flask layer.
    if (!canInstaBan(reporterId)) {
        return { success: false, banned: false, reason: "reporter_not_authorized" };
    }
    // Staff cannot insta-ban other insta-ban staff.
    if (canInstaBan(reportedId)) {
        return { success: false, banned: false, reason: "target_is_staff" };
    }

    try {
        var ban = server.BanUsers({
            Bans: [{
                PlayFabId: reportedId,
                Reason: "[InstaBan] by " + reporterId + " for: " + reason,
                DurationInHours: INSTABAN_HOURS
            }]
        });
        var banIds = ban.Data && ban.Data.BanIds;
        return {
            success: true,
            banned: true,
            reason: "instaban",
            banId: banIds && banIds.length > 0 ? banIds[0] : null,
            bannedPlayFabId: reportedId,
            hours: INSTABAN_HOURS
        };
    } catch (e) {
        return { success: false, banned: false, reason: "ban_failed", message: String(e) };
    }
};

// ---------------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------------

function getTitleDataJson(key) {
    var result = server.GetTitleData({ Key: key });
    var value = result.Data && result.Data.Value ? result.Data.Value : "";
    if (!value) return null;
    try {
        return JSON.parse(value);
    } catch (e) {
        return null;
    }
}

function getTitleDataRaw(key) {
    var result = server.GetTitleData({ Key: key });
    return result.Data && result.Data.Value ? result.Data.Value : "";
}

function getMasterAdminIds() {
    var value = getTitleDataRaw(CONFIG.MasterAdminKey).trim();
    if (!value) return [];
    if (value.charAt(0) === "[") {
        try { return JSON.parse(value); } catch (e) { return []; }
    }
    if (value.charAt(0) === "{") {
        try {
            var obj = JSON.parse(value);
            return obj && obj.id ? [obj.id] : [];
        } catch (e) { return []; }
    }
    return [value];
}

function isMasterAdmin(playerId) {
    return getMasterAdminIds().indexOf(playerId) !== -1;
}

function isAdmin(playerId) {
    if (isMasterAdmin(playerId)) return true;
    var admins = getTitleDataJson(CONFIG.AdminKey) || [];
    return admins.indexOf(playerId) !== -1;
}

function getDisplayName(playFabId) {
    try {
        var info = server.GetUserAccountInfo({ PlayFabId: playFabId });
        var name = info.Data.UserInfo.TitleInfo.DisplayName;
        if (name) return name;
    } catch (e) { }
    return playFabId;
}

function setTitleDataJson(key, obj) {
    server.SetTitleData({ Key: key, Value: JSON.stringify(obj) });
}

function getEmptyList() {
    return { content_creators: [], moderators: [], admins: [], owners: [] };
}

function normaliseList(data) {
    data = data || getEmptyList();
    if (!data.content_creators) data.content_creators = [];
    if (!data.moderators) data.moderators = [];
    if (!data.admins) data.admins = [];
    if (!data.owners) data.owners = [];
    return data;
}

// ---------------------------------------------------------------------------
// Tracked player roles
// ---------------------------------------------------------------------------

handlers.GetTrackedPlayers = function (args) {
    var data = getTitleDataJson(CONFIG.TitleDataKey);
    if (!data) {
        data = getEmptyList();
        setTitleDataJson(CONFIG.TitleDataKey, data);
    }
    return normaliseList(data);
};

handlers.SetTrackedPlayer = function (args) {
    if (!isAdmin(currentPlayerId)) throw "Not authorized - only tracker admins can add players";

    var playFabId = args.playFabId;
    var role = args.role;
    if (!playFabId) throw "playFabId is required";
    if (["content_creator", "moderator", "admin", "owner"].indexOf(role) === -1) {
        throw "role must be content_creator, moderator, admin or owner";
    }

    var data = normaliseList(getTitleDataJson(CONFIG.TitleDataKey));

    // A player holds exactly one role: clear the others first.
    var otherRoles = ["content_creator", "moderator", "admin", "owner"]
        .filter(function (r) { return r !== role; });
    for (var i = 0; i < otherRoles.length; i++) {
        data[otherRoles[i] + "s"] = data[otherRoles[i] + "s"]
            .filter(function (p) { return p.playFabId !== playFabId; });
    }

    var list = data[role + "s"];
    var existing = list.filter(function (p) { return p.playFabId === playFabId; });
    if (existing.length === 0) {
        var total = data.content_creators.length + data.moderators.length
            + data.admins.length + data.owners.length;
        if (total >= CONFIG.MaxTracked) {
            throw "Tracked player limit of " + CONFIG.MaxTracked + " reached";
        }
        list.push({ playFabId: playFabId, displayName: getDisplayName(playFabId) });
    } else {
        existing[0].displayName = getDisplayName(playFabId);
    }

    setTitleDataJson(CONFIG.TitleDataKey, data);
    return { success: true, role: role, playFabId: playFabId, tracked: data };
};

handlers.RemoveTrackedPlayer = function (args) {
    if (!isAdmin(currentPlayerId)) throw "Not authorized - only tracker admins can remove players";

    var playFabId = args.playFabId;
    if (!playFabId) throw "playFabId is required";

    var data = normaliseList(getTitleDataJson(CONFIG.TitleDataKey));
    var removed = false;
    var allKeys = ["content_creators", "moderators", "admins", "owners"];
    for (var i = 0; i < allKeys.length; i++) {
        data[allKeys[i]] = data[allKeys[i]].filter(function (p) {
            if (p.playFabId === playFabId) { removed = true; return false; }
            return true;
        });
    }

    setTitleDataJson(CONFIG.TitleDataKey, data);
    return { success: removed, playFabId: playFabId, tracked: data };
};

// ---------------------------------------------------------------------------
// Admin management
// ---------------------------------------------------------------------------

handlers.GetTrackerAdmins = function (args) {
    var admins = getTitleDataJson(CONFIG.AdminKey) || [];
    var master = getTitleDataJson(CONFIG.MasterAdminKey);
    if (typeof master === "string") master = { id: master };
    return { admins: admins, master_admin: master ? master.id : null };
};

handlers.SetTrackerAdmin = function (args) {
    if (!isMasterAdmin(currentPlayerId)) throw "Not authorized - only the master admin can manage admins";

    var playFabId = args.playFabId;
    if (!playFabId) throw "playFabId is required";

    var admins = getTitleDataJson(CONFIG.AdminKey) || [];
    var idx = admins.indexOf(playFabId);
    if (args.isAdmin && idx === -1) {
        admins.push(playFabId);
    } else if (!args.isAdmin && idx !== -1) {
        admins.splice(idx, 1);
    }
    setTitleDataJson(CONFIG.AdminKey, admins);
    return { success: true, admins: admins };
};
