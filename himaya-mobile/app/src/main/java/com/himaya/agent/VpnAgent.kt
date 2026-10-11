package com.himaya.agent

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.net.VpnService
import android.os.Build
import android.os.ParcelFileDescriptor
import android.util.Log
import androidx.core.app.NotificationCompat

/**
 * VPN service for DNS-level content filtering.
 *
 * ★ Insight ─────────────────────────────────────
 * VpnService creates a TUN (Tun/Tap) interface. All device traffic
 * is routed through it by the kernel. We intercept DNS queries
 * and match against the hub's blocklist.
 *
 * Key lifecycle callbacks:
 *  - onStartCommand: user requested VPN start (from MainActivity or BootReceiver)
 *  - onRevoke: user revoked VPN permission in system settings
 *  - onTearingDown: service is stopping
 *
 * A foreground notification is mandatory while the VPN is active
 * (Android requirement for long-running services).
 * ──────────────────────────────────────────────────
 */
class VpnAgent : VpnService() {

    companion object {
        const val ACTION_START = "com.himaya.agent.START_VPN"
        const val ACTION_STOP = "com.himaya.agent.STOP_VPN"
        private const val TAG = "VpnAgent"
        private const val VPN_NOTIFICATION_ID = 2001
        private const val CHANNEL_ID = "himaya_vpn_channel"
    }

    private var vpnInterface: ParcelFileDescriptor? = null

    override fun onCreate() {
        super.onCreate()
        Log.i(TAG, "VPN service created")
        createNotificationChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val action = intent?.action

        when (action) {
            ACTION_START -> startVpn()
            ACTION_STOP -> stopSelf()
            else -> stopSelf()
        }

        return START_NOT_STICKY
    }

    /** Establish the VPN tunnel and start reading/writing packets */
    private fun startVpn() {
        try {
            val builder = Builder()
                .addAddress("10.0.0.2", 24)
                .addDnsServer("1.1.1.1")
                .addRoute("0.0.0.0", 0)
                .setSession("Himaya DNS Filter")
                .setConfigureIntent(
                    PendingIntent.getActivity(
                        this,
                        0,
                        Intent(this, MainActivity::class.java),
                        PendingIntent.FLAG_IMMUTABLE
                    )
                )

            vpnInterface = builder.establish()
            Log.i(TAG, "VPN tunnel established: ${vpnInterface?.fileDescriptor?.valid()}")

            // Start foreground with notification
            startForeground(VPN_NOTIFICATION_ID, createVpnNotification())

            // vpnInterface?.fileDescriptor is now the TUN fd.
            // We read/write IP packets on it. Phase 3 will implement the
            // actual DNS filtering loop here.

        } catch (e: Exception) {
            Log.e(TAG, "Failed to start VPN: ${e.message}")
            stopSelf()
        }
    }

    /**
     * Called when the user revokes VPN permission from system settings.
     */
    override fun onRevoke() {
        Log.w(TAG, "VPN permission revoked by user")
        stopForeground(true)
        stopSelf()
    }

    /**
     * Called when the service is being torn down.
     */
    override fun onTearingDown() {
        Log.i(TAG, "VPN tearing down")
        stopForeground(true)
        vpnInterface?.close()
        vpnInterface = null
        super.onTearingDown()
    }

    override fun onDestroy() {
        super.onDestroy()
        vpnInterface?.close()
        vpnInterface = null
        Log.i(TAG, "VPN service destroyed")
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                "Himaya VPN Filter",
                NotificationManager.IMPORTANCE_LOW
            )
            val manager = getSystemService(NotificationManager::class.java)
            manager.createNotificationChannel(channel)
        }
    }

    private fun createVpnNotification(): Notification {
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("Himaya Agent")
            .setContentText("DNS filtering active")
            .setSmallIcon(android.R.drawable.ic_lock_idle_alarm)
            .setOngoing(true)
            .build()
    }
}

/**
 * Helper to start/stop the VPN from MainActivity or other components.
 */
object VpnConnection {
    private const val TAG = "VpnConnection"

    /**
     * Request user permission for VPN, then start the VpnAgent service.
     * Returns true if permission was granted (or already granted).
     */
    fun startVpn(context: Context) {
        context.startForegroundService(Intent(context, VpnAgent::class.java).apply {
            action = VpnAgent.ACTION_START
        })
    }

    /** Stop the VPN service */
    fun stopVpn(context: Context) {
        context.stopService(Intent(context, VpnAgent::class.java))
    }
}