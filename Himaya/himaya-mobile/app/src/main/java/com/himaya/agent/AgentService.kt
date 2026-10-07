package com.himaya.agent

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.IBinder
import android.util.Log

/**
 * Main agent foreground service.
 *
 * Responsibilities:
 *  - Register device with the hub on startup
 *  - Send periodic heartbeats (every 20 seconds)
 *  - Forward DNS blocks and VPN attempts
 *  - Dispatch remote actions (lock, unlock, etc.)
 *
 * ★ Insight ─────────────────────────────────────
 * Foreground service is required so Android keeps the process alive
 * even when the app is backgrounded. A persistent notification (simple
 * text only) is shown so the user knows the agent is active.
 *
 * The service runs as long as the app process lives. On BOOT_COMPLETED
 * the BootReceiver restarts it.
 *
 * We use a plain Thread (not coroutines) to avoid needing KotlinScope
 * in a Service. Keep it simple and lightweight.
 * ──────────────────────────────────────────────────
 */
class AgentService : Service() {

    private var hubUrl: String = ""
    private var deviceId: String = ""

    // Heartbeat interval: 20 seconds
    private val HEARTBEAT_INTERVAL_MS = 20000L

    // Notification channel ID
    private const val CHANNEL_ID = "himaya_agent_channel"

    /** Called by the hub when the agent first registers */
    @SuppressLint("UnsafeProtectedServiceSuspension")
    override fun onCreate() {
        super.onCreate()

        // Create notification channel for Android O+
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                "Himaya Agent",
                NotificationManager.IMPORTANCE_LOW
            )
            val manager = getSystemService(NotificationManager::class.java)
            manager.createNotificationChannel(channel)
        }

        // Initialize hub URL and device ID from intent extras
        hubUrl = intent.getStringExtra("hub_url") ?: ""
        deviceId = intent.getStringExtra("device_id") ?: ""

        // Register with the hub immediately
        registerWithHub()

        // Start heartbeat loop in a background thread
        startHeartbeatLoop()
    }

    /** Register device with the hub (stub - actual registration in Phase 3) */
    private fun registerWithHub() {
        Log.i("AgentService", "Registering device: $deviceId with hub: $hubUrl")
    }

    /** Starts the periodic heartbeat loop */
    private fun startHeartbeatLoop() {
        Thread {
            while (isRunning) {
                try {
                    sendHeartbeat()
                } catch (e: Exception) {
                    Log.e("AgentService", "Heartbeat error", e)
                }
                Thread.sleep(HEARTBEAT_INTERVAL_MS)
            }
        }.start()
    }

    private fun sendHeartbeat() {
        val ip = "10.0.0.2" // placeholder IP
        // Use HubClient to send heartbeat
        HubClient(this).apply { hubUrl = hubUrl }
        HubClient(this).heartbeat(deviceId, ip)
    }

    @SuppressLint("ScheduleForegroundService")
    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (deviceId.isEmpty() && intent?.getStringExtra("device_id") != null) {
            deviceId = intent.getStringExtra("device_id") ?: ""
            hubUrl = intent.getStringExtra("hub_url") ?: ""
        }

        // If we don't have a device ID, don't start the loop yet
        if (deviceId.isEmpty()) {
            return START_STICKY
        }

        return START_STICKY
    }

    @Override
    fun onBind(intent: Intent?): IBinder? {
        return null
    }

    @Override
    fun onDestroy() {
        // No explicit thread management needed -
        // thread will die with process
        super.onDestroy()
    }
}