package com.himaya.agent

import android.app.Application
import android.content.Intent

/**
 * Application class for Himaya Agent
 * Initializes services on app start
 */
class HimayaApplication : Application() {

    override fun onCreate() {
        super.onCreate()
        // Start agent service on app creation
        startService(Intent(this, AgentService::class.java))
    }
}