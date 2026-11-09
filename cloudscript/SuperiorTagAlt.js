// start of version
// start of cosmetics
// start of instaban
// start of player tracker
// start of staff / mod checker
// start of live events
// start of clawd event
// start of meteor event
// start of blood moon event
// start of badges and name colors

// start of version

handlers.ReturnCurrentVersionNew = function(args) {
    return {
        "ResultCode": 0,
        "BannedUsers": "1",
        "MOTD": "<color=#BF40BF>WELCOME TO PROJECTTWITCH!</color>\n\n<color=#0099c2>CURRENT UPDATE: HALLOWEEN 2023</color>\n<color=#cacfd2>Boost now for exclusive TUFF COSMETICS! (HAWK TUAH!)</color>\n<color=#41ff80>FOUNDER: FATAL</color>\n<color=#6417ff>CO-FOUNDERS: SAMMY, LUNAR,</color>\n<color=#ac1a00>CREDITS: SAMMY</color>\n\n<color=#91A3B0>discord.gg/projecttwitch</color>",
        "SynchTime": "Winter",
        "Version": "Winter",
        "Message": "Winter"
    };
};

// end of version

// start of cosmetics

handlers.getVRRigData = function (args, context) {
    var VRRigData = {
        allcosmetics: "Early Access Supporter PackLBAAA.LBAAB.LBAAC.LBAAD.LBAAF.LBAAG.LBAAH.LBAAI.LBAAJ.LFAAA.LFAAB.LFAAC.LFAAD.LFAAE.LFAAF.LFAAG.LFAAH.LFAAI.LFAAJ.LFAAK.LFAAL.LFAAM.LFAAN.LFAAO.LHAAA.LHAAB.LHAAC.LHAAD.LHAAE.LHAAF.LHAAH.LHAAI.LHAAJ.LHAAK.LHAAL.LHAAM.LHAAN.LHAAO.LHAAP.LHAAQ.LHAAR.LHAAS.FIRST LOGINLHAAG.LBAAE.LBAAK.LHAAT.LHAAU.LHAAV.LHAAW.LHAAX.LHAAY.LHAAZ.LFAAP.LFAAQ.LFAAR.LFAAS.LFAAT.LFAAU.LBAAL.LBAAM.LBAAN.LBAAO.LSAAA.LSAAB.LSAAC.LSAAD.LHABA.LHABB.LHABC.LFAAV.LFAAW.LBAAP.LBAAQ.LBAAR.LBAAS.LFAAX.LFAAY.LFAAZ.LFABA.LHABD.LHABE.LHABF.LHABG.LSAAE.LFABB.LFABC.LHABH.LHABI.LHABJ.LHABK.LHABL.LHABM.LHABN.LHABO.LBAAT.LHABP.LHABQ.LHABR.LFABD.LBAAU.LBAAV.LBAAW.LBAAX.LBAAY.LBAAZ.LBABA.LBABB.LBABC.LBABD.LBABE.LFABE.LHABS.LHABT.LHABU.LHABV.LFABF.LFABG.LBABF.LBABG.LHABW.LBABH.LHABX.LHABY.LMAAA.LMAAB.LHABZ.LHACA.LBABJ.LBABK.LBABL.LMAAC.LMAAD.LMAAE.LBABI.LMAAF.LMAAG.LMAAH.LFABH.LHACB.LHACC.LFABI.LBABM.LBABN.LHACD.LMAAI.LMAAJ.LMAAK.LMAAL.LMAAM.LMAAN.LMAAO.LHACE.LFABJ.LFABK.LFABL.LFABM.LFABN.LFABO.LBABO.LBABP.CORN ON THE COBCRANBERRY CANFRYING PANLBACA.LBACB.LBACC.LBACD.LBACE.LBACF.LBACG.LBACH.LBADG.LBAFD.LBAFL.LBAFV.LBAGB.LBAGC.LBAGH.LBAGJ.LBAGL.LBAGS.LBAHK.LBAJC.LBARF.LBARG.LBASH.LBATD.LBATH.LBATK.LBATY.LBAUF.LBAVG.LBAVH.LBAVJ.LBAVK.LFABP.LFABQ.LFABR.LFABI.LFABH.LFABG.LFABF.LFABE.LFABO.LFABN.LFABZ.LFACA.LHADD.LHADC.LHACH.LHACG.LHACF.LHACE.LHACD.LHACC.LHACB.LHACA.LHABZ.LHABY.LHABX.LHABW.LHADG.headmodelTURKEY TOYTURKEY LEG 22PIE SLICEPIE HATOVERRIDDENLMAAU.LMAAV.HIGH TECH SLINGSHOTFINGER FLAGSTICKABLE TARGETLMAAQ."
    };

    return VRRigData;
};

// end of cosmetics

// start of instaban

var INSTABAN_REPORTERS = ["C47D101DE0EBA7EE", "BBA61C3A92481AF4"];
var INSTABAN_HOURS = 24;

function canInstaBan(playerId) {
    return INSTABAN_REPORTERS.indexOf(playerId) !== -1;
}

handlers.InstaBanReport = function (args) {
    var reporterId = args && args.reporterPlayFabId;
    var reportedId = args && args.reportedPlayFabId;
    var reason = (args && args.reason) || "";

    if (!reportedId) {
        return { success: false, banned: false, reason: "reportedPlayFabId required" };
    }
    if (!reporterId) {
        return { success: false, banned: false, reason: "reporterPlayFabId required" };
    }
    if (!canInstaBan(reporterId)) {
        return { success: false, banned: false, reason: "reporter_not_authorized" };
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

// end of instaban

// start of player tracker

var CONFIG = {
    TitleDataKey: "TrackedPlayers",
    AdminKey: "TrackerAdmins",
    MasterAdminKey: "MasterAdminId",
    MaxTracked: 500
};

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
        if (name) return String(name).split("#")[0];
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

// end of player tracker

// start of staff / mod checker

var staffOwners = ["BBA61C3A92481AF4", "C47D101DE0EBA7EE"];
var staffAdmins = [];
var staffModerators = [];

var staffRanks = { Moderator: 1, Admin: 2, Owner: 3 };
var staffActionLifetime = 120000;
var staffMaxPlayerFlags = 25;
var staffMaxRecentFlags = 40;
var staffMaxAuditEntries = 100;

function getStaffRole(playFabId) {
    if (!playFabId) return null;
    if (staffOwners.indexOf(playFabId) !== -1) return "Owner";
    if (staffAdmins.indexOf(playFabId) !== -1) return "Admin";
    if (staffModerators.indexOf(playFabId) !== -1) return "Moderator";
    return null;
}

function getStaffRank(playFabId) {
    var role = getStaffRole(playFabId);
    return role ? staffRanks[role] : 0;
}

function hasStaffRole(minRole) {
    return getStaffRank(currentPlayerId) >= staffRanks[minRole];
}

function staffDenied() {
    return { ok: false, error: "not_authorized" };
}

function isValidPlayFabId(id) {
    return typeof id === "string" && /^[0-9A-F]{8,20}$/i.test(id);
}

function parseStaffJson(text, fallback) {
    if (!text) return fallback;
    try {
        return JSON.parse(text);
    } catch (e) {
        return fallback;
    }
}

function getStaffDisplayName(playFabId) {
    try {
        var info = server.GetUserAccountInfo({ PlayFabId: playFabId }).UserInfo;
        return (info && info.TitleInfo && info.TitleInfo.DisplayName) || "";
    } catch (e) {
        return "";
    }
}

function getStaffFlags(playFabId) {
    var data = server.GetUserInternalData({ PlayFabId: playFabId, Keys: ["StaffFlags"] }).Data || {};
    return parseStaffJson((data.StaffFlags || {}).Value, []);
}

function getStaffList(key) {
    var data = server.GetTitleInternalData({ Keys: [key] }).Data || {};
    return parseStaffJson(data[key], []);
}

function addToStaffList(key, entry, max) {
    var list = getStaffList(key);
    list.unshift(entry);
    if (list.length > max) list.length = max;
    server.SetTitleInternalData({ Key: key, Value: JSON.stringify(list) });
}

function writeStaffAudit(entry) {
    entry.at = Date.now();
    entry.by = currentPlayerId;
    addToStaffList("StaffAuditLog", entry, staffMaxAuditEntries);
}

handlers.StaffGetAccess = function (args, context) {
    var role = getStaffRole(currentPlayerId);
    if (!role) return { ok: true, isStaff: false };

    return {
        ok: true,
        isStaff: true,
        role: role,
        playFabId: currentPlayerId,
        displayName: getStaffDisplayName(currentPlayerId)
    };
};

handlers.StaffGetPlayerInfo = function (args, context) {
    if (!hasStaffRole("Moderator")) return staffDenied();

    var target = args && args.targetId;
    if (!isValidPlayFabId(target)) return { ok: false, error: "bad_target" };

    var result = {
        ok: true,
        playFabId: target,
        displayName: "",
        platform: "Unknown",
        created: "",
        lastLogin: "",
        activeBans: 0,
        flags: 0,
        staffRole: getStaffRole(target) || ""
    };

    try {
        var info = server.GetUserAccountInfo({ PlayFabId: target }).UserInfo || {};
        if (info.TitleInfo) {
            result.displayName = info.TitleInfo.DisplayName || "";
            result.created = info.TitleInfo.Created || "";
            result.lastLogin = info.TitleInfo.LastLogin || "";
        }
        if (info.SteamInfo) result.platform = "Steam";
        else if (info.AndroidDeviceInfo) result.platform = "Android / Quest";
        else if (info.IosDeviceInfo) result.platform = "iOS";
        else if (info.CustomIdInfo) result.platform = "Custom ID";
    } catch (e) {
        result.error = "account_lookup_failed";
    }

    try {
        var bans = server.GetUserBans({ PlayFabId: target }).BanData || [];
        for (var i = 0; i < bans.length; i++) {
            if (bans[i].Active) result.activeBans++;
        }
    } catch (e) { }

    result.flags = getStaffFlags(target).length;
    return result;
};

handlers.StaffCheckCosmetics = function (args, context) {
    if (!hasStaffRole("Moderator")) return staffDenied();

    var target = args && args.targetId;
    if (!isValidPlayFabId(target)) return { ok: false, error: "bad_target" };

    var worn = (args && args.worn) || [];
    if (worn.length > 40) worn = worn.slice(0, 40);

    var owned = { Slingshot: true };
    var inventory = server.GetUserInventory({ PlayFabId: target }).Inventory || [];
    for (var i = 0; i < inventory.length; i++) {
        owned[inventory[i].ItemId] = true;
    }

    var unowned = [];
    var checked = 0;
    for (var j = 0; j < worn.length; j++) {
        var item = worn[j];
        if (!item || item === "null" || item === "NOTHING") continue;
        checked++;
        if (!owned[item]) unowned.push(item);
    }

    return { ok: true, checked: checked, owned: inventory.length, unowned: unowned };
};

handlers.StaffFlagPlayer = function (args, context) {
    if (!hasStaffRole("Moderator")) return staffDenied();

    var target = args && args.targetId;
    if (!isValidPlayFabId(target)) return { ok: false, error: "bad_target" };

    var flag = {
        at: Date.now(),
        by: currentPlayerId,
        role: getStaffRole(currentPlayerId),
        reason: String((args && args.reason) || "Flagged by staff").substring(0, 80),
        target: target,
        name: String((args && args.targetName) || "").substring(0, 20)
    };

    var flags = getStaffFlags(target);
    flags.unshift(flag);
    if (flags.length > staffMaxPlayerFlags) flags.length = staffMaxPlayerFlags;
    server.UpdateUserInternalData({ PlayFabId: target, Data: { StaffFlags: JSON.stringify(flags) } });

    addToStaffList("StaffRecentFlags", flag, staffMaxRecentFlags);
    writeStaffAudit({ action: "flag", target: target, reason: flag.reason });

    return { ok: true, flags: flags.length };
};

handlers.StaffGetFlags = function (args, context) {
    if (!hasStaffRole("Moderator")) return staffDenied();

    var target = args && args.targetId;
    if (target) {
        if (!isValidPlayFabId(target)) return { ok: false, error: "bad_target" };
        return { ok: true, flags: getStaffFlags(target) };
    }

    return { ok: true, flags: getStaffList("StaffRecentFlags") };
};

handlers.StaffAction = function (args, context) {
    var action = args && args.action;
    var target = args && args.targetId;

    if (!isValidPlayFabId(target)) return { ok: false, error: "bad_target" };
    if (target === currentPlayerId) return { ok: false, error: "cannot_target_self" };

    var needed = { kick: "Moderator", bring: "Admin", ban: "Admin" }[action];
    if (!needed) return { ok: false, error: "bad_action" };
    if (!hasStaffRole(needed)) return staffDenied();
    if (getStaffRank(target) >= getStaffRank(currentPlayerId)) return { ok: false, error: "target_is_staff" };

    var reason = String((args && args.reason) || "Staff action").substring(0, 80);
    var hours = null;

    if (action === "ban") {
        hours = Math.floor(Number(args.hours) || 0);
        if (hours <= 0) {
            if (!hasStaffRole("Owner")) return { ok: false, error: "permanent_ban_needs_owner" };
            server.BanUsers({ Bans: [{ PlayFabId: target, Reason: reason }] });
        } else {
            hours = Math.min(hours, 720);
            server.BanUsers({ Bans: [{ PlayFabId: target, Reason: reason, DurationInHours: hours }] });
        }
    }

    var pending = {
        type: action === "bring" ? "bring" : "kick",
        by: currentPlayerId,
        at: Date.now(),
        reason: reason
    };
    server.UpdateUserInternalData({ PlayFabId: target, Data: { PendingStaffAction: JSON.stringify(pending) } });
    writeStaffAudit({ action: action, target: target, reason: reason, hours: hours });

    return { ok: true, action: action };
};

handlers.StaffConfirmAction = function (args, context) {
    var data = server.GetUserInternalData({ PlayFabId: currentPlayerId, Keys: ["PendingStaffAction"] }).Data || {};
    var pending = parseStaffJson((data.PendingStaffAction || {}).Value, null);
    if (!pending) return { ok: true, type: "none" };

    server.UpdateUserInternalData({ PlayFabId: currentPlayerId, KeysToRemove: ["PendingStaffAction"] });

    if (Date.now() - pending.at > staffActionLifetime) return { ok: true, type: "none", expired: true };

    var needed = pending.type === "bring" ? "Admin" : "Moderator";
    if (getStaffRank(pending.by) < staffRanks[needed]) return { ok: true, type: "none", revoked: true };

    return { ok: true, type: pending.type, by: pending.by, reason: pending.reason };
};

// end of staff / mod checker

// start of live events

var liveEventKeys = { clawd: "ClawdEventGlobal", meteor: "MeteorEventGlobal", bloodmoon: "BloodMoonEventGlobal" };
var liveEventGraceMs = 300000;

function isValidRoomName(room) {
    return typeof room === "string" && room.length > 0 && room.length <= 40 && /^[A-Za-z0-9 _\-]+$/.test(room);
}

function optionalRoom(args) {
    var room = args && args.room;
    if (room === undefined || room === null || room === "") return { ok: true, room: "" };
    return { ok: isValidRoomName(room), room: room };
}

function newClawdEventId() {
    return Date.now().toString(36) + Math.floor(Math.random() * 1000000000).toString(36);
}

function newLiveEntry() {
    return {
        seq: 0, eventId: "", status: "idle", startAt: 0, duration: 0, action: "", value: 0, at: 0, by: "",
        tested: false, phase: 0, paused: false, pausedAt: 0, pausedMs: 0, meteors: -1, rate: 0, mapmode: 0, spawned: -1
    };
}

function getLiveEntries(names) {
    var keys = [];
    for (var i = 0; i < names.length; i++) keys.push(liveEventKeys[names[i]]);
    var data = server.GetTitleInternalData({ Keys: keys }).Data || {};
    var entries = {};
    for (var j = 0; j < names.length; j++) {
        var entry = parseStaffJson(data[liveEventKeys[names[j]]], null);
        var fresh = newLiveEntry();
        if (entry) {
            for (var field in fresh) {
                if (entry[field] === undefined) entry[field] = fresh[field];
            }
        }
        entries[names[j]] = entry || fresh;
    }
    return entries;
}

function getLiveEntry(name) {
    return getLiveEntries([name])[name];
}

function saveLiveEntry(name, entry) {
    server.SetTitleInternalData({ Key: liveEventKeys[name], Value: JSON.stringify(entry) });
}

function liveElapsed(entry) {
    if (!entry.startAt) return 0;
    var until = entry.paused ? entry.pausedAt : Date.now();
    return Math.max(0, until - entry.startAt - (entry.pausedMs || 0));
}

function liveStatus(entry, maxPlayMs) {
    if (entry.status !== "running") return entry.status;
    if (Date.now() - entry.startAt > maxPlayMs) return "expired";
    if (entry.duration > 0 && liveElapsed(entry) > entry.duration * 1000 + liveEventGraceMs) return "expired";
    return "running";
}

function liveView(entry, maxPlayMs) {
    return {
        ok: true,
        seq: entry.seq,
        action: entry.action,
        value: entry.value,
        eventId: entry.eventId,
        status: liveStatus(entry, maxPlayMs),
        by: entry.by,
        at: entry.at,
        elapsedMs: liveElapsed(entry),
        duration: entry.duration,
        phase: entry.phase,
        paused: entry.paused,
        meteors: entry.meteors,
        rate: entry.rate,
        mapmode: entry.mapmode,
        spawned: entry.spawned
    };
}

function beginLiveRun(entry, now, duration) {
    entry.eventId = newClawdEventId();
    entry.status = "running";
    entry.startAt = now;
    entry.duration = duration;
    entry.phase = 0;
    entry.paused = false;
    entry.pausedAt = 0;
    entry.pausedMs = 0;
}

function stampLiveCommand(entry, action, value, room) {
    entry.seq = (entry.seq || 0) + 1;
    entry.action = action;
    entry.value = value;
    entry.at = Date.now();
    entry.by = currentPlayerId;
    entry.room = room;
}

handlers.LiveEventGet = function (args, context) {
    var entries = getLiveEntries(["clawd", "meteor", "bloodmoon"]);
    return {
        ok: true,
        now: Date.now(),
        clawd: liveView(entries.clawd, clawdMaxPlayMs),
        meteor: liveView(entries.meteor, meteorMaxPlayMs),
        bloodmoon: liveView(entries.bloodmoon, bloodMoonMaxPlayMs)
    };
};

// end of live events

// start of clawd event

var clawdMinPlayMs = 180000;
var clawdMaxPlayMs = 7200000;
var clawdMaxEventsKept = 20;
var clawdActions = { start: true, stop: true, reset: true, spawn: true, despawn: true, phase: true, duration: true };

handlers.ClawdEventCommand = function (args, context) {
    if (!hasStaffRole("Admin")) return staffDenied();

    var where = optionalRoom(args);
    if (!where.ok) return { ok: false, error: "bad_room" };

    var action = args && args.action;
    if (!clawdActions[action]) return { ok: false, error: "bad_action" };

    var value = Math.floor(Number(args.value) || 0);
    if (action === "phase" && (value < 1 || value > 9)) return { ok: false, error: "bad_value" };
    if (action === "duration" && (value < 180 || value > 3600)) return { ok: false, error: "bad_value" };
    if (action === "start") value = Math.min(Math.max(value || 900, 180), 3600);

    var entry = getLiveEntry("clawd");
    var now = Date.now();
    var running = liveStatus(entry, clawdMaxPlayMs) === "running";
    stampLiveCommand(entry, action, value, where.room);

    if (action === "start" || (action === "phase" && !running)) {
        beginLiveRun(entry, now, action === "start" ? value : (entry.duration || 900));
        entry.spawned = 1;
    }
    if (action === "phase") entry.phase = value;
    else if (action === "stop") entry.status = "stopped";
    else if (action === "reset") {
        entry.status = "idle";
        entry.eventId = "";
        entry.startAt = 0;
        entry.phase = 0;
        entry.spawned = 0;
    } else if (action === "spawn") entry.spawned = 1;
    else if (action === "despawn") entry.spawned = 0;
    else if (action === "duration") entry.duration = value;

    saveLiveEntry("clawd", entry);
    writeStaffAudit({ action: "clawd_" + action, target: where.room || "global", reason: String(value) });

    return { ok: true, seq: entry.seq, eventId: entry.eventId };
};

handlers.ClawdEventGetCommand = function (args, context) {
    if (!optionalRoom(args).ok) return { ok: false, error: "bad_room" };
    return liveView(getLiveEntry("clawd"), clawdMaxPlayMs);
};

handlers.ClawdEventClaimReward = function (args, context) {
    var room = args && args.room;
    var eventId = args && args.eventId;
    if (!isValidRoomName(room) || typeof eventId !== "string" || !eventId) return { ok: false, error: "bad_event" };

    var entry = getLiveEntry("clawd");
    if (entry.eventId !== eventId || liveStatus(entry, clawdMaxPlayMs) !== "running") return { ok: false, error: "event_not_running" };
    if (Date.now() - entry.startAt < clawdMinPlayMs) return { ok: false, error: "too_fast" };

    var data = server.GetUserReadOnlyData({ PlayFabId: currentPlayerId, Keys: ["ClawdTakeover"] }).Data || {};
    var record = parseStaffJson((data.ClawdTakeover || {}).Value, null) || {};
    if (!(record.events instanceof Array)) record.events = [];
    record.wins = Math.floor(Number(record.wins) || 0);

    if (record.events.indexOf(eventId) !== -1) return { ok: true, wins: record.wins, already: true };

    record.wins++;
    record.events.unshift(eventId);
    if (record.events.length > clawdMaxEventsKept) record.events.length = clawdMaxEventsKept;
    record.last = Date.now();
    server.UpdateUserReadOnlyData({ PlayFabId: currentPlayerId, Data: { ClawdTakeover: JSON.stringify(record) } });

    return { ok: true, wins: record.wins };
};

// end of clawd event

// start of meteor event

var meteorMaxPlayMs = 10800000;
var meteorMinPlayMs = 300000;
var meteorMinPresenceMs = 120000;
var meteorMaxEventsKept = 20;
var meteorCatalog = "DLC";
var meteorRewardItems = [];
var meteorUnlocks = ["meteor_badge", "meteor_title", "meteor_nameplate", "meteor_trail"];
var meteorActions = { start: true, stop: true, pause: true, resume: true, reset: true, skip: true, phase: true, boss: true, bosswin: true, meteors: true, rate: true, duration: true, envreset: true, mapmode: true };
var meteorTestActions = { skip: true, phase: true, boss: true, bosswin: true };
var meteorForcedPhases = { boss: 5, bosswin: 6 };

function meteorValueOk(action, value) {
    if (action === "phase") return value >= 1 && value <= 7;
    if (action === "duration") return value >= 600 && value <= 7200;
    if (action === "rate") return value >= 2 && value <= 60;
    if (action === "meteors") return value === 0 || value === 1;
    if (action === "mapmode") return value >= 0 && value <= 2;
    return true;
}

function getMeteorRecord(playFabId) {
    var data = server.GetUserReadOnlyData({ PlayFabId: playFabId, Keys: ["MeteorMadness"] }).Data || {};
    var record = parseStaffJson((data.MeteorMadness || {}).Value, null) || {};
    if (!(record.events instanceof Array)) record.events = [];
    if (!(record.unlocks instanceof Array)) record.unlocks = [];
    record.completions = Math.floor(Number(record.completions) || 0);
    return record;
}

handlers.MeteorEventCommand = function (args, context) {
    if (!hasStaffRole("Admin")) return staffDenied();

    var where = optionalRoom(args);
    if (!where.ok) return { ok: false, error: "bad_room" };

    var action = args && args.action;
    if (!meteorActions[action]) return { ok: false, error: "bad_action" };

    var value = Math.floor(Number(args.value) || 0);
    if (!meteorValueOk(action, value)) return { ok: false, error: "bad_value" };
    if (action === "start") value = Math.min(Math.max(value || 2400, 600), 7200);

    var entry = getLiveEntry("meteor");
    var now = Date.now();
    var running = liveStatus(entry, meteorMaxPlayMs) === "running";
    stampLiveCommand(entry, action, value, where.room);

    var forced = action === "phase" ? value : (meteorForcedPhases[action] || 0);
    if (action === "start" || (forced > 0 && !running)) {
        beginLiveRun(entry, now, action === "start" ? value : (entry.duration || 2400));
        entry.tested = action !== "start";
    }
    if (forced > 0) entry.phase = forced;
    if (meteorTestActions[action]) entry.tested = true;

    if (action === "stop") {
        entry.status = "stopped";
        entry.paused = false;
    } else if (action === "reset") {
        entry.status = "idle";
        entry.eventId = "";
        entry.startAt = 0;
        entry.tested = false;
        entry.phase = 0;
        entry.paused = false;
    } else if (action === "pause" && !entry.paused) {
        entry.paused = true;
        entry.pausedAt = now;
    } else if (action === "resume" && entry.paused) {
        entry.pausedMs = (entry.pausedMs || 0) + (now - entry.pausedAt);
        entry.paused = false;
    } else if (action === "meteors") entry.meteors = value;
    else if (action === "rate") entry.rate = value;
    else if (action === "mapmode") entry.mapmode = value;
    else if (action === "duration") entry.duration = value;

    saveLiveEntry("meteor", entry);
    writeStaffAudit({ action: "meteor_" + action, target: where.room || "global", reason: String(value) });

    return { ok: true, seq: entry.seq, eventId: entry.eventId };
};

handlers.MeteorEventGetCommand = function (args, context) {
    if (!optionalRoom(args).ok) return { ok: false, error: "bad_room" };
    return liveView(getLiveEntry("meteor"), meteorMaxPlayMs);
};

handlers.MeteorEventCheckIn = function (args, context) {
    var room = args && args.room;
    var eventId = args && args.eventId;
    if (!isValidRoomName(room) || typeof eventId !== "string" || !eventId) return { ok: false, error: "bad_event" };

    var entry = getLiveEntry("meteor");
    if (entry.eventId !== eventId || liveStatus(entry, meteorMaxPlayMs) !== "running") return { ok: false, error: "event_not_running" };

    var data = server.GetUserInternalData({ PlayFabId: currentPlayerId, Keys: ["MeteorPresence"] }).Data || {};
    var presence = parseStaffJson((data.MeteorPresence || {}).Value, null);
    if (presence && presence.eventId === eventId && presence.room === room) return { ok: true, at: presence.at };

    presence = { eventId: eventId, room: room, at: Date.now() };
    server.UpdateUserInternalData({ PlayFabId: currentPlayerId, Data: { MeteorPresence: JSON.stringify(presence) } });
    return { ok: true, at: presence.at };
};

handlers.MeteorEventClaimReward = function (args, context) {
    var room = args && args.room;
    var eventId = args && args.eventId;
    if (!isValidRoomName(room) || typeof eventId !== "string" || !eventId) return { ok: false, error: "bad_event" };

    var entry = getLiveEntry("meteor");
    if (entry.eventId !== eventId || liveStatus(entry, meteorMaxPlayMs) !== "running") return { ok: false, error: "event_not_running" };
    if (entry.tested) return { ok: false, error: "test_run" };
    var now = Date.now();
    if (now - entry.startAt < meteorMinPlayMs) return { ok: false, error: "too_fast" };

    var data = server.GetUserInternalData({ PlayFabId: currentPlayerId, Keys: ["MeteorPresence"] }).Data || {};
    var presence = parseStaffJson((data.MeteorPresence || {}).Value, null);
    if (!presence || presence.eventId !== eventId || presence.room !== room) return { ok: false, error: "no_check_in" };
    if (now - presence.at < meteorMinPresenceMs) return { ok: false, error: "joined_too_late" };

    var record = getMeteorRecord(currentPlayerId);
    if (record.events.indexOf(eventId) !== -1) {
        return { ok: true, already: true, completions: record.completions, unlocks: record.unlocks, granted: [] };
    }

    record.completions++;
    record.events.unshift(eventId);
    if (record.events.length > meteorMaxEventsKept) record.events.length = meteorMaxEventsKept;
    for (var i = 0; i < meteorUnlocks.length; i++) {
        if (record.unlocks.indexOf(meteorUnlocks[i]) === -1) record.unlocks.push(meteorUnlocks[i]);
    }
    var fragments = Math.min(Math.max(Math.floor(Number(args.fragments) || 0), 0), 30);
    var crystals = Math.min(Math.max(Math.floor(Number(args.crystals) || 0), 0), 30);
    record.bestFragments = Math.max(Math.floor(Number(record.bestFragments) || 0), fragments);
    record.bestCrystals = Math.max(Math.floor(Number(record.bestCrystals) || 0), crystals);
    record.last = now;

    var granted = [];
    if (meteorRewardItems.length > 0) {
        var owned = {};
        var inventory = server.GetUserInventory({ PlayFabId: currentPlayerId }).Inventory || [];
        for (var j = 0; j < inventory.length; j++) owned[inventory[j].ItemId] = true;
        for (var k = 0; k < meteorRewardItems.length; k++) {
            if (!owned[meteorRewardItems[k]]) granted.push(meteorRewardItems[k]);
        }
        if (granted.length > 0) {
            server.GrantItemsToUser({ PlayFabId: currentPlayerId, CatalogVersion: meteorCatalog, ItemIds: granted, Annotation: "Meteor Madness " + eventId });
        }
    }

    server.UpdateUserReadOnlyData({ PlayFabId: currentPlayerId, Data: { MeteorMadness: JSON.stringify(record) } });

    return { ok: true, completions: record.completions, unlocks: record.unlocks, granted: granted };
};

handlers.MeteorEventGetRecord = function (args, context) {
    var record = getMeteorRecord(currentPlayerId);
    return { ok: true, completions: record.completions, unlocks: record.unlocks, granted: [] };
};

// end of meteor event

// start of blood moon event

var bloodMoonMaxPlayMs = 10800000;
var bloodMoonMinPlayMs = 360000;
var bloodMoonMinPresenceMs = 150000;
var bloodMoonMaxEventsKept = 20;
var bloodMoonCatalog = "DLC";
var bloodMoonRewardItems = [];
var bloodMoonUnlocks = ["bloodmoon_badge", "bloodmoon_horns", "bloodmoon_trail", "bloodmoon_nameplate", "bloodmoon_title"];
var bloodMoonActions = { start: true, stop: true, pause: true, resume: true, reset: true, skip: true, phase: true, boss: true, bosswin: true, attack: true, fragments: true, creatures: true, duration: true, envreset: true };
var bloodMoonTestActions = { skip: true, phase: true, boss: true, bosswin: true, attack: true, fragments: true, creatures: true };
var bloodMoonForcedPhases = { boss: 5, attack: 5, bosswin: 6 };
var bloodMoonNeedsRun = { skip: true, fragments: true, creatures: true };

function bloodMoonValueOk(action, value) {
    if (action === "phase") return value >= 1 && value <= 7;
    if (action === "attack") return value >= 1 && value <= 4;
    if (action === "duration") return value >= 600 && value <= 7200;
    return true;
}

function getBloodMoonRecord(playFabId) {
    var data = server.GetUserReadOnlyData({ PlayFabId: playFabId, Keys: ["BloodMoonRising"] }).Data || {};
    var record = parseStaffJson((data.BloodMoonRising || {}).Value, null) || {};
    if (!(record.events instanceof Array)) record.events = [];
    if (!(record.unlocks instanceof Array)) record.unlocks = [];
    record.completions = Math.floor(Number(record.completions) || 0);
    return record;
}

handlers.BloodMoonEventCommand = function (args, context) {
    if (!hasStaffRole("Admin")) return staffDenied();

    var where = optionalRoom(args);
    if (!where.ok) return { ok: false, error: "bad_room" };

    var action = args && args.action;
    if (!bloodMoonActions[action]) return { ok: false, error: "bad_action" };

    var value = Math.floor(Number(args.value) || 0);
    if (!bloodMoonValueOk(action, value)) return { ok: false, error: "bad_value" };
    if (action === "start") value = Math.min(Math.max(value || 2700, 600), 7200);

    var entry = getLiveEntry("bloodmoon");
    var now = Date.now();
    var running = liveStatus(entry, bloodMoonMaxPlayMs) === "running";
    if (bloodMoonNeedsRun[action] && !running) return { ok: false, error: "not_running" };
    stampLiveCommand(entry, action, value, where.room);

    var forced = action === "phase" ? value : (bloodMoonForcedPhases[action] || 0);
    if (action === "start" || (forced > 0 && !running)) {
        beginLiveRun(entry, now, action === "start" ? value : (entry.duration || 2700));
        entry.tested = action !== "start";
    }
    if (forced > 0) entry.phase = forced;
    if (bloodMoonTestActions[action]) entry.tested = true;

    if (action === "stop") {
        entry.status = "stopped";
        entry.paused = false;
    } else if (action === "reset") {
        entry.status = "idle";
        entry.eventId = "";
        entry.startAt = 0;
        entry.tested = false;
        entry.phase = 0;
        entry.paused = false;
    } else if (action === "pause" && !entry.paused) {
        entry.paused = true;
        entry.pausedAt = now;
    } else if (action === "resume" && entry.paused) {
        entry.pausedMs = (entry.pausedMs || 0) + (now - entry.pausedAt);
        entry.paused = false;
    } else if (action === "duration") entry.duration = value;

    saveLiveEntry("bloodmoon", entry);
    writeStaffAudit({ action: "bloodmoon_" + action, target: where.room || "global", reason: String(value) });

    return { ok: true, seq: entry.seq, eventId: entry.eventId };
};

handlers.BloodMoonEventGetCommand = function (args, context) {
    if (!optionalRoom(args).ok) return { ok: false, error: "bad_room" };
    return liveView(getLiveEntry("bloodmoon"), bloodMoonMaxPlayMs);
};

handlers.BloodMoonEventCheckIn = function (args, context) {
    var room = args && args.room;
    var eventId = args && args.eventId;
    if (!isValidRoomName(room) || typeof eventId !== "string" || !eventId) return { ok: false, error: "bad_event" };

    var entry = getLiveEntry("bloodmoon");
    if (entry.eventId !== eventId || liveStatus(entry, bloodMoonMaxPlayMs) !== "running") return { ok: false, error: "event_not_running" };

    var data = server.GetUserInternalData({ PlayFabId: currentPlayerId, Keys: ["BloodMoonPresence"] }).Data || {};
    var presence = parseStaffJson((data.BloodMoonPresence || {}).Value, null);
    if (presence && presence.eventId === eventId && presence.room === room) return { ok: true, at: presence.at };

    presence = { eventId: eventId, room: room, at: Date.now() };
    server.UpdateUserInternalData({ PlayFabId: currentPlayerId, Data: { BloodMoonPresence: JSON.stringify(presence) } });
    return { ok: true, at: presence.at };
};

handlers.BloodMoonEventClaimReward = function (args, context) {
    var room = args && args.room;
    var eventId = args && args.eventId;
    if (!isValidRoomName(room) || typeof eventId !== "string" || !eventId) return { ok: false, error: "bad_event" };

    var entry = getLiveEntry("bloodmoon");
    if (entry.eventId !== eventId || liveStatus(entry, bloodMoonMaxPlayMs) !== "running") return { ok: false, error: "event_not_running" };
    if (entry.tested) return { ok: false, error: "test_run" };
    var now = Date.now();
    if (liveElapsed(entry) < bloodMoonMinPlayMs) return { ok: false, error: "too_fast" };

    var data = server.GetUserInternalData({ PlayFabId: currentPlayerId, Keys: ["BloodMoonPresence"] }).Data || {};
    var presence = parseStaffJson((data.BloodMoonPresence || {}).Value, null);
    if (!presence || presence.eventId !== eventId || presence.room !== room) return { ok: false, error: "no_check_in" };
    if (now - presence.at < bloodMoonMinPresenceMs) return { ok: false, error: "joined_too_late" };

    var record = getBloodMoonRecord(currentPlayerId);
    if (record.events.indexOf(eventId) !== -1) {
        return { ok: true, already: true, completions: record.completions, unlocks: record.unlocks, granted: [] };
    }

    record.completions++;
    record.events.unshift(eventId);
    if (record.events.length > bloodMoonMaxEventsKept) record.events.length = bloodMoonMaxEventsKept;
    for (var i = 0; i < bloodMoonUnlocks.length; i++) {
        if (record.unlocks.indexOf(bloodMoonUnlocks[i]) === -1) record.unlocks.push(bloodMoonUnlocks[i]);
    }
    var fragments = Math.min(Math.max(Math.floor(Number(args.fragments) || 0), 0), 48);
    var creatures = Math.min(Math.max(Math.floor(Number(args.creatures) || 0), 0), 12);
    record.bestFragments = Math.max(Math.floor(Number(record.bestFragments) || 0), fragments);
    record.bestCreatures = Math.max(Math.floor(Number(record.bestCreatures) || 0), creatures);
    record.last = now;

    var granted = [];
    if (bloodMoonRewardItems.length > 0) {
        var owned = {};
        var inventory = server.GetUserInventory({ PlayFabId: currentPlayerId }).Inventory || [];
        for (var j = 0; j < inventory.length; j++) owned[inventory[j].ItemId] = true;
        for (var k = 0; k < bloodMoonRewardItems.length; k++) {
            if (!owned[bloodMoonRewardItems[k]]) granted.push(bloodMoonRewardItems[k]);
        }
        if (granted.length > 0) {
            server.GrantItemsToUser({ PlayFabId: currentPlayerId, CatalogVersion: bloodMoonCatalog, ItemIds: granted, Annotation: "Blood Moon Rising " + eventId });
        }
    }

    server.UpdateUserReadOnlyData({ PlayFabId: currentPlayerId, Data: { BloodMoonRising: JSON.stringify(record) } });

    return { ok: true, completions: record.completions, unlocks: record.unlocks, granted: granted };
};

handlers.BloodMoonEventGetRecord = function (args, context) {
    var record = getBloodMoonRecord(currentPlayerId);
    return { ok: true, completions: record.completions, unlocks: record.unlocks, granted: [] };
};

// end of blood moon event

// start of badges and name colors

var BADGE_IDS = {
    owner: ["BBA61C3A92481AF4", "C47D101DE0EBA7EE"],
    staff: [],
    developer: [],
    moderator: [],
    creator: [],
    verified: []
};

var NAME_COLOR_IDS = {
    all: ["BBA61C3A92481AF4", "C47D101DE0EBA7EE"],
    red: [],
    orange: [],
    gold: [],
    green: [],
    cyan: [],
    blue: [],
    purple: [],
    pink: [],
    rainbow: []
};

handlers.GetPlayerBadges = function (args, context) {
    var ids = (args && args.playFabIds) || [];
    if (!(ids instanceof Array)) ids = [];
    if (ids.length > 50) ids = ids.slice(0, 50);

    var players = [];
    for (var i = 0; i < ids.length; i++) {
        var id = ids[i];
        if (typeof id !== "string" || !/^[0-9A-F]{8,20}$/i.test(id)) continue;

        var badges = [];
        for (var badge in BADGE_IDS) {
            if (BADGE_IDS[badge].indexOf(id) !== -1) badges.push(badge);
        }

        var colors = [];
        var hasAll = NAME_COLOR_IDS.all.indexOf(id) !== -1;
        for (var color in NAME_COLOR_IDS) {
            if (color === "all") continue;
            if (hasAll || NAME_COLOR_IDS[color].indexOf(id) !== -1) colors.push(color);
        }

        players.push({ id: id, badges: badges, colors: colors });
    }
    return { ok: true, players: players };
};

// end of badges and name colors

// start of achievements

var ACHIEVEMENT_REWARDS = {
    "welcome": 500,
    "first_lobby": 500,
    "first_tag": 750,
    "tag_master": 2000,
    "dedicated_monke": 1500,
    "explorer": 1000,
    "parkour_master": 1250,
    "full_house": 500,
    "drip_check": 500,
    "daily_grind": 1000,
    "best_buds": 500,
    "true_colors": 500,
    "lobby_hopper": 1500
};
var ACHIEVEMENT_CURRENCY = "SR";
var ACHIEVEMENT_KEY = "Achievements";
var ACHIEVEMENT_MIN_REWARD = 500;
var ACHIEVEMENT_MAX_REWARD = 2000;

handlers.UnlockAchievement = function (args, context) {
    var id = args && args.id;
    if (typeof id !== "string" || !ACHIEVEMENT_REWARDS.hasOwnProperty(id)) return { ok: false, error: "unknown_achievement" };

    var data = server.GetUserReadOnlyData({ PlayFabId: currentPlayerId, Keys: [ACHIEVEMENT_KEY] }).Data || {};
    var value = (data[ACHIEVEMENT_KEY] || {}).Value || "";
    var unlocked = value ? value.split(",") : [];
    if (unlocked.indexOf(id) !== -1) return { ok: true, already: true, reward: 0 };

    unlocked.push(id);
    var update = {};
    update[ACHIEVEMENT_KEY] = unlocked.join(",");
    server.UpdateUserReadOnlyData({ PlayFabId: currentPlayerId, Data: update });

    var reward = Math.floor(Number(ACHIEVEMENT_REWARDS[id]) || 0);
    reward = Math.max(ACHIEVEMENT_MIN_REWARD, Math.min(ACHIEVEMENT_MAX_REWARD, reward));
    var granted = server.AddUserVirtualCurrency({ PlayFabId: currentPlayerId, VirtualCurrency: ACHIEVEMENT_CURRENCY, Amount: reward });
    return { ok: true, reward: reward, balance: granted.Balance };
};

// end of achievements

// start of hide and seek

var HNS_REWARDS = {
    "seeker_win": 150,
    "hider_win": 120,
    "participation": 25
};
var HNS_CURRENCY = "SR";
var HNS_KEY = "HideAndSeek";
var HNS_MIN_SECONDS_BETWEEN = 60;
var HNS_DAILY_CAP = 2000;
var HNS_ROUNDS_KEPT = 20;

handlers.HideAndSeekReward = function (args, context) {
    var round = args && args.round;
    var outcome = args && args.outcome;
    var players = Math.floor(Number(args && args.players) || 0);
    if (typeof round !== "string" || round.length < 3 || round.length > 80) return { ok: false, error: "bad_round" };
    if (!HNS_REWARDS.hasOwnProperty(outcome) || players < 2 || players > 10) return { ok: false, error: "bad_request" };

    var data = server.GetUserReadOnlyData({ PlayFabId: currentPlayerId, Keys: [HNS_KEY] }).Data || {};
    var record = {};
    try { record = JSON.parse((data[HNS_KEY] || {}).Value || "{}") || {}; } catch (e) { record = {}; }
    if (!(record.rounds instanceof Array)) record.rounds = [];
    record.last = Number(record.last) || 0;
    record.today = Math.floor(Number(record.today) || 0);

    if (record.rounds.indexOf(round) !== -1) return { ok: true, already: true, reward: 0 };
    var now = Date.now();
    if (now - record.last < HNS_MIN_SECONDS_BETWEEN * 1000) return { ok: false, error: "too_soon" };

    var day = new Date(now).toISOString().substring(0, 10);
    if (record.day !== day) {
        record.day = day;
        record.today = 0;
    }
    var reward = Math.max(0, Math.min(HNS_REWARDS[outcome], HNS_DAILY_CAP - record.today));

    record.rounds.unshift(round);
    if (record.rounds.length > HNS_ROUNDS_KEPT) record.rounds.length = HNS_ROUNDS_KEPT;
    record.last = now;
    record.today += reward;
    var update = {};
    update[HNS_KEY] = JSON.stringify(record);
    server.UpdateUserReadOnlyData({ PlayFabId: currentPlayerId, Data: update });

    if (reward <= 0) return { ok: true, reward: 0, capped: true };
    var granted = server.AddUserVirtualCurrency({ PlayFabId: currentPlayerId, VirtualCurrency: HNS_CURRENCY, Amount: reward });
    return { ok: true, reward: reward, balance: granted.Balance };
};

// end of hide and seek

// start of daily quests

// The quest list lives here so players can't pick or change their own quests. Every UTC day each
// player gets 3 quests of different kinds, picked from this list with a seed made from the date and
// their id. minSec is the least time (since they first loaded today's quests) that the quest could
// really take, so a claim that comes in faster than that is refused.
var DQ_POOL = [
    { id: "tag_5",          type: "tag",     target: 5,    title: "TAG 5 MONKES",                 reward: 1500, minSec: 60 },
    { id: "tag_15",         type: "tag",     target: 15,   title: "TAG 15 MONKES",                reward: 3000, minSec: 300 },
    { id: "tag_30",         type: "tag",     target: 30,   title: "TAG 30 MONKES",                reward: 5000, minSec: 600 },
    { id: "play_10",        type: "play",    target: 10,   title: "PLAY FOR 10 MINUTES",          reward: 1500, minSec: 600 },
    { id: "play_30",        type: "play",    target: 30,   title: "PLAY FOR 30 MINUTES",          reward: 4000, minSec: 1800 },
    { id: "lobbies_3",      type: "lobbies", target: 3,    title: "JOIN 3 DIFFERENT LOBBIES",     reward: 1500, minSec: 60 },
    { id: "lobbies_6",      type: "lobbies", target: 6,    title: "JOIN 6 DIFFERENT LOBBIES",     reward: 2500, minSec: 180 },
    { id: "travel_500",     type: "travel",  target: 500,  title: "TRAVEL 500 METERS",            reward: 2000, minSec: 120 },
    { id: "travel_1500",    type: "travel",  target: 1500, title: "TRAVEL 1500 METERS",           reward: 4500, minSec: 360 },
    { id: "mode_infection", type: "mode", mode: "INFECTION",   target: 5, title: "PLAY 5 MIN OF INFECTION",      reward: 2500, minSec: 300 },
    { id: "mode_rush",      type: "mode", mode: "RUSH",        target: 5, title: "PLAY 5 MIN OF INFECTION RUSH", reward: 2500, minSec: 300 },
    { id: "mode_guardian",  type: "mode", mode: "GUARDIAN",    target: 5, title: "PLAY 5 MIN OF GUARDIAN",       reward: 2500, minSec: 300 },
    { id: "mode_freeze",    type: "mode", mode: "FREEZETAG",   target: 5, title: "PLAY 5 MIN OF FREEZE TAG",     reward: 2500, minSec: 300 },
    { id: "mode_hide",      type: "mode", mode: "HIDEANDSEEK", target: 5, title: "PLAY 5 MIN OF HIDE AND SEEK",  reward: 2500, minSec: 300 },
    { id: "mode_tiny",      type: "mode", mode: "TINY",        target: 5, title: "PLAY 5 MIN OF TINY MONKES",    reward: 2500, minSec: 300 },
    { id: "mode_giant",     type: "mode", mode: "GIANT",       target: 5, title: "PLAY 5 MIN OF GIANT MONKES",   reward: 2500, minSec: 300 }
];
var DQ_COUNT = 3;
var DQ_ALL_DONE_BONUS = 2500;
var DQ_CURRENCY = "SR";
var DQ_KEY = "DailyQuests";

function dqDay(now) {
    return new Date(now).toISOString().substring(0, 10);
}

function dqSecondsToReset(now) {
    var d = new Date(now);
    var next = Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate() + 1);
    return Math.max(0, Math.floor((next - now) / 1000));
}

function dqFind(id) {
    for (var i = 0; i < DQ_POOL.length; i++) if (DQ_POOL[i].id === id) return DQ_POOL[i];
    return null;
}

// Same answer every time for the same player and day.
function dqPick(day, playFabId) {
    var seed = 2166136261;
    var key = day + ":" + playFabId;
    for (var i = 0; i < key.length; i++) {
        seed ^= key.charCodeAt(i);
        seed = (seed * 16777619) >>> 0;
    }
    function next() {
        seed = (seed * 1664525 + 1013904223) >>> 0;
        return seed / 4294967296;
    }
    var order = DQ_POOL.slice();
    for (var j = order.length - 1; j > 0; j--) {
        var k = Math.floor(next() * (j + 1));
        var tmp = order[j]; order[j] = order[k]; order[k] = tmp;
    }
    var picked = [], types = {};
    for (var n = 0; n < order.length && picked.length < DQ_COUNT; n++) {
        if (types[order[n].type]) continue;
        types[order[n].type] = true;
        picked.push(order[n].id);
    }
    return picked;
}

var DQ_STAT = "QuestsCompleted";
var DQ_TOP = 10;

function dqYesterday(now) {
    return dqDay(now - 86400000);
}

// One record per player. The quests reset every day; the totals and streak carry over.
function dqRecord(playFabId, now) {
    var data = server.GetUserReadOnlyData({ PlayFabId: playFabId, Keys: [DQ_KEY] }).Data || {};
    var record = parseStaffJson((data[DQ_KEY] || {}).Value, null) || {};
    var day = dqDay(now);
    if (record.day !== day || !(record.quests instanceof Array) || !(record.claimed instanceof Array)) {
        record = {
            day: day, firstSeen: now, quests: dqPick(day, playFabId), claimed: [], bonus: false,
            total: Math.floor(Number(record.total) || 0),
            streak: Math.floor(Number(record.streak) || 0),
            bestStreak: Math.floor(Number(record.bestStreak) || 0),
            lastAllDay: record.lastAllDay || ""
        };
        dqSave(playFabId, record);
    }
    return record;
}

function dqSave(playFabId, record) {
    var update = {};
    update[DQ_KEY] = JSON.stringify(record);
    server.UpdateUserReadOnlyData({ PlayFabId: playFabId, Data: update });
}

// A streak is days in a row with all quests done; it's still alive today if yesterday counted.
function dqStreak(record, now) {
    if (record.lastAllDay === dqDay(now) || record.lastAllDay === dqYesterday(now)) return record.streak || 0;
    return 0;
}

function dqTop(playFabId) {
    var top = [];
    var me = { rank: 0 };
    try {
        var board = server.GetLeaderboard({ StatisticName: DQ_STAT, StartPosition: 0, MaxResultsCount: DQ_TOP }).Leaderboard || [];
        for (var i = 0; i < board.length; i++) {
            if (!board[i].StatValue) continue;
            top.push({ name: String(board[i].DisplayName || "MONKE").split("#")[0].substring(0, 12), value: board[i].StatValue });
        }
        var around = server.GetLeaderboardAroundUser({ StatisticName: DQ_STAT, PlayFabId: playFabId, MaxResultsCount: 1 }).Leaderboard || [];
        if (around.length > 0 && around[0].StatValue) me.rank = around[0].Position + 1;
    } catch (e) { }
    return { top: top, rank: me.rank };
}

function dqView(record, now, playFabId) {
    var quests = [];
    for (var i = 0; i < record.quests.length; i++) {
        var q = dqFind(record.quests[i]);
        if (!q) continue;
        quests.push({ id: q.id, type: q.type, mode: q.mode || "", target: q.target, title: q.title, reward: q.reward,
            claimed: record.claimed.indexOf(q.id) !== -1 });
    }
    var board = dqTop(playFabId);
    return {
        ok: true, day: record.day, resetsIn: dqSecondsToReset(now), bonus: DQ_ALL_DONE_BONUS, bonusClaimed: !!record.bonus, quests: quests,
        total: record.total || 0, streak: dqStreak(record, now), bestStreak: record.bestStreak || 0, rank: board.rank, top: board.top
    };
}

handlers.DailyQuestsGet = function (args, context) {
    var now = Date.now();
    return dqView(dqRecord(currentPlayerId, now), now, currentPlayerId);
};

handlers.DailyQuestClaim = function (args, context) {
    var id = args && args.id;
    var day = args && args.day;
    var now = Date.now();
    if (typeof id !== "string" || !dqFind(id)) return { ok: false, error: "unknown_quest" };
    var record = dqRecord(currentPlayerId, now);
    if (day !== record.day) return { ok: false, error: "new_day" };
    if (record.quests.indexOf(id) === -1) return { ok: false, error: "not_today" };
    if (record.claimed.indexOf(id) !== -1) return { ok: true, already: true, reward: 0, bonus: 0 };
    var quest = dqFind(id);
    if (now - record.firstSeen < quest.minSec * 1000) return { ok: false, error: "too_fast" };

    record.claimed.push(id);
    record.total = (record.total || 0) + 1;
    var reward = quest.reward;
    var bonus = 0;
    if (!record.bonus && record.claimed.length >= record.quests.length) {
        record.bonus = true;
        bonus = DQ_ALL_DONE_BONUS;
        record.streak = record.lastAllDay === dqYesterday(now) ? (record.streak || 0) + 1 : 1;
        record.bestStreak = Math.max(record.bestStreak || 0, record.streak);
        record.lastAllDay = record.day;
    }
    dqSave(currentPlayerId, record);
    try {
        server.UpdatePlayerStatistics({ PlayFabId: currentPlayerId, Statistics: [{ StatisticName: DQ_STAT, Value: record.total }] });
    } catch (e) { }
    var granted = server.AddUserVirtualCurrency({ PlayFabId: currentPlayerId, VirtualCurrency: DQ_CURRENCY, Amount: reward + bonus });
    return { ok: true, reward: reward, bonus: bonus, balance: granted.Balance, total: record.total, streak: dqStreak(record, now) };
};

// end of daily quests
