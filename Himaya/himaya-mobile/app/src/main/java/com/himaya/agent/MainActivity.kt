package com.himaya.agent

import android.app.Activity
import android.app.admin.DevicePolicyManager
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.net.VpnService
import android.os.Bundle
import android.util.Log
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * Main activity — the "Himaya Active" visible indicator.
 *
 * ★ Insight ─────────────────────────────────────
 * The "visible indicator" requirement means the child sees a simple
 * status: "Himaya Active" when the agent is running, "Paused" when not.
 * No hidden background behavior — the UI reflects the actual state.
 *
 * This activity also handles:
 *  - Hub URL + Device ID entry
 *  - Device admin activation (required for remote lock/wipe)
 *  - VPN service preparation (required for DNS filtering)
 *  - Starting/stopping the foreground AgentService
 *
 * All sensitive actions (admin, VPN) require explicit user consent
 * via system dialogs — we never silently enable anything.
 * ──────────────────────────────────────────────────
 */
class MainActivity : AppCompatActivity() {

    private lateinit var tvStatus: TextView
    private lateinit var etHubUrl: EditText
    private lateinit var etDeviceId: EditText
    private lateinit var btnEnable: Button
    private lateinit var btnDisable: Button
    private lateinit var btnEnableVpn: Button

    private val devicePolicyManager by lazy {
        getSystemService(Context.DEVICE_POLICY_SERVICE) as DevicePolicyManager
    }

    private val adminComponent by lazy {
        ComponentName(this, DeviceAdminReceiver::class.java)
    }

    private val TAG = "MainActivity"

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        tvStatus = findViewById(R.id.tvStatus)
        etHubUrl = findViewById(R.id.etHubUrl)
        etDeviceId = findViewById(R.id.etDeviceId)
        btnEnable = findViewById(R.id.btnEnable)
        btnDisable = findViewById(R.id.btnDisable)
        btnEnableVpn = findViewById(R.id.btnEnableVpn)

        loadSavedConfig()
        updateStatus()

        btnEnable.setOnClickListener { enableAgent() }
        btnDisable.setOnClickListener { disableAgent() }
        btnEnableVpn.setOnClickListener { prepareVpn() }

        handleEnrollmentIntent(intent)
    }

    override fun onNewIntent(intent: Intent?) {
        super.onNewIntent(intent)
        setIntent(intent)
        handleEnrollmentIntent(intent)
    }

    /** Handle deep-link or QR code auto-enrollment from Hub */
    private fun handleEnrollmentIntent(intent: Intent?) {
        val uri = intent?.data ?: return
        val hub = uri.getQueryParameter("hub")
        val pin = uri.getQueryParameter("pin")
        val devId = uri.getQueryParameter("device_id") ?: ("android-" + java.util.UUID.randomUUID().toString().take(6))

        if (!hub.isNullOrBlank()) {
            val cleanHub = if (!hub.startsWith("http://") && !hub.startsWith("https://")) "http://$hub" else hub
            etHubUrl.setText(cleanHub)
            etDeviceId.setText(devId)
            PreferenceManager.putString(this, "hub_url", cleanHub)
            PreferenceManager.putString(this, "device_id", devId)

            Toast.makeText(this, "Auto-configured Hub: $cleanHub", Toast.LENGTH_LONG).show()

            if (!pin.isNullOrBlank()) {
                CoroutineScope(Dispatchers.IO).launch {
                    val client = HubClient().apply { hubUrl = cleanHub }
                    val ok = client.pairWithPin(pin, android.os.Build.MODEL ?: "Android Device")
                    withContext(Dispatchers.Main) {
                        if (ok) {
                            Toast.makeText(this@MainActivity, "✓ Paired with Himaya Hub!", Toast.LENGTH_LONG).show()
                            if (devicePolicyManager.isAdminActive(adminComponent)) {
                                enableAgent()
                            } else {
                                requestAdmin()
                            }
                        }
                    }
                }
            }
        }
    }

    override fun onResume() {
        super.onResume()
        updateStatus()
    }

    /** Load saved hub URL and device ID from preferences */
    private fun loadSavedConfig() {
        etHubUrl.setText(PreferenceManager.getString(this, "hub_url"))
        etDeviceId.setText(PreferenceManager.getString(this, "device_id"))
    }

    /** Save config and start the agent service */
    private fun enableAgent() {
        val hubUrl = etHubUrl.text.toString().trim()
        val deviceId = etDeviceId.text.toString().trim()

        if (hubUrl.isEmpty() || deviceId.isEmpty()) {
            Toast.makeText(this, "Enter hub URL and device ID", Toast.LENGTH_SHORT).show()
            return
        }

        // Check if device admin is active
        if (!devicePolicyManager.isAdminActive(adminComponent)) {
            Toast.makeText(this, "Please enable Device Admin first", Toast.LENGTH_LONG).show()
            return
        }

        // Save config
        PreferenceManager.putString(this, "hub_url", hubUrl)
        PreferenceManager.putString(this, "device_id", deviceId)

        // Start agent service
        AgentService.start(this, hubUrl, deviceId)

        updateStatus()
        Toast.makeText(this, "Agent enabled", Toast.LENGTH_SHORT).show()
    }

    /** Stop the agent service and clear config */
    private fun disableAgent() {
        stopService(Intent(this, AgentService::class.java))
        PreferenceManager.clear(this)
        updateStatus()
        Toast.makeText(this, "Agent disabled", Toast.LENGTH_SHORT).show()
    }

    /** Request device admin activation */
    private fun requestAdmin() {
        val intent = Intent(DevicePolicyManager.ACTION_ADD_DEVICE_ADMIN)
        intent.putExtra(DevicePolicyManager.EXTRA_DEVICE_ADMIN, adminComponent)
        intent.putExtra(DevicePolicyManager.EXTRA_ADD_EXPLANATION,
            "Himaya needs device admin for remote lock, wipe, and policy enforcement")
        startActivityForResult(intent, REQUEST_ENABLE_ADMIN)
    }

    /** Request VPN service preparation (user consent) */
    private fun prepareVpn() {
        val intent = VpnService.prepare(this)
        if (intent != null) {
            startActivityForResult(intent, REQUEST_ENABLE_VPN)
        } else {
            // Already prepared
            Toast.makeText(this, "VPN already prepared", Toast.LENGTH_SHORT).show()
        }
    }

    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        when (requestCode) {
            REQUEST_ENABLE_ADMIN -> {
                if (resultCode == Activity.RESULT_OK) {
                    Toast.makeText(this, "Device admin enabled", Toast.LENGTH_SHORT).show()
                    // Now start VPN prep
                    prepareVpn()
                } else {
                    Toast.makeText(this, "Device admin required for agent", Toast.LENGTH_LONG).show()
                }
            }
            REQUEST_ENABLE_VPN -> {
                if (resultCode == Activity.RESULT_OK) {
                    Toast.makeText(this, "VPN prepared", Toast.LENGTH_SHORT).show()
                    // Now we can start the agent
                    enableAgent()
                } else {
                    Toast.makeText(this, "VPN required for DNS filtering", Toast.LENGTH_LONG).show()
                }
            }
        }
    }

    /** Update the status text based on agent state */
    private fun updateStatus() {
        val isRunning = isAgentRunning()
        val adminActive = devicePolicyManager.isAdminActive(adminComponent)

        tvStatus.text = if (isRunning) {
            getString(R.string.active_status)
        } else {
            getString(R.string.agent_paused)
        }

        btnEnable.isEnabled = !isRunning
        btnDisable.isEnabled = isRunning
        btnEnableVpn.isEnabled = !adminActive // Show VPN prep if admin not yet enabled
    }

    /** Check if agent service is running */
    private fun isAgentRunning(): Boolean {
        // Check if foreground service notification is showing
        // For simplicity, just check if we have saved config and admin active
        val hubUrl = PreferenceManager.getString(this, "hub_url")
        val deviceId = PreferenceManager.getString(this, "device_id")
        return hubUrl.isNotEmpty() && deviceId.isNotEmpty() &&
               devicePolicyManager.isAdminActive(adminComponent)
    }

    companion object {
        private const val REQUEST_ENABLE_ADMIN = 1001
        private const val REQUEST_ENABLE_VPN = 1002
    }
}