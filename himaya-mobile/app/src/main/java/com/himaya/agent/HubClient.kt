package com.himaya.agent

import org.json.JSONException
import org.json.JSONObject
import java.io.IOException

/** The hub no longer accepts this device's key (the parent removed the device, or the hub was reset). */
class AuthRejectedException(message: String = "The hub rejected this device's key") : Exception(message)

data class HubState(val locked: Boolean, val paused: Boolean, val bedtimeActive: Boolean) {
    companion object {
        val NONE = HubState(locked = false, paused = false, bedtimeActive = false)
    }
}

data class HeartbeatReply(val state: HubState, val dnsPort: Int?, val snapshotIntervalS: Int)
data class HubCommand(val action: String, val payload: JSONObject)
data class CommandsReply(val commands: List<HubCommand>, val state: HubState?)
data class PairSuccess(val deviceId: String, val agentKey: String, val dnsPort: Int?)

sealed class PairOutcome {
    class Success(val result: PairSuccess) : PairOutcome()
    object WrongPin : PairOutcome()
    class RateLimited(val message: String) : PairOutcome()
    class Unreachable(val message: String) : PairOutcome()
    class Failed(val message: String) : PairOutcome()
}

/**
 * Talks to the hub. Every call is blocking: run it on a background thread.
 *
 * Differences from the first version:
 *  - every agent request carries the per-device key (`X-API-Key`) issued at pairing;
 *  - request bodies are JSON in the shapes the hub validates (the old client sent some values in bodies
 *    the hub ignored, so IPs and blocked hosts were lost);
 *  - pairing returns the hub-assigned device id and key, which the old client discarded;
 *  - responses are always closed (the transport does it), so connections are no longer leaked.
 */
class HubClient(private val http: Http, hubUrl: String = "", var agentKey: String = "") {

    var hubUrl: String = hubUrl.trim().trimEnd('/')
        set(value) {
            field = value.trim().trimEnd('/')
        }

    private fun agentHeaders(): Map<String, String> = mapOf("X-API-Key" to agentKey)

    private fun checkAuth(reply: Http.Reply) {
        if (reply.code == 401 || reply.code == 403) throw AuthRejectedException()
    }

    private fun parseState(json: JSONObject?): HubState? {
        json ?: return null
        return HubState(json.optBoolean("locked"), json.optBoolean("paused"), json.optBoolean("bedtime_active"))
    }

    fun pair(baseUrl: String, pin: String, deviceName: String, ownerType: String): PairOutcome {
        val body = JSONObject()
            .put("pin", pin)
            .put("name", deviceName)
            .put("platform", "android")
            .put("owner_type", ownerType)
        val reply = try {
            http.request("POST", baseUrl.trim().trimEnd('/') + "/enroll/pair", emptyMap(), body.toString())
        } catch (e: IOException) {
            return PairOutcome.Unreachable(e.message ?: "Could not reach the hub")
        }
        return when (reply.code) {
            200 -> try {
                val json = JSONObject(reply.body)
                val dnsPort = if (json.isNull("dns_port")) null else json.optInt("dns_port")
                PairOutcome.Success(PairSuccess(json.getString("device_id"), json.getString("agent_key"), dnsPort))
            } catch (e: JSONException) {
                PairOutcome.Failed("The hub sent an answer this app does not understand. Update the hub and the app.")
            }
            403 -> PairOutcome.WrongPin
            429 -> PairOutcome.RateLimited(detail(reply.body, "Too many wrong PINs. Wait a few minutes."))
            else -> PairOutcome.Failed(detail(reply.body, "The hub refused the request (${reply.code})."))
        }
    }

    private fun detail(body: String, fallback: String): String = try {
        JSONObject(body).optString("detail", fallback).ifBlank { fallback }
    } catch (e: JSONException) {
        fallback
    }

    /** null = the hub could not be reached. Throws [AuthRejectedException] if the key is no longer valid. */
    fun heartbeat(deviceId: String, ip: String?, caps: JSONObject, agentVersion: String): HeartbeatReply? {
        val body = JSONObject().put("caps", caps).put("agent_version", agentVersion)
        if (!ip.isNullOrBlank()) body.put("ip", ip)
        val reply = try {
            http.request("POST", "$hubUrl/agents/$deviceId/heartbeat", agentHeaders(), body.toString())
        } catch (e: IOException) {
            return null
        }
        checkAuth(reply)
        if (reply.code != 200) return null
        return try {
            val json = JSONObject(reply.body)
            HeartbeatReply(
                parseState(json.optJSONObject("state")) ?: HubState.NONE,
                if (json.isNull("dns_port")) null else json.optInt("dns_port"),
                json.optInt("snapshot_interval_s", 300),
            )
        } catch (e: JSONException) {
            null
        }
    }

    fun commands(deviceId: String): CommandsReply? {
        val reply = try {
            http.request("GET", "$hubUrl/agents/$deviceId/commands", agentHeaders())
        } catch (e: IOException) {
            return null
        }
        checkAuth(reply)
        if (reply.code != 200) return null
        return try {
            val json = JSONObject(reply.body)
            val array = json.optJSONArray("commands")
            val list = ArrayList<HubCommand>()
            if (array != null) {
                for (i in 0 until array.length()) {
                    val item = array.getJSONObject(i)
                    list.add(HubCommand(item.optString("action"), item.optJSONObject("payload") ?: JSONObject()))
                }
            }
            CommandsReply(list, parseState(json.optJSONObject("state")))
        } catch (e: JSONException) {
            null
        }
    }

    fun reportVpn(deviceId: String, interfaceName: String): Boolean =
        post("$hubUrl/agents/$deviceId/vpn-attempt", JSONObject().put("interface", interfaceName))

    fun reportDnsBlock(deviceId: String, host: String): Boolean =
        post("$hubUrl/agents/$deviceId/dns-block", JSONObject().put("host", host))

    /** Types the hub accepts from an agent: `agent_stopped` and `enforcement_notice`. */
    fun reportEvent(deviceId: String, type: String, data: JSONObject): Boolean =
        post("$hubUrl/agents/$deviceId/event", JSONObject().put("type", type).put("data", data))

    private fun post(url: String, body: JSONObject): Boolean {
        val reply = try {
            http.request("POST", url, agentHeaders(), body.toString())
        } catch (e: IOException) {
            return false
        }
        checkAuth(reply)
        return reply.code in 200..299
    }

    fun uploadScreenshot(deviceId: String, jpeg: ByteArray): Boolean {
        val reply = try {
            http.upload("$hubUrl/agents/$deviceId/snapshot", agentHeaders(), "file", "screen.jpg", "image/jpeg", jpeg)
        } catch (e: IOException) {
            return false
        }
        checkAuth(reply)
        return reply.code in 200..299
    }
}
