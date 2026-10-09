package com.himaya.agent

import android.net.Uri
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.util.concurrent.TimeUnit

/**
 * Robust HTTP client that communicates with the Himaya hub.
 */
class HubClient {

    private val JSON_MEDIA_TYPE = "application/json; charset=utf-8".toMediaTypeOrNull()

    private val client: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(15L, TimeUnit.SECONDS)
        .readTimeout(20L, TimeUnit.SECONDS)
        .retryOnConnectionFailure(true)
        .build()

    var hubUrl: String = ""

    fun checkConnection(): Boolean {
        return try {
            val res = get("/health")
            res?.isSuccessful == true
        } catch (e: Exception) {
            false
        }
    }

    fun register(
        name: String,
        platform: String,
        deviceId: String,
        ownerType: String
    ): Boolean {
        val json = JSONObject().apply {
            put("name", name)
            put("platform", platform)
            put("device_id", deviceId)
            put("owner_type", ownerType)
        }
        val res = post("/devices", json.toString())
        return res?.isSuccessful == true
    }

    fun pairWithPin(
        pin: String,
        name: String,
        platform: String = "android"
    ): Boolean {
        val json = JSONObject().apply {
            put("pin", pin)
            put("name", name)
            put("platform", platform)
            put("owner_type", "child")
        }
        val res = post("/enroll/pair", json.toString())
        return res?.isSuccessful == true
    }

    fun heartbeat(deviceId: String, ip: String): Boolean {
        val json = JSONObject().apply {
            put("ip", ip)
        }
        val res = post("/agents/$deviceId/heartbeat", json.toString())
        return res?.isSuccessful == true
    }

    fun getPendingCommands(deviceId: String): List<JSONObject> {
        val res = get("/agents/$deviceId/commands") ?: return emptyList()
        val list = mutableListOf<JSONObject>()
        try {
            val bodyStr = res.body?.string() ?: return emptyList()
            val root = JSONObject(bodyStr)
            val arr = root.optJSONArray("commands") ?: JSONArray()
            for (i in 0 until arr.length()) {
                val obj = arr.optJSONObject(i)
                if (obj != null) list.add(obj)
            }
        } catch (e: Exception) {
            // error parsing commands
        }
        return list
    }

    fun reportDnsBlock(deviceId: String, host: String): Boolean {
        val json = JSONObject().apply {
            put("host", host)
        }
        val res = post("/agents/$deviceId/dns-block", json.toString())
        return res?.isSuccessful == true
    }

    fun reportVpnAttempt(deviceId: String, iface: String): Boolean {
        val json = JSONObject().apply {
            put("interface", iface)
        }
        val res = post("/agents/$deviceId/vpn-attempt", json.toString())
        return res?.isSuccessful == true
    }

    fun policySync(deviceId: String, rules: Map<String, Any>): Boolean {
        val json = JSONObject(rules)
        val res = post("/agents/$deviceId/policy-sync", json.toString())
        return res?.isSuccessful == true
    }

    private fun post(path: String, jsonBody: String): Response? {
        if (hubUrl.isEmpty()) return null
        return try {
            val cleanBase = hubUrl.trimEnd('/')
            val cleanPath = path.trimStart('/')
            val fullUrl = "$cleanBase/$cleanPath"

            val body = jsonBody.toRequestBody(JSON_MEDIA_TYPE)
            val request = Request.Builder()
                .url(fullUrl)
                .post(body)
                .build()
            client.newCall(request).execute()
        } catch (e: Exception) {
            null
        }
    }

    private fun get(path: String): Response? {
        if (hubUrl.isEmpty()) return null
        return try {
            val cleanBase = hubUrl.trimEnd('/')
            val cleanPath = path.trimStart('/')
            val fullUrl = "$cleanBase/$cleanPath"

            val request = Request.Builder()
                .url(fullUrl)
                .get()
                .build()
            client.newCall(request).execute()
        } catch (e: Exception) {
            null
        }
    }
}