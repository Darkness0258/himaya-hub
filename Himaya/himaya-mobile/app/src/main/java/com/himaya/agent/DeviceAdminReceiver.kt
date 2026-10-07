package com.himaya.agent

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.ActivityInfo
import android.widget.Toast

/**
 * Device administrator receiver.
 *
 * Required for remote lock and wipe actions.
 * The device admin policy is defined in res/xml/device_admin.xml.
 *
 * ★ Insight ─────────────────────────────────────
 * BIND_DEVICE_ADMIN permission + meta-data pointing to device_admin.xml
 * are the minimum for device admin. The policy includes:
 *   - lock-password (screen lock)
 *   - wipe-data (factory reset)
 *   - disable-camera (prevent photo capture)
 *   - disable-usb-tether (prevent tethering)
 *
 * The user must enable the admin via a settings activity before
 * remote actions work. Until then, we just handle what we can.
 * ──────────────────────────────────────────────────
 */
class DeviceAdminReceiver : android.app DeviceAdminReceiver() {

    override fun onEnabled(context: Context, intent: Intent) {
        super.onEnabled(context, intent)
        Toast.makeText(context, "Device admin enabled", Toast.LENGTH_LONG).show()
        Log.i("DeviceAdminReceiver", "Admin enabled")
    }

    override fun onDisabled(context: Context, intent: Intent) {
        super.onDisabled(context, intent)
        Toast.makeText(context, "Device admin disabled", Toast.LENGTH_LONG).show()
        Log.i("DeviceAdminReceiver", "Admin disabled")
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