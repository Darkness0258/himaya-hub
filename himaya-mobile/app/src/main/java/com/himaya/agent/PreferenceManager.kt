package com.himaya.agent

import android.content.Context
import android.content.SharedPreferences

/** Everything the agent remembers on the phone. Plain private preferences: the agent key is a revocable per-device secret. */
object PreferenceManager {
    private const val FILE = "himaya_agent"

    private const val KEY_HUB_URL = "hub_url"
    private const val KEY_DEVICE_ID = "device_id"
    private const val KEY_AGENT_KEY = "agent_key"
    private const val KEY_DEVICE_NAME = "device_name"
    private const val KEY_OWNER = "owner_type"
    private const val KEY_DNS_PORT = "dns_port"
    private const val KEY_FILTER_ON = "filter_enabled"
    private const val KEY_FILTER_LOST = "filter_lost"
    private const val KEY_ADMIN_LOST = "admin_lost"
    private const val KEY_REMOVED = "removed_by_hub"

    private fun prefs(context: Context): SharedPreferences = context.applicationContext.getSharedPreferences(FILE, Context.MODE_PRIVATE)

    fun hubUrl(context: Context): String = prefs(context).getString(KEY_HUB_URL, "") ?: ""
    fun deviceId(context: Context): String = prefs(context).getString(KEY_DEVICE_ID, "") ?: ""
    fun agentKey(context: Context): String = prefs(context).getString(KEY_AGENT_KEY, "") ?: ""
    fun deviceName(context: Context): String = prefs(context).getString(KEY_DEVICE_NAME, "") ?: ""
    fun ownerType(context: Context): String = prefs(context).getString(KEY_OWNER, "child") ?: "child"

    /** 0 means the hub's DNS filter is not available (the VPN then forwards to a family-safe public resolver). */
    fun dnsPort(context: Context): Int = prefs(context).getInt(KEY_DNS_PORT, 0)
    fun setDnsPort(context: Context, port: Int) = prefs(context).edit().putInt(KEY_DNS_PORT, port).apply()

    fun filterOn(context: Context): Boolean = prefs(context).getBoolean(KEY_FILTER_ON, false)
    fun setFilterOn(context: Context, on: Boolean) = prefs(context).edit().putBoolean(KEY_FILTER_ON, on).apply()

    /** Set when the system stops our VPN (the user turned it off, or another VPN took over). The agent reports it once. */
    fun filterLost(context: Context): Boolean = prefs(context).getBoolean(KEY_FILTER_LOST, false)
    fun setFilterLost(context: Context, lost: Boolean) = prefs(context).edit().putBoolean(KEY_FILTER_LOST, lost).apply()

    fun adminLost(context: Context): Boolean = prefs(context).getBoolean(KEY_ADMIN_LOST, false)
    fun setAdminLost(context: Context, lost: Boolean) = prefs(context).edit().putBoolean(KEY_ADMIN_LOST, lost).apply()

    fun removedByHub(context: Context): Boolean = prefs(context).getBoolean(KEY_REMOVED, false)
    fun setRemovedByHub(context: Context, removed: Boolean) = prefs(context).edit().putBoolean(KEY_REMOVED, removed).apply()

    fun isPaired(context: Context): Boolean = hubUrl(context).isNotEmpty() && deviceId(context).isNotEmpty() && agentKey(context).isNotEmpty()

    fun savePairing(context: Context, hubUrl: String, deviceId: String, agentKey: String, deviceName: String, ownerType: String, dnsPort: Int?) {
        prefs(context).edit()
            .putString(KEY_HUB_URL, hubUrl.trimEnd('/'))
            .putString(KEY_DEVICE_ID, deviceId)
            .putString(KEY_AGENT_KEY, agentKey)
            .putString(KEY_DEVICE_NAME, deviceName)
            .putString(KEY_OWNER, ownerType)
            .putInt(KEY_DNS_PORT, dnsPort ?: 0)
            .putBoolean(KEY_REMOVED, false)
            .putBoolean(KEY_FILTER_LOST, false)
            .putBoolean(KEY_ADMIN_LOST, false)
            .apply()
    }

    fun clear(context: Context) = prefs(context).edit().clear().apply()
}
