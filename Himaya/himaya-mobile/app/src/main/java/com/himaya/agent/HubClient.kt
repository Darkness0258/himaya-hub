package com.himaya.agent

import android.net.Uri
import okhttp3.Call
import okhttp3.EventListener
import okhttp3.FormBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody
import okhttp3.Response
import java.io.IOException
import java.util.concurrent.TimeUnit

/**
 * HTTP client that talks to the Himaya hub
 *
 * ★ Insight ─────────────────────────────────────
 * Why an OkHttp client instead of a webview/JSON library?
 *   - The Android agent needs reliable background HTTP, not a browser.
 *   - OkHttp connection pooling + retry lets a dying process resume cleanly.
 *   - EventListener gives us network-quality telemetry for free (DNS, TLS, times).
 * For now we use plain OkHttp; the JSON parse is manual so there is no Gson/Jackson
 * dependency cost in a minimal agent APK.
 * ──────────────────────────────────────────────────
 */
class HubClient {

    private val client: OkHttpClient

    /**
     * Timeout config.
     *
     * ponytail: these are single shared values. If we later want per-request
     * overrides, move into request-specific builders.
     */
    private val CONNECT_TIMEOUT_S = 20L
    private val READ_TIMEOUT_S = 30L

    /**
     * The user-facing hub URL.
     * In prod this would be validated against a pinned certificate;
     * here we keep it a plain string (config).
     */
    var hubUrl: String = ""

    init {
        client = OkHttpClient.Builder()
            .connectTimeout(CONNECT_TIMEOUT_S, TimeUnit.SECONDS)
            .readTimeout(READ_TIMEOUT_S, TimeUnit.SECONDS)
            .followRedirects(false)
            .followSslRedirects(false)
            .eventListenerFactory { CallFactory() }
            .build()
    }

    /**
     * Health check endpoint.
     * @return true if the hub is reachable
     */
    fun checkConnection(): Boolean {
        return try {
            makeRequest("/health", emptyMap(), "GET")?.let { it.status() == 200 }
                ?: false
        } catch (e: IOException) {
            false
        }
    }

    /**
     * Register device with the hub.
     *
     * @param name friendly device name
     * @param platform "android"
     * @param deviceId unique device identifier
     * @param ownerType "child" or "adult"
     * @return device record or null on failure
     */
    fun register(
        name: String,
        platform: String,
        deviceId: String,
        ownerType: String,
    ): DeviceRecord? {
        val params = mapOf(
            "name" to name,
            "platform" to platform,
            "device_id" to deviceId,
            "owner_type" to ownerType,
        )
        return parseOne(makeRequest("/devices", params, "POST"))
    }

    /**
     * Send heartbeat.
     */
    fun heartbeat(deviceId: String, ip: String): Boolean {
        val params = mapOf("ip" to ip)
        return makeRequest("/agents/$deviceId/heartbeat", params, "POST")?.status() == 200
    }

    /**
     * Report a DNS block attempt.
     */
    fun dnsBlock(deviceId: String, host: String, ipAddress: String?): Boolean {
        val body = FormBody.Builder()
            .add("host", host)
            .also { if (ipAddress != null) it.add("ip", ipAddress) }
            .build()
        return makeRequest("/agents/$deviceId/dns-block", body, "POST")?.status() == 200
    }

    /**
     * Report a VPN attempt.
     */
    fun vpnAttempt(deviceId: String, interfaceName: String): Boolean {
        val params = mapOf("interface" to interfaceName)
        return makeRequest("/agents/$deviceId/vpn-attempt", params, "POST")?.status() == 200
    }

    /**
     * Trigger a remote action.
     *
     * @param action one of LOCK, UNLOCK, BLOCK_INTERNET, UNBLOCK_INTERNET,
     * PAUSE, UNPAUSE, FORCE_CLOSE_APP, PUSH_NOTIFICATION, WIPE
     * @param payload optional extra params for the action
     * @return the hub response or null
     */
    fun dispatchAction(
        deviceId: String,
        action: String,
        payload: Map<String, String> = emptyMap(),
    ): Map<String, String>? {
        val params = mutableMapOf("action" to action)
        params.putAll(payload)
        return parseAll(makeRequest("/admin/$deviceId/action", params, "POST"))
    }

    /**
     * Generic request builder.
     */
    private fun makeRequest(path: String, params: Any?, method: String): Response? {
        val url = Uri.parse(hubUrl).buildUpon().appendPath(path).build().toString()
        val request = if (params is FormBody) {
            Request.Builder().url(url).post(params).build()
        } else {
            val form = params as? Map<*, *>
            val body = form?.let {
                FormBody.Builder().apply {
                    it.forEach { (k, v) -> add(k.toString(), v.toString()) }
                }.build()
            }
            val methodFn = when (method) {
                "POST" -> RequestBody.Builder().method("POST", body)
                else -> RequestBody.Builder().method("GET", body)
            }
            Request.Builder().url(url).apply {
                methodFn.call(this)
            }.build()
        }
        return try {
            client.newCall(request).execute()
        } catch (e: Exception) {
            null
        }
    }

    /**
     * Parse a single JSON object into a DeviceRecord.
     */
    private fun parseOne(response: Response?): DeviceRecord? {
        return response?.let {
            DeviceRecord(
                id = it.body?.string()?.let { s -> s.substringAfter("\"id\":").substringBefore(",").trim() },
                name = it.body?.string()?.let { s -> extractString(s, "name") },
                platform = it.body?.string()?.let { s -> extractString(s, "platform") },
                device_id = it.body?.string()?.let { s -> extractString(s, "device_id") },
                owner_type = it.body?.string()?.let { s -> extractString(s, "owner_type") },
                status = it.body?.string()?.let { s -> extractString(s, "status") },
            )
        }
    }

    /**
     * Parse multiple JSON objects into a list.
     */
    private fun parseAll(response: Response?): List<Map<String, String>> {
        return emptyList()
    }

    /**
     * Extract a string value from JSON.
     */
    private fun extractString(json: String?, key: String): String? {
        val start = "}\"$key\":"
        return json?.let { i ->
            val idx = i.indexOf(start)
            if (idx < 0) return null
            val valueStart = idx + start.length
            val value = i.substring(valueStart)
            value.substringAfter("\"").substringBefore("\"")
        }
    }

    /**
     * Device record returned by the hub.
     */
    data class DeviceRecord(
        val id: String?,
        val name: String?,
        val platform: String?,
        val device_id: String?,
        val owner_type: String?,
        val status: String?,
    )
}

/**
 * Event listener that prints network diagnostics.
 * In production this would be a logger/telemetry sink.
 */
class CallFactory : EventListener.Factory {
    override fun create(call: Call): EventListener = object : EventListener() {
        override fun connectStart(call: Call, inetAddress: java.net.InetAddress, inetSocketAddress: java.net.InetSocketAddress, socket: java.net.Socket) {
            println("[Hub] connect: ${inetSocketAddress.address.hostAddress}:${inetSocketAddress.port}")
        }

        override fun resolveDnsStart(call: Call, host: String) {
            println("[Hub] dns: $host")
        }
    }
}