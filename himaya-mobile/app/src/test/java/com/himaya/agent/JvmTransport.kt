package com.himaya.agent

import java.io.ByteArrayOutputStream
import java.net.HttpURLConnection
import java.net.URL

/** Real HTTP over `HttpURLConnection`: lets the hub protocol code run on a plain JVM against a live hub. */
class JvmTransport : Http {
    private fun read(connection: HttpURLConnection): Http.Reply {
        val code = connection.responseCode
        val stream = if (code >= 400) connection.errorStream else connection.inputStream
        val body = stream?.use { String(it.readBytes(), Charsets.UTF_8) } ?: ""
        return Http.Reply(code, body)
    }

    override fun request(method: String, url: String, headers: Map<String, String>, jsonBody: String?): Http.Reply {
        val connection = URL(url).openConnection() as HttpURLConnection
        connection.requestMethod = method
        connection.connectTimeout = 5000
        connection.readTimeout = 15000
        headers.forEach { (k, v) -> connection.setRequestProperty(k, v) }
        if (jsonBody != null) {
            connection.doOutput = true
            connection.setRequestProperty("Content-Type", "application/json")
            connection.outputStream.use { it.write(jsonBody.toByteArray(Charsets.UTF_8)) }
        }
        return read(connection)
    }

    override fun upload(url: String, headers: Map<String, String>, field: String, filename: String, mime: String, bytes: ByteArray): Http.Reply {
        val boundary = "----himaya" + System.nanoTime()
        val connection = URL(url).openConnection() as HttpURLConnection
        connection.requestMethod = "POST"
        connection.doOutput = true
        connection.setRequestProperty("Content-Type", "multipart/form-data; boundary=$boundary")
        headers.forEach { (k, v) -> connection.setRequestProperty(k, v) }
        val out = ByteArrayOutputStream()
        out.write("--$boundary\r\nContent-Disposition: form-data; name=\"$field\"; filename=\"$filename\"\r\nContent-Type: $mime\r\n\r\n".toByteArray())
        out.write(bytes)
        out.write("\r\n--$boundary--\r\n".toByteArray())
        connection.outputStream.use { it.write(out.toByteArray()) }
        return read(connection)
    }
}
