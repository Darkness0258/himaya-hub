package com.himaya.agent

import android.content.Context
import android.content.SharedPreferences

/**
 * Simple SharedPreferences wrapper for agent config.
 */
object PreferenceManager {
    private const val PREFS_NAME = "himaya_agent_prefs"

    private fun getPrefs(context: Context): SharedPreferences =
        context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

    fun getString(context: Context, key: String, default: String = ""): String {
        return getPrefs(context).getString(key, default) ?: default
    }

    fun putString(context: Context, key: String, value: String) {
        getPrefs(context).edit().putString(key, value).apply()
    }

    fun getBoolean(context: Context, key: String, default: Boolean = false): Boolean {
        return getPrefs(context).getBoolean(key, default)
    }

    fun putBoolean(context: Context, key: String, value: Boolean) {
        getPrefs(context).edit().putBoolean(key, value).apply()
    }

    fun clear(context: Context) {
        getPrefs(context).edit().clear().apply()
    }
}