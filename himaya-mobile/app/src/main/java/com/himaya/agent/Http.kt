package com.himaya.agent

import java.io.IOException

/**
 * The tiny slice of HTTP the agent needs. The Android build uses OkHttp ([OkHttpTransport]); tests use
 * plain `HttpURLConnection`, so the hub protocol code in [HubClient] can be exercised on a normal JVM
 * against a real hub.
 */
interface Http {
    class Reply(val code: Int, val body: String)

    @Throws(IOException::class)
    fun request(method: String, url: String, headers: Map<String, String>, jsonBody: String? = null): Reply

    @Throws(IOException::class)
    fun upload(url: String, headers: Map<String, String>, field: String, filename: String, mime: String, bytes: ByteArray): Reply
}
