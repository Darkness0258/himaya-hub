package com.himaya.agent

import android.app.Application

/**
 * Only prepares notification channels. The first version started the service from here, which crashes on
 * Android 8+ whenever the process is created in the background (for example by the boot receiver).
 */
class HimayaApplication : Application() {
    override fun onCreate() {
        super.onCreate()
        Notifications.ensureChannels(this)
    }
}
