package com.himaya.agent

import android.app.admin.DeviceAdminReceiver
import android.content.Context
import android.content.Intent
import android.util.Log
import android.widget.Toast

/**
 * Device administrator receiver.
 *
 * Required for remote lock and wipe actions.
 * The device admin policy is defined in res/xml/device_admin.xml.
 */
class DeviceAdminReceiver : DeviceAdminReceiver() {

    override fun onEnabled(context: Context, intent: Intent) {
        super.onEnabled(context, intent)
        Toast.makeText(context, "Himaya Device Protection Active", Toast.LENGTH_LONG).show()
        Log.i("DeviceAdminReceiver", "Device Admin Enabled")
    }

    override fun onDisabled(context: Context, intent: Intent) {
        super.onDisabled(context, intent)
        Toast.makeText(context, "Himaya Device Admin Disabled", Toast.LENGTH_LONG).show()
        Log.w("DeviceAdminReceiver", "Device Admin Disabled")
    }

    override fun onPasswordFailed(context: Context, intent: Intent) {
        super.onPasswordFailed(context, intent)
        Log.w("DeviceAdminReceiver", "Password failed")
    }

    override fun onPasswordSucceeded(context: Context, intent: Intent) {
        super.onPasswordSucceeded(context, intent)
        Log.i("DeviceAdminReceiver", "Password succeeded")
    }
}