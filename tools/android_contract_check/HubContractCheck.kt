/**
 * Runs the Android app's real HubClient + DnsPacket code on a normal JVM against a LIVE hub.
 * It proves the Kotlin client and the Python hub agree on the API (the original app and hub did not).
 *
 * Usage (see run.sh):  HUB=http://127.0.0.1:8000 ADMIN_KEY=hma_... OUT=/tmp/dnscheck java -cp ... HubContractCheckKt
 */
import com.himaya.agent.AuthRejectedException
import com.himaya.agent.DnsPacket
import com.himaya.agent.HubClient
import com.himaya.agent.JvmTransport
import com.himaya.agent.PairOutcome
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

private var checks = 0
private fun check(label: String, condition: Boolean) {
    checks++
    println((if (condition) "  ok    " else "  FAIL  ") + label)
    if (!condition) { println("\nCONTRACT CHECK FAILED"); System.exit(1) }
}

fun main() {
    val hub = System.getenv("HUB") ?: error("set HUB")
    val admin = mapOf("X-API-Key" to (System.getenv("ADMIN_KEY") ?: error("set ADMIN_KEY")))
    val http = JvmTransport()
    fun parent(method: String, path: String, body: JSONObject? = null) = http.request(method, hub + path, admin, body?.toString())

    println("== pairing with the PIN the dashboard would show ==")
    val pin = JSONObject(parent("GET", "/enroll/info").body).getString("pin")
    val client = HubClient(http, hub)
    val bad = client.pair(hub, if (pin == "000000") "111111" else "000000", "Pixel 7", "child")
    check("a wrong PIN is WrongPin", bad is PairOutcome.WrongPin)
    val outcome = client.pair(hub, pin, "Pixel 7", "child")
    check("the right PIN pairs", outcome is PairOutcome.Success)
    val paired = (outcome as PairOutcome.Success).result
    check("the hub assigned the id (android-xxxx) and the app keeps it", paired.deviceId.startsWith("android-"))
    check("the key looks like an agent key", paired.agentKey.startsWith("hag_"))
    check("the PIN was consumed", client.pair(hub, pin, "Again", "child") is PairOutcome.WrongPin)
    client.agentKey = paired.agentKey

    println("== heartbeat ==")
    val caps = JSONObject().put("os", "android").put("lock", true).put("vpn_dns", false).put("pause", "dns").put("screenshots", "on-request").put("wipe", true)
    val beat = client.heartbeat(paired.deviceId, "192.168.1.77", caps, "2.0.0")
    check("heartbeat accepted", beat != null)
    val device = JSONObject(parent("GET", "/devices/${paired.deviceId}").body)
    check("device is online", device.getString("status") == "online")
    check("the IP in the body reached the hub (the old client's was ignored)", device.getString("ip") == "192.168.1.77")
    check("capabilities reached the hub", device.getJSONObject("caps").getString("pause") == "dns" && device.getString("agent_version") == "2.0.0")

    println("== desired state and commands ==")
    parent("POST", "/admin/${paired.deviceId}/action", JSONObject().put("action", "lock"))
    parent("POST", "/admin/${paired.deviceId}/action", JSONObject().put("action", "pause"))
    parent("POST", "/admin/${paired.deviceId}/action", JSONObject().put("action", "push_notification").put("payload", JSONObject().put("message", "Dinner time")))
    parent("POST", "/admin/${paired.deviceId}/action", JSONObject().put("action", "snapshot"))
    val state = client.heartbeat(paired.deviceId, null, caps, "2.0.0")!!.state
    check("heartbeat reports locked + paused", state.locked && state.paused)
    val commands = client.commands(paired.deviceId)!!
    check("commands arrive exactly as queued", commands.commands.map { it.action }.containsAll(listOf("lock", "pause", "push_notification", "snapshot")))
    check("the message text is intact", commands.commands.first { it.action == "push_notification" }.payload.getString("message") == "Dinner time")
    check("the command queue is then empty", client.commands(paired.deviceId)!!.commands.isEmpty())
    parent("POST", "/admin/${paired.deviceId}/action", JSONObject().put("action", "unlock"))
    check("unlock is reflected", !client.heartbeat(paired.deviceId, null, caps, "2.0.0")!!.state.locked)

    println("== telemetry the parent sees ==")
    check("VPN report accepted", client.reportVpn(paired.deviceId, "tun0"))
    check("blocked-site report accepted", client.reportDnsBlock(paired.deviceId, "https://www.TikTok.com/x"))
    check("agent event accepted", client.reportEvent(paired.deviceId, "enforcement_notice", JSONObject().put("message", "The website filter was turned off on the phone.")))
    val events = JSONArray(parent("GET", "/events?limit=50&device_id=${paired.deviceId}").body)
    val byType = (0 until events.length()).map { events.getJSONObject(it) }.groupBy { it.getString("type") }
    check("vpn_attempt event has the interface", byType["vpn_attempt"]?.first()?.getJSONObject("data")?.getString("interface") == "tun0")
    check("dns_block host was normalised by the hub (the old client sent it where the hub ignored it)", byType["dns_block"]?.first()?.getJSONObject("data")?.getString("host") == "tiktok.com")
    check("enforcement_notice reached the feed", byType.containsKey("enforcement_notice"))

    println("== screenshot upload ==")
    val jpeg = byteArrayOf(0xFF.toByte(), 0xD8.toByte(), 0xFF.toByte(), 0xE0.toByte(), 0, 0x10, 'J'.code.toByte(), 'F'.code.toByte(), 'I'.code.toByte(), 'F'.code.toByte(), 0, 1, 1, 0, 0, 1, 0, 1, 0, 0, 0xFF.toByte(), 0xD9.toByte())
    check("multipart upload accepted", client.uploadScreenshot(paired.deviceId, jpeg))
    val shots = JSONArray(parent("GET", "/snapshots?device_id=${paired.deviceId}").body)
    check("the hub stored it and offers a signed link", shots.length() == 1 && shots.getJSONObject(0).getString("url").contains("sig="))
    val image = http.request("GET", hub + shots.getJSONObject(0).getString("url"), emptyMap())
    check("the signed link serves the bytes back", image.code == 200 && image.body.isNotEmpty())

    println("== a removed device is told so ==")
    parent("DELETE", "/devices/${paired.deviceId}")
    var rejected = false
    try { client.heartbeat(paired.deviceId, null, caps, "2.0.0") } catch (e: AuthRejectedException) { rejected = true }
    check("heartbeat after removal throws AuthRejectedException", rejected)

    println("== DNS packets built by the Kotlin codec (validated afterwards by dnspython) ==")
    val out = File(System.getenv("OUT") ?: "/tmp/dnscheck").also { it.mkdirs() }
    fun query(name: String, type: Int): ByteArray {
        val o = java.io.ByteArrayOutputStream()
        o.write(byteArrayOf(0x12, 0x34, 0x01, 0x00, 0, 1, 0, 0, 0, 0, 0, 0))
        name.split('.').forEach { o.write(it.length); o.write(it.toByteArray()) }
        o.write(0); o.write(byteArrayOf((type shr 8).toByte(), type.toByte(), 0, 1))
        return o.toByteArray()
    }
    for ((label, type) in listOf("a" to 1, "aaaa" to 28, "https" to 65)) {
        File(out, "blocked_$label.hex").writeText(DnsPacket.blockedResponse(query("tiktok.com", type))!!.joinToString("") { "%02x".format(it) })
    }
    File(out, "servfail.hex").writeText(DnsPacket.servFail(query("example.com", 1))!!.joinToString("") { "%02x".format(it) })
    val dns = query("example.com", 1)
    val packet = ByteArray(28 + dns.size).also {
        it[0] = 0x45; it[2] = (it.size shr 8).toByte(); it[3] = it.size.toByte(); it[8] = 64; it[9] = 17
        it[12] = 10; it[13] = 111; it[14] = 0xDE.toByte(); it[15] = 1; it[16] = 10; it[17] = 111; it[18] = 0xDE.toByte(); it[19] = 2
        val s = DnsPacket.checksum(it, 0, 20); it[10] = (s shr 8).toByte(); it[11] = s.toByte()
        it[21] = 0x40; it[23] = 53; it[25] = (8 + dns.size).toByte(); System.arraycopy(dns, 0, it, 28, dns.size)
    }
    val parsed = DnsPacket.parseUdpQuery(packet, packet.size)!!
    File(out, "udp_reply.hex").writeText(DnsPacket.buildUdpResponse(parsed, DnsPacket.blockedResponse(parsed.dns)!!).joinToString("") { "%02x".format(it) })

    println("\nALL $checks CONTRACT CHECKS PASSED")
}
