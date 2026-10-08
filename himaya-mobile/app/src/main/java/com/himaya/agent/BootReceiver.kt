package com.himaya.agent

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log

/**
 * Boot receiver to restart the agent after device reboot.
 *
 * The hub URL and device ID are restored from SharedPreferences here.
 * They're saved when the user enables the agent in MainActivity.
 */
class BootReceiver : BroadcastReceiver() {

    companion object {
        private const val TAG = "BootReceiver"
    }

    override fun onReceive(context: Context, intent: Intent) {
        // Restore config from saved preferences
        val hubUrl = PreferenceManager.getString(context, "hub_url", "")
        val deviceId = PreferenceManager.getString(context, "device_id", "")

        if (hubUrl.isNotEmpty() && deviceId.isNotEmpty()) {
            val serviceIntent = Intent(context, AgentService::class.java)
            serviceIntent.putExtra("hub_url", hubUrl)
            serviceIntent.putExtra("device_id", deviceId)
            context.startService(serviceIntent)
            Log.i(TAG, "Agent service started after boot")
        }
    }
}