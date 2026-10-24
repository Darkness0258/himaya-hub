package com.himaya.agent

import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.IOException
import java.util.concurrent.TimeUnit

/** [Http] over OkHttp. Responses are always closed (`use`), which the first version forgot: it leaked a connection per call. */
class OkHttpTransport : Http {
    private val client = OkHttpClient.Builder()
        .connectTimeout(5, TimeUnit.SECONDS)
        .readTimeout(20, TimeUnit.SECONDS)
        .writeTimeout(20, TimeUnit.SECONDS)
        .retryOnConnectionFailure(true)
        .build()

    private val jsonType = "application/json; charset=utf-8".toMediaType()

    private fun builder(url: String, headers: Map<String, String>): Request.Builder {
        val request = try {
            Request.Builder().url(url)
        } catch (e: IllegalArgumentException) {
            throw IOException("That is not a valid hub address: $url")
        }
        for ((name, value) in headers) request.header(name, value)
        return request
    }

    override fun request(method: String, url: String, headers: Map<String, String>, jsonBody: String?): Http.Reply {
        val request = builder(url, headers)
        val needsBody = method == "POST" || method == "PUT" || method == "PATCH"
        val body = when {
            jsonBody != null -> jsonBody.toRequestBody(jsonType)
            needsBody -> "".toRequestBody(null)
            else -> null
        }
        request.method(method, body)
        client.newCall(request.build()).execute().use { response ->
            return Http.Reply(response.code, response.body?.string() ?: "")
        }
    }

    override fun upload(url: String, headers: Map<String, String>, field: String, filename: String, mime: String, bytes: ByteArray): Http.Reply {
        val multipart = MultipartBody.Builder()
            .setType(MultipartBody.FORM)
            .addFormDataPart(field, filename, bytes.toRequestBody(mime.toMediaType()))
            .build()
        val request = builder(url, headers).method("POST", multipart)
        client.newCall(request.build()).execute().use { response ->
            return Http.Reply(response.code, response.body?.string() ?: "")
        }
    }
}
