package com.himaya.agent

import android.app.ActivityManager
import android.app.NotificationManager
import android.app.Service
import android.app.admin.DevicePolicyManager
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import android.os.Process
import org.json.JSONObject
import java.net.Inet4Address
import java.net.NetworkInterface
import java.util.concurrent.Executors
import java.util.concurrent.ScheduledExecutorService
import java.util.concurrent.TimeUnit

/**
 * The long-running part of the agent. It shows the persistent "Himaya is active" notification (visible, not
 * hidden) and keeps the phone in step with what the parent asked for.
 *
 * Fixed compared to the first version:
 *  - the monitoring loops start exactly once (every `onStartCommand` used to launch a fresh set, and the app,
 *    the boot receiver and the activity all started the service);
 *  - no hard-coded IP address: it reports the phone's real Wi-Fi address;
 *  - lock / pause are *desired state* from the hub, re-applied until the hub says otherwise, so a missed
 *    command cannot leave the phone out of sync;
 *  - the VPN guard no longer flags Himaya's own website-filter VPN;
 *  - erasing needs the hub's typed confirmation AND Device admin;
 *  - a screenshot request becomes a notification the child must approve (Android forbids a background
 *    service from opening the screen-capture dialog, and a silent capture would not be consent).
 */
class AgentService : Service() {

    companion object {
        const val ACTION_START = "com.himaya.agent.START"
        const val ACTION_STOP = "com.himaya.agent.STOP"
        const val AGENT_VERSION = "2.0.0"
        private val PACKAGE_NAME = Regex("^[A-Za-z0-9_.]{3,120}$")

        @Volatile var running = false

        fun start(context: Context) {
            context.startForegroundService(Intent(context, AgentService::class.java).setAction(ACTION_START))
        }

        fun stop(context: Context) {
            context.stopService(Intent(context, AgentService::class.java))
        }
    }

    private var executor: ScheduledExecutorService? = null
    private val client = HubClient(OkHttpTransport())

    @Volatile private var state = HubState.NONE
    @Volatile private var connected = false
    @Volatile private var authOk = true
    @Volatile private var shownStatus = ""
    private var knownVpns: Set<String> = emptySet()
    private var reportedNoAdmin = false

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        Notifications.ensureChannels(this)
        enterForeground(statusText())
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) {
            stopSelf()
            return START_NOT_STICKY
        }
        enterForeground(statusText())
        if (!PreferenceManager.isPaired(this)) {
            stopSelf()
            return START_NOT_STICKY
        }
        running = true
        startLoops()
        return START_STICKY
    }

    private fun enterForeground(text: String) {
        val notification = Notifications.status(this, text)
        if (Build.VERSION.SDK_INT >= 29) {
            startForeground(Notifications.ID_STATUS, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
        } else {
            startForeground(Notifications.ID_STATUS, notification)
        }
        shownStatus = text
    }

    /** Start the loops once. Calling this again (the service is started from several places) does nothing. */
    @Synchronized
    private fun startLoops() {
        if (executor != null) return
        val pool = Executors.newScheduledThreadPool(3)
        executor = pool
        pool.scheduleWithFixedDelay(guarded { heartbeat() }, 0, 20, TimeUnit.SECONDS)
        pool.scheduleWithFixedDelay(guarded { pollCommands() }, 2, 5, TimeUnit.SECONDS)
        pool.scheduleWithFixedDelay(guarded { enforce() }, 3, 5, TimeUnit.SECONDS)
        pool.scheduleWithFixedDelay(guarded { checkVpns() }, 6, 20, TimeUnit.SECONDS)
    }

    /** A scheduled task that throws is silently cancelled forever, so every task catches everything. */
    private fun guarded(task: () -> Unit): Runnable = Runnable {
        try {
            syncClient()
            task()
        } catch (e: AuthRejectedException) {
            onAuthRejected()
        } catch (e: Throwable) {
            android.util.Log.w("Himaya", "agent task failed", e)
        }
    }

    private fun syncClient() {
        client.hubUrl = PreferenceManager.hubUrl(this)
        client.agentKey = PreferenceManager.agentKey(this)
    }

    private fun deviceId(): String = PreferenceManager.deviceId(this)

    private fun adminComponent() = ComponentName(this, DeviceAdminReceiver::class.java)

    private fun adminActive(): Boolean = getSystemService(DevicePolicyManager::class.java)?.isAdminActive(adminComponent()) == true

    // ------------------------------------------------------------------ hub conversation

    private fun heartbeat() {
        val reply = client.heartbeat(deviceId(), localIp(), capabilities(), AGENT_VERSION)
        if (reply == null) {
            setConnected(false)
            return
        }
        authOk = true
        setConnected(true)
        if (reply.dnsPort != null) PreferenceManager.setDnsPort(this, reply.dnsPort)
        applyState(reply.state)
    }

    private fun pollCommands() {
        val reply = client.commands(deviceId()) ?: return
        reply.state?.let { applyState(it) }
        for (command in reply.commands) {
            try {
                execute(command)
            } catch (e: Exception) {
                android.util.Log.w("Himaya", "command ${command.action} failed", e)
            }
        }
    }

    private fun execute(command: HubCommand) {
        when (command.action) {
            "push_notification" -> {
                val text = command.payload.optString("message").take(500)
                if (text.isNotBlank()) Notifications.message(this, text)
            }
            "force_close_app" -> closeApp(command.payload.optString("app"))
            "snapshot" -> Notifications.screenRequest(this)
            "wipe" -> wipe(command.payload.optBoolean("confirmed"))
            // lock / unlock / pause / unpause arrive as *state* (heartbeat and command poll) and are enforced in enforce()
        }
    }

    private fun closeApp(name: String) {
        val pkg = name.trim()
        if (!PACKAGE_NAME.matches(pkg) || pkg == packageName) {
            notice("Refused to close \"$pkg\".")
            return
        }
        getSystemService(ActivityManager::class.java)?.killBackgroundProcesses(pkg)
    }

    private fun wipe(confirmed: Boolean) {
        if (!confirmed) return
        if (!adminActive()) {
            notice("Erase needs Device admin to be turned on in the Himaya app.")
            return
        }
        getSystemService(DevicePolicyManager::class.java)?.wipeData(0)
    }

    private fun notice(message: String) {
        client.reportEvent(deviceId(), "enforcement_notice", JSONObject().put("message", message))
    }

    // ------------------------------------------------------------------ desired state

    private fun applyState(newState: HubState) {
        state = newState
        VpnAgent.blockAll = newState.paused || newState.bedtimeActive
        refreshNotification()
    }

    private fun setConnected(value: Boolean) {
        if (connected != value) {
            connected = value
            refreshNotification()
        }
    }

    private fun statusText(): String = when {
        !authOk -> "Your parent removed this phone from Himaya"
        !connected && !running -> "Starting"
        !connected -> "Can't reach your hub right now"
        state.locked -> "Locked by your parent"
        state.paused -> "Internet paused by your parent"
        state.bedtimeActive -> "Bedtime: internet is off"
        else -> "Connected to your family's hub"
    }

    private fun refreshNotification() {
        val text = statusText()
        if (text == shownStatus) return
        shownStatus = text
        getSystemService(NotificationManager::class.java)?.notify(Notifications.ID_STATUS, Notifications.status(this, text))
    }

    /** Runs every few seconds: re-apply the lock, and keep the website filter alive. */
    private fun enforce() {
        if (state.locked) {
            if (adminActive()) {
                val power = getSystemService(PowerManager::class.java)
                if (power?.isInteractive == true) getSystemService(DevicePolicyManager::class.java)?.lockNow()
            } else if (!reportedNoAdmin) {
                reportedNoAdmin = true
                notice("This phone cannot be locked: Device admin is off in the Himaya app.")
            }
        }
        if (PreferenceManager.adminLost(this)) {
            PreferenceManager.setAdminLost(this, false)
            notice("Device admin was turned off on the phone, so it can no longer be locked or erased remotely.")
        }
        if (PreferenceManager.filterLost(this)) {
            PreferenceManager.setFilterLost(this, false)
            notice("The website filter (VPN) was turned off on the phone.")
        }
        if (PreferenceManager.filterOn(this) && !VpnAgent.running && VpnAgent.consentIntent(this) == null) VpnAgent.start(this)
    }

    // ------------------------------------------------------------------ VPN guard

    private fun checkVpns() {
        val manager = getSystemService(ConnectivityManager::class.java) ?: return
        val found = ArrayList<String>()
        @Suppress("DEPRECATION")
        for (network in manager.allNetworks) {
            val caps = manager.getNetworkCapabilities(network) ?: continue
            if (!caps.hasTransport(NetworkCapabilities.TRANSPORT_VPN)) continue
            if (Build.VERSION.SDK_INT >= 31 && caps.ownerUid == Process.myUid()) continue // Himaya's own filter
            found.add(manager.getLinkProperties(network)?.interfaceName ?: "vpn")
        }
        // Before Android 12 the owner is unknown: if our filter is up, assume one VPN network is ours.
        if (Build.VERSION.SDK_INT < 31 && VpnAgent.running && found.isNotEmpty()) found.removeAt(0)
        val now = found.toSet()
        for (name in now - knownVpns) client.reportVpn(deviceId(), name)
        knownVpns = now
    }

    // ------------------------------------------------------------------ helpers

    private fun capabilities(): JSONObject {
        val admin = adminActive()
        return JSONObject()
            .put("os", "android")
            .put("sdk", Build.VERSION.SDK_INT)
            .put("lock", admin)
            .put("wipe", admin)
            .put("vpn_dns", VpnAgent.running)
            .put("pause", "dns")
            .put("screenshots", "on-request")
    }

    private fun localIp(): String? = try {
        NetworkInterface.getNetworkInterfaces()
            ?.toList()
            ?.filter { it.isUp && !it.isLoopback }
            ?.flatMap { it.inetAddresses.toList() }
            ?.firstOrNull { it is Inet4Address && it.isSiteLocalAddress }
            ?.hostAddress
    } catch (e: Exception) {
        null
    }

    /** The hub no longer knows this phone: let go of everything so the phone is never left locked or offline. */
    private fun onAuthRejected() {
        if (!authOk) return
        authOk = false
        connected = false
        state = HubState.NONE
        VpnAgent.blockAll = false
        PreferenceManager.setRemovedByHub(this, true)
        VpnAgent.stop(this)
        Notifications.message(this, "Your parent removed this phone from Himaya. Locks and internet pauses are released.")
        refreshNotification()
    }

    override fun onDestroy() {
        running = false
        VpnAgent.blockAll = false
        executor?.shutdownNow()
        executor = null
        super.onDestroy()
    }
}
