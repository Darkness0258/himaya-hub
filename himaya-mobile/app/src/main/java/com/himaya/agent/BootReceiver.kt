package com.himaya.agent

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

/** Starts the agent again after a restart or an app update, if this phone is set up. */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val action = intent.action
        if (action != Intent.ACTION_BOOT_COMPLETED && action != Intent.ACTION_MY_PACKAGE_REPLACED) return
        if (!PreferenceManager.isPaired(context)) return
        try {
            AgentService.start(context)
        } catch (e: Exception) {
            android.util.Log.w("Himaya", "could not start the agent after boot", e)
        }
    }
}
