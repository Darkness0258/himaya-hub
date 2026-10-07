package com.himaya.agent

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.content.Intent
import android.net.VpnService
import android.os.Build
import android.util.Log

/**
 * VPN service connection helper.
 *
 * ★ Insight ─────────────────────────────────────
 * VpnService.Builder creates a TUN interface that captures all device DNS.
 * We route 0.0.0.0/0 through it, so youtube.com, etc. never reach the
 * internet without going through the hub's filter first.
 * Phase 3 will wire the actual DNS blocking logic here.
 * ──────────────────────────────────────────────────
 */
object VpnConnection {
    private const val TAG = "VpnConnection"

    /** Build and return the VpnService Intent for DNS filter */
    fun buildVpnIntent(context: Context): Intent {
        val builder = VpnService.Builder().apply {
            // TUN interface address
            addAddress("10.0.0.2", 24)
            // DNS servers - use the hub as forwarder
            addDnsServer("127.0.0.1")
            // Route all IPv4 traffic
            addRoute("0.0.0.0", 0)
            // Exclude local subnets
            excludeRoute("192.168", 0)
            excludeRoute("10", 0)
        }

        return VpnService.prepare(context).let { prepareIntent ->
            if (prepareIntent != null) {
                // Need user consent to establish VPN
                prepareIntent
            } else {
                // Already connected
                Intent(context, VpnAgent::class.java)
            }
        }.apply { setAction(VpnAgent.ACTION_START) }
    }

    /** Start a foreground VPN connection */
    @Suppress("DEPRECATION")
    fun startForeground(context: Context) {
        val notification = createNotification(context)
        val serviceIntent = Intent(context, VpnAgent::class.java)
        serviceIntent.setAction(VpnAgent.ACTION_START)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            context.startForegroundService(serviceIntent)
        } else {
            context.startService(serviceIntent)
        }
    }

    /** Stop the VPN */
    fun stopForeground(context: Context) {
        context.sendBroadcast(Intent(context, VpnAgent::class.java).apply {
            action = VpnAgent.ACTION_STOP
        })
    }

    /** Create the persistent notification for foreground VPN */
    fun createNotification(context: Context): Notification {
        val channelId = "himaya_vpn_channel"

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                channelId,
                "Himaya VPN Filter",
                NotificationManager.IMPORTANCE_LOW
            )
            val manager = context.getSystemService(NotificationManager::class.java)
            manager.createNotificationChannel(channel)
        }

        return Notification.Builder(context, channelId)
            .setContentTitle("Himaya Agent")
            .setContentText("DNS filtering active")
            .setSmallIcon(android.R.drawable.ic_lock_idle_alarm)
            .setOngoing(true)
            .build()
    }
}

/**
 * Foreground VPN service.
 * Extends VpnService to intercept all DNS traffic.
 */
class VpnAgent : VpnService() {

    companion object {
        const val ACTION_START = "com.himaya.agent.START_VPN"
        const val ACTION_STOP = "com.himaya.agent.STOP_VPN"
        private const val TAG = "VpnAgent"
    }

    private val mAglConnection: android.net.DNSServerAger? = null

    override fun onCreate() {
        super.onCreate()
        Log.i(TAG, "VPN service created")
    }

    override fun onPrepare(intent: Intent?): Int {
        // Return RESULT_OK to allow VPN connection
        return android.net.VpnService.RESULT_OK
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val action = intent?.action

        when (action) {
            ACTION_START -> {
                startVpn()
            }
            ACTION_STOP -> {
                stopSelf()
            }
        }

        return START_NOT_STICKY
    }

    private fun startVpn() {
        val builder = VpnService.Builder().apply {
            addAddress("10.0.0.2", 24)
            addDnsServer("1.1.1.1")
            addRoute("0.0.0.0", 0)
        }

        val exitInfo = builder.establish()
        Log.i(TAG, "VPN established: $exitInfo")

        // Start foreground with notification
        val notification = VpnConnection.createNotification(this)
        startForeground(1, notification)
    }

    override fun onConnected() {
        super.onConnected()
        Log.i(TAG, "VPN connected")
    }

    override fun onDisconnected() {
        super.onDisconnected()
        Log.i(TAG, "VPN disconnected")
        stopSelf()
    }

    override fun onDestroy() {
        super.onDestroy()
        Log.i(TAG, "VPN service destroyed")
    }
}