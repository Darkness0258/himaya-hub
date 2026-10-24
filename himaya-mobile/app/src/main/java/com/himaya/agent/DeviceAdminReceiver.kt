package com.himaya.agent

import android.content.Context
import android.content.Intent

/**
 * Device admin lets Himaya lock the screen and, for a lost phone, erase it. Only the `force-lock` and
 * `wipe-data` policies are declared (see res/xml/device_admin.xml). The class keeps its name because
 * enroll-device-owner.bat refers to `com.himaya.agent/.DeviceAdminReceiver`.
 */
class DeviceAdminReceiver : android.app.admin.DeviceAdminReceiver() {

    override fun onEnabled(context: Context, intent: Intent) {
        PreferenceManager.setAdminLost(context, false)
    }

    override fun onDisableRequested(context: Context, intent: Intent): CharSequence =
        "Without Device admin, Himaya cannot lock this phone or erase it if it is lost. Your parent will be told."

    override fun onDisabled(context: Context, intent: Intent) {
        // The agent reports this to the hub on its next tick.
        PreferenceManager.setAdminLost(context, true)
    }
}
