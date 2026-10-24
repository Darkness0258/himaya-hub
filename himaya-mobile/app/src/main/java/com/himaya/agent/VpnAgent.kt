package com.himaya.agent

import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.net.VpnService
import android.os.ParcelFileDescriptor
import java.io.FileInputStream
import java.io.FileOutputStream
import java.io.IOException
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors

/**
 * Website filter: a DNS-only VPN.
 *
 * Only ONE route enters the tunnel (the fake DNS server address), so nothing but DNS lookups are touched
 * and the phone's internet keeps working normally. Every lookup is forwarded to the hub's DNS filter, which
 * applies the parent's rules for this phone; if the hub does not answer, a family-safe public resolver is used.
 * While the parent has paused the phone (or bedtime is active) lookups are answered locally with the
 * sinkhole address, so a pause holds even when the hub cannot be reached.
 *
 * The first version routed ALL traffic (0.0.0.0/0) into a tunnel nobody read, which would have cut the
 * phone's internet the moment it was started. Himaya's own app is excluded from the tunnel so the agent can
 * always reach the hub, including to be told to un-pause.
 */
class VpnAgent : VpnService() {

    companion object {
        const val ACTION_START = "com.himaya.agent.VPN_START"
        const val ACTION_STOP = "com.himaya.agent.VPN_STOP"
        private const val TUN_ADDRESS = "10.111.222.1"
        private const val FAKE_DNS = "10.111.222.2"
        private const val FALLBACK_DNS = "1.1.1.3" // Cloudflare "family" resolver: blocks malware and adult content

        @Volatile var running = false
        @Volatile var blockAll = false

        /** Non-null means the user still has to approve the VPN in the system dialog. */
        fun consentIntent(context: Context): Intent? = prepare(context)

        fun start(context: Context) {
            context.startService(Intent(context, VpnAgent::class.java).setAction(ACTION_START))
        }

        fun stop(context: Context) {
            context.startService(Intent(context, VpnAgent::class.java).setAction(ACTION_STOP))
        }
    }

    private var tunnel: ParcelFileDescriptor? = null
    private var reader: Thread? = null
    private var workers: ExecutorService? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) {
            shutdown()
            stopSelf()
            return START_NOT_STICKY
        }
        startTunnel()
        return START_STICKY
    }

    private fun startTunnel() {
        if (running) return
        val builder = Builder()
            .setSession("Himaya website filter")
            .addAddress(TUN_ADDRESS, 32)
            .addDnsServer(FAKE_DNS)
            .addRoute(FAKE_DNS, 32) // DNS only. Deliberately NOT 0.0.0.0/0.
            .setMtu(1500)
            .setBlocking(true)
        try {
            builder.addDisallowedApplication(packageName) // the agent must always reach the hub
        } catch (e: PackageManager.NameNotFoundException) {
            // cannot happen for our own package
        }
        val descriptor = builder.establish()
        if (descriptor == null) { // permission was revoked
            PreferenceManager.setFilterOn(this, false)
            return
        }
        tunnel = descriptor
        running = true
        PreferenceManager.setFilterOn(this, true)
        workers = Executors.newFixedThreadPool(6)
        reader = Thread({ readLoop(descriptor) }, "himaya-dns-vpn").also { it.start() }
    }

    private fun readLoop(descriptor: ParcelFileDescriptor) {
        val input = FileInputStream(descriptor.fileDescriptor)
        val output = FileOutputStream(descriptor.fileDescriptor)
        val buffer = ByteArray(32767)
        try {
            while (running) {
                val length = input.read(buffer)
                if (length < 0) break
                if (length == 0) continue
                val query = DnsPacket.parseUdpQuery(buffer, length) ?: continue // parse copies what it needs
                workers?.execute { answer(query, output) }
            }
        } catch (e: IOException) {
            // the tunnel was closed
        } finally {
            if (running) { // closed from outside (the user turned the VPN off)
                shutdown()
            }
        }
    }

    private fun answer(query: DnsPacket.UdpQuery, output: FileOutputStream) {
        val dns = query.dns
        val reply: ByteArray? = if (blockAll) {
            DnsPacket.blockedResponse(dns)
        } else {
            forwardToHub(dns) ?: exchange(dns, FALLBACK_DNS, 53) ?: DnsPacket.servFail(dns)
        }
        if (reply == null) return
        val packet = DnsPacket.buildUdpResponse(query, reply)
        try {
            synchronized(output) { output.write(packet) }
        } catch (e: IOException) {
            // tunnel closing
        }
    }

    private fun forwardToHub(dns: ByteArray): ByteArray? {
        val port = PreferenceManager.dnsPort(this)
        if (port <= 0) return null
        val host = Uri.parse(PreferenceManager.hubUrl(this)).host ?: return null
        return exchange(dns, host, port)
    }

    /** One DNS round trip over a socket that bypasses the tunnel (otherwise the query would loop back into it). */
    private fun exchange(dns: ByteArray, host: String, port: Int): ByteArray? {
        var socket: DatagramSocket? = null
        return try {
            socket = DatagramSocket()
            protect(socket)
            socket.soTimeout = 2000
            socket.send(DatagramPacket(dns, dns.size, InetAddress.getByName(host), port))
            val buffer = ByteArray(4096)
            val response = DatagramPacket(buffer, buffer.size)
            socket.receive(response)
            val bytes = buffer.copyOf(response.length)
            if (bytes.size >= 2 && bytes[0] == dns[0] && bytes[1] == dns[1]) bytes else null // must answer THIS query
        } catch (e: IOException) {
            null
        } finally {
            socket?.close()
        }
    }

    private fun shutdown() {
        running = false
        PreferenceManager.setFilterOn(this, false)
        try {
            tunnel?.close()
        } catch (e: IOException) {
            // already closed
        }
        tunnel = null
        reader?.interrupt()
        reader = null
        workers?.shutdownNow()
        workers = null
    }

    /** The user switched the VPN off, or another VPN app took over. */
    override fun onRevoke() {
        PreferenceManager.setFilterLost(this, true)
        shutdown()
        super.onRevoke()
    }

    override fun onDestroy() {
        shutdown()
        super.onDestroy()
    }
}
