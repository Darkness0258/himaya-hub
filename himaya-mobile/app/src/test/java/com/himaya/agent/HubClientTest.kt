package com.himaya.agent

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test
import java.io.IOException

class HubClientTest {

    /** Records every request and replies from a script (or throws). */
    private class FakeHttp(private val reply: (String, String) -> Http.Reply) : Http {
        class Call(val method: String, val url: String, val headers: Map<String, String>, val body: String?)

        val calls = ArrayList<Call>()
        var uploaded: ByteArray? = null
        var uploadField: String? = null

        override fun request(method: String, url: String, headers: Map<String, String>, jsonBody: String?): Http.Reply {
            calls.add(Call(method, url, headers, jsonBody))
            return reply(method, url)
        }

        override fun upload(url: String, headers: Map<String, String>, field: String, filename: String, mime: String, bytes: ByteArray): Http.Reply {
            calls.add(Call("POST", url, headers, null))
            uploaded = bytes
            uploadField = field
            return reply("POST", url)
        }
    }

    private fun client(http: Http) = HubClient(http, "http://192.168.1.20:8000/", "hag_key")

    @Test
    fun pairingSendsTheShapeTheHubValidatesAndReturnsTheHubAssignedIdentity() {
        val http = FakeHttp { _, _ -> Http.Reply(200, """{"status":"paired","device_id":"android-1a2b3c4d","agent_key":"hag_secret","dns_port":5300}""") }
        val outcome = HubClient(http).pair("http://192.168.1.20:8000/", "123456", "Pixel 7", "child")
        assertTrue(outcome is PairOutcome.Success)
        val success = (outcome as PairOutcome.Success).result
        assertEquals("android-1a2b3c4d", success.deviceId)
        assertEquals("hag_secret", success.agentKey)
        assertEquals(5300, success.dnsPort)
        val call = http.calls.single()
        assertEquals("http://192.168.1.20:8000/enroll/pair", call.url)
        assertFalse(call.headers.containsKey("X-API-Key")) // pairing is authorised by the PIN, not a key
        val body = JSONObject(call.body!!)
        assertEquals("123456", body.getString("pin"))
        assertEquals("android", body.getString("platform"))
        assertEquals("child", body.getString("owner_type"))
        assertFalse(body.has("device_id")) // the client never chooses its own id
    }

    @Test
    fun pairingOutcomes() {
        assertTrue(HubClient(FakeHttp { _, _ -> Http.Reply(403, """{"detail":"nope"}""") }).pair("http://h", "000000", "x", "child") is PairOutcome.WrongPin)
        val limited = HubClient(FakeHttp { _, _ -> Http.Reply(429, """{"detail":"Too many wrong PINs."}""") }).pair("http://h", "000000", "x", "child")
        assertEquals("Too many wrong PINs.", (limited as PairOutcome.RateLimited).message)
        val down = HubClient(object : Http {
            override fun request(method: String, url: String, headers: Map<String, String>, jsonBody: String?): Http.Reply = throw IOException("no route to host")
            override fun upload(url: String, headers: Map<String, String>, field: String, filename: String, mime: String, bytes: ByteArray): Http.Reply = throw IOException()
        }).pair("http://h", "000000", "x", "child")
        assertEquals("no route to host", (down as PairOutcome.Unreachable).message)
        assertTrue(HubClient(FakeHttp { _, _ -> Http.Reply(200, "<html>") }).pair("http://h", "1", "x", "child") is PairOutcome.Failed)
    }

    @Test
    fun heartbeatCarriesTheKeyAndJsonBodyAndReadsTheDesiredState() {
        val http = FakeHttp { _, _ -> Http.Reply(200, """{"status":"ok","state":{"locked":true,"paused":false,"bedtime_active":true},"dns_port":null,"snapshot_interval_s":300}""") }
        val caps = JSONObject().put("os", "android").put("vpn_dns", true)
        val reply = client(http).heartbeat("android-1a2b3c4d", "192.168.1.55", caps, "2.0.0")
        assertNotNull(reply)
        assertEquals(HubState(locked = true, paused = false, bedtimeActive = true), reply!!.state)
        assertNull(reply.dnsPort)
        val call = http.calls.single()
        assertEquals("http://192.168.1.20:8000/agents/android-1a2b3c4d/heartbeat", call.url) // trailing slash of the hub URL is handled
        assertEquals("hag_key", call.headers["X-API-Key"])
        val body = JSONObject(call.body!!)
        assertEquals("192.168.1.55", body.getString("ip")) // sent in the body: the old client's value was silently ignored
        assertTrue(body.getJSONObject("caps").getBoolean("vpn_dns"))
        assertEquals("2.0.0", body.getString("agent_version"))
    }

    @Test
    fun anUnknownIpIsOmittedRatherThanSentBlank() {
        val http = FakeHttp { _, _ -> Http.Reply(200, """{"state":{}}""") }
        client(http).heartbeat("android-1a2b3c4d", null, JSONObject(), "2.0.0")
        assertFalse(JSONObject(http.calls.single().body!!).has("ip"))
    }

    @Test
    fun anUnreachableHubIsNullAndARevokedKeyThrows() {
        val down = object : Http {
            override fun request(method: String, url: String, headers: Map<String, String>, jsonBody: String?): Http.Reply = throw IOException("timeout")
            override fun upload(url: String, headers: Map<String, String>, field: String, filename: String, mime: String, bytes: ByteArray): Http.Reply = throw IOException()
        }
        assertNull(client(down).heartbeat("android-1a2b3c4d", null, JSONObject(), "2.0.0"))
        assertNull(client(down).commands("android-1a2b3c4d"))
        assertFalse(client(down).reportVpn("android-1a2b3c4d", "tun0"))
        val revoked = FakeHttp { _, _ -> Http.Reply(401, """{"detail":"That key is not valid."}""") }
        for (call in listOf<() -> Any?>({ client(revoked).heartbeat("d", null, JSONObject(), "2") }, { client(revoked).commands("d") }, { client(revoked).reportVpn("d", "x") }, { client(revoked).uploadScreenshot("d", ByteArray(3)) })) {
            try {
                call()
                fail("expected AuthRejectedException")
            } catch (expected: AuthRejectedException) {
                // good
            }
        }
    }

    @Test
    fun commandsAreParsedWithPayloadsAndState() {
        val http = FakeHttp { _, _ ->
            Http.Reply(200, """{"device_id":"d","commands":[{"id":1,"action":"push_notification","payload":{"message":"Dinner"}},{"id":2,"action":"snapshot","payload":{}}],"state":{"locked":false,"paused":true,"bedtime_active":false}}""")
        }
        val reply = client(http).commands("android-1a2b3c4d")!!
        assertEquals(listOf("push_notification", "snapshot"), reply.commands.map { it.action })
        assertEquals("Dinner", reply.commands[0].payload.getString("message"))
        assertTrue(reply.state!!.paused)
        assertEquals("GET", http.calls.single().method)
    }

    @Test
    fun reportsUseJsonBodiesInTheHubsFieldNames() {
        val http = FakeHttp { _, _ -> Http.Reply(200, """{"status":"ok"}""") }
        val c = client(http)
        assertTrue(c.reportVpn("d1", "tun0"))
        assertTrue(c.reportDnsBlock("d1", "tiktok.com"))
        assertTrue(c.reportEvent("d1", "enforcement_notice", JSONObject().put("message", "VPN off")))
        assertEquals("tun0", JSONObject(http.calls[0].body!!).getString("interface"))
        assertEquals("tiktok.com", JSONObject(http.calls[1].body!!).getString("host"))
        val event = JSONObject(http.calls[2].body!!)
        assertEquals("enforcement_notice", event.getString("type"))
        assertEquals("VPN off", event.getJSONObject("data").getString("message"))
        assertTrue(http.calls.all { it.headers["X-API-Key"] == "hag_key" })
    }

    @Test
    fun screenshotsAreUploadedAsTheFileField() {
        val http = FakeHttp { _, _ -> Http.Reply(200, """{"status":"ok"}""") }
        assertTrue(client(http).uploadScreenshot("d1", byteArrayOf(1, 2, 3)))
        assertEquals("file", http.uploadField)
        assertEquals(3, http.uploaded!!.size)
        assertEquals("http://192.168.1.20:8000/agents/d1/snapshot", http.calls.single().url)
        assertFalse(HubClient(FakeHttp { _, _ -> Http.Reply(413, "{}") }, "http://h", "k").uploadScreenshot("d1", ByteArray(1)))
    }
}
