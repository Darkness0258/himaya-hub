package com.himaya.agent

import android.Manifest
import android.app.Activity
import android.app.admin.DevicePolicyManager
import android.content.ComponentName
import android.content.Intent
import android.content.pm.PackageManager
import android.media.projection.MediaProjectionManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.view.View
import android.view.inputmethod.EditorInfo
import android.widget.Button
import android.widget.CompoundButton
import android.widget.EditText
import android.widget.RadioButton
import android.widget.TextView
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import org.json.JSONObject

/**
 * The only screen: connect to the hub with a PIN, switch on the protections, see what is going on.
 *
 * Compared to the first version:
 *  - a link or QR code can only pre-fill the hub address, and the person must confirm it (before, a crafted
 *    link paired the phone to any hub automatically, with the PIN included in the link);
 *  - the PIN is typed here; the hub never puts it in a link or page;
 *  - the pairing answer (hub-assigned device id and key) is stored, so the phone and the hub agree on identity;
 *  - the agent no longer refuses to run without Device admin; each protection is explained and optional;
 *  - the status shows whether the service is really running, not just whether settings exist;
 *  - disconnecting is confirmed and the parent is told.
 */
class MainActivity : AppCompatActivity() {

    companion object {
        private const val REQ_ADMIN = 10
        private const val REQ_VPN = 11
        private const val REQ_CAPTURE = 12
        private const val REQ_NOTIFICATIONS = 13
        private val HUB_URL = Regex("^https?://[A-Za-z0-9._-]+(:[0-9]{1,5})?$|^https?://\\[[0-9A-Fa-f:.]+](:[0-9]{1,5})?$")

        /** "192.168.1.20:8000", "http://hub.local:8000/anything" -> "http://192.168.1.20:8000". Null if it is not a plain hub address. */
        fun normalizeHub(input: String): String? {
            var text = input.trim()
            if (text.isEmpty() || looksLikeKey(text)) return null
            if (!text.contains("://")) text = "http://$text"
            val uri = Uri.parse(text)
            val scheme = uri.scheme?.lowercase() ?: return null
            val authority = uri.authority ?: return null
            val candidate = "$scheme://$authority"
            return if (HUB_URL.matches(candidate)) candidate else null
        }
    }

    private lateinit var statusTitle: TextView
    private lateinit var statusDetail: TextView
    private lateinit var connectGroup: View
    private lateinit var connectedGroup: View
    private lateinit var connectedInfo: TextView
    private lateinit var hubInput: EditText
    private lateinit var pinInput: EditText
    private lateinit var nameInput: EditText
    private lateinit var ownerAdult: RadioButton
    private lateinit var connectButton: Button
    private lateinit var connectError: TextView
    private lateinit var adminStatus: TextView
    private lateinit var adminButton: Button
    private lateinit var notifStatus: TextView
    private lateinit var notifButton: Button
    private lateinit var filterStatus: TextView
    private lateinit var filterSwitch: CompoundButton

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        Notifications.ensureChannels(this)
        setContentView(R.layout.activity_main)
        bindViews()
        nameInput.setText("${Build.MANUFACTURER.replaceFirstChar { it.uppercase() }} ${Build.MODEL}".take(80))
        connectButton.setOnClickListener { connect() }
        pinInput.setOnEditorActionListener { _, actionId, _ ->
            if (actionId == EditorInfo.IME_ACTION_DONE) connect()
            actionId == EditorInfo.IME_ACTION_DONE
        }
        findViewById<Button>(R.id.disconnectButton).setOnClickListener { confirmDisconnect() }
        adminButton.setOnClickListener { requestAdmin() }
        notifButton.setOnClickListener { requestNotifications() }
        filterSwitch.setOnCheckedChangeListener { button, checked ->
            if (button.isPressed) setFilter(checked)
        }
        handleIntent(intent)
    }

    private fun bindViews() {
        statusTitle = findViewById(R.id.statusTitle)
        statusDetail = findViewById(R.id.statusDetail)
        connectGroup = findViewById(R.id.connectGroup)
        connectedGroup = findViewById(R.id.connectedGroup)
        connectedInfo = findViewById(R.id.connectedInfo)
        hubInput = findViewById(R.id.hubInput)
        pinInput = findViewById(R.id.pinInput)
        nameInput = findViewById(R.id.nameInput)
        ownerAdult = findViewById(R.id.ownerAdult)
        connectButton = findViewById(R.id.connectButton)
        connectError = findViewById(R.id.connectError)
        adminStatus = findViewById(R.id.adminStatus)
        adminButton = findViewById(R.id.adminButton)
        notifStatus = findViewById(R.id.notifStatus)
        notifButton = findViewById(R.id.notifButton)
        filterStatus = findViewById(R.id.filterStatus)
        filterSwitch = findViewById(R.id.filterSwitch)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        handleIntent(intent)
    }

    override fun onResume() {
        super.onResume()
        if (PreferenceManager.isPaired(this) && !AgentService.running) AgentService.start(this)
        refreshUi()
    }

    // ------------------------------------------------------------------ links, QR codes and notifications

    private fun handleIntent(intent: Intent?) {
        intent ?: return
        if (intent.action == Notifications.ACTION_SCREEN_SHARE) {
            intent.action = null
            if (PreferenceManager.isPaired(this)) askForScreenCapture()
            return
        }
        val data = intent.data ?: return
        val hub = when (data.scheme) {
            "himaya" -> data.getQueryParameter("hub")
            "http", "https" -> "${data.scheme}://${data.authority}"
            else -> null
        }?.let { normalizeHub(it) }
        intent.data = null
        if (hub == null) {
            connectError.text = "That link does not contain a valid hub address."
            return
        }
        if (PreferenceManager.isPaired(this)) return // already connected: ignore stray links
        AlertDialog.Builder(this)
            .setTitle("Connect to this hub?")
            .setMessage("$hub\n\nOnly continue if this is your family's Himaya hub. You will need the 6-digit PIN from its dashboard.")
            .setPositiveButton("Yes, it's mine") { _, _ ->
                hubInput.setText(hub)
                pinInput.requestFocus()
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    // ------------------------------------------------------------------ pairing

    private fun connect() {
        connectError.text = ""
        val hub = normalizeHub(hubInput.text.toString())
        val pin = pinInput.text.toString().trim()
        val name = nameInput.text.toString().trim().ifEmpty { "${Build.MANUFACTURER} ${Build.MODEL}" }
        val owner = if (ownerAdult.isChecked) "adult" else "child"
        when {
            hub == null -> {
                if (looksLikeKey(hubInput.text.toString())) {
                    hubInput.setText("") // do not leave a secret on screen
                    connectError.text = "That looks like a secret key, not an address. Type the hub address like 192.168.1.20:8000 instead."
                } else {
                    connectError.text = "Type the hub address like 192.168.1.20:8000 (the Enroll page of the dashboard shows it)."
                }
                return
            }
            pin.length != 6 || !pin.all { it.isDigit() } -> {
                connectError.text = "The PIN is 6 digits. Look at the Enroll page of the dashboard."
                return
            }
        }
        connectButton.isEnabled = false
        connectButton.text = "Connecting"
        Thread {
            val outcome = HubClient(OkHttpTransport()).pair(hub!!, pin, name, owner)
            runOnUiThread { onPairResult(hub, name, owner, outcome) }
        }.start()
    }

    private fun onPairResult(hub: String, name: String, owner: String, outcome: PairOutcome) {
        connectButton.isEnabled = true
        connectButton.text = "Connect"
        when (outcome) {
            is PairOutcome.Success -> {
                val result = outcome.result
                PreferenceManager.savePairing(this, hub, result.deviceId, result.agentKey, name, owner, result.dnsPort)
                pinInput.setText("")
                AgentService.start(this)
                if (Build.VERSION.SDK_INT >= 33) requestNotifications()
                refreshUi()
            }
            PairOutcome.WrongPin -> connectError.text = "That PIN was not accepted. It changes after every use, so check the dashboard for the current one."
            is PairOutcome.RateLimited -> connectError.text = outcome.message
            is PairOutcome.Unreachable -> connectError.text = "Could not reach $hub. Is this phone on the same Wi-Fi as the hub?"
            is PairOutcome.Failed -> connectError.text = outcome.message
        }
    }

    private fun confirmDisconnect() {
        AlertDialog.Builder(this)
            .setTitle("Disconnect this phone?")
            .setMessage("Himaya stops protecting this phone and your parent is told. Locks and internet pauses end.")
            .setPositiveButton("Disconnect") { _, _ -> disconnect() }
            .setNegativeButton("Stay connected", null)
            .show()
    }

    private fun disconnect() {
        val hub = PreferenceManager.hubUrl(this)
        val key = PreferenceManager.agentKey(this)
        val id = PreferenceManager.deviceId(this)
        Thread {
            try {
                HubClient(OkHttpTransport(), hub, key).reportEvent(id, "agent_stopped", JSONObject().put("reason", "Disconnected on the phone"))
            } catch (e: Exception) {
                // the parent will see it go quiet instead
            }
            runOnUiThread {
                VpnAgent.blockAll = false
                AgentService.stop(this)
                VpnAgent.stop(this)
                PreferenceManager.clear(this)
                refreshUi()
            }
        }.start()
    }

    // ------------------------------------------------------------------ protections

    private fun adminComponent() = ComponentName(this, DeviceAdminReceiver::class.java)

    private fun adminActive(): Boolean = getSystemService(DevicePolicyManager::class.java)?.isAdminActive(adminComponent()) == true

    private fun requestAdmin() {
        val intent = Intent(DevicePolicyManager.ACTION_ADD_DEVICE_ADMIN)
            .putExtra(DevicePolicyManager.EXTRA_DEVICE_ADMIN, adminComponent())
            .putExtra(DevicePolicyManager.EXTRA_ADD_EXPLANATION, "Lets Himaya lock this phone when your parent asks, and erase it if it is lost.")
        @Suppress("DEPRECATION")
        startActivityForResult(intent, REQ_ADMIN)
    }

    private fun requestNotifications() {
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), REQ_NOTIFICATIONS)
        }
    }

    private fun notificationsAllowed(): Boolean =
        Build.VERSION.SDK_INT < 33 || checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED

    private fun setFilter(on: Boolean) {
        if (!on) {
            VpnAgent.stop(this)
            PreferenceManager.setFilterOn(this, false)
            refreshUi()
            return
        }
        val consent = VpnAgent.consentIntent(this)
        if (consent != null) {
            @Suppress("DEPRECATION")
            startActivityForResult(consent, REQ_VPN)
        } else {
            VpnAgent.start(this)
            refreshUi()
        }
    }

    private fun askForScreenCapture() {
        val manager = getSystemService(MediaProjectionManager::class.java)
        @Suppress("DEPRECATION")
        startActivityForResult(manager.createScreenCaptureIntent(), REQ_CAPTURE)
    }

    @Deprecated("Deprecated in Java")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        @Suppress("DEPRECATION")
        super.onActivityResult(requestCode, resultCode, data)
        when (requestCode) {
            REQ_VPN -> if (resultCode == Activity.RESULT_OK) VpnAgent.start(this)
            REQ_CAPTURE -> if (resultCode == Activity.RESULT_OK && data != null) ScreenShareService.start(this, resultCode, data) else Notifications.cancelRequest(this)
        }
        refreshUi()
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        refreshUi()
    }

    // ------------------------------------------------------------------ status

    private fun refreshUi() {
        val paired = PreferenceManager.isPaired(this)
        connectGroup.visibility = if (paired) View.GONE else View.VISIBLE
        connectedGroup.visibility = if (paired) View.VISIBLE else View.GONE

        if (!paired) {
            statusTitle.text = "Not connected yet"
            statusDetail.text = "Connect this phone to your family's Himaya hub to switch on protection."
        } else if (PreferenceManager.removedByHub(this)) {
            statusTitle.text = "Removed by your parent"
            statusDetail.text = "The hub no longer knows this phone. Disconnect here, then connect again if that was a mistake."
        } else if (AgentService.running) {
            statusTitle.text = "Himaya is active"
            statusDetail.text = "A notification stays visible while Himaya runs. Your parent can lock this phone, send messages, and pause the internet."
        } else {
            statusTitle.text = "Starting"
            statusDetail.text = "Himaya is starting up."
        }
        connectedInfo.text = if (paired) "Connected to ${PreferenceManager.hubUrl(this)} as \"${PreferenceManager.deviceName(this)}\"" else ""

        val admin = adminActive()
        adminStatus.text = if (admin) "Lock and erase: on" else "Lock and erase: off. Needed so your parent can lock this phone or erase it if it is lost."
        adminButton.visibility = if (admin) View.GONE else View.VISIBLE
        val notifications = notificationsAllowed()
        notifStatus.text = if (notifications) "Notifications: on" else "Notifications: off. Needed to see messages and the Himaya indicator."
        notifButton.visibility = if (notifications) View.GONE else View.VISIBLE
        filterSwitch.isChecked = VpnAgent.running
        filterStatus.text = if (VpnAgent.running) "Website filter: on" else "Website filter: off. Turn it on so blocked websites and internet pauses work on this phone."
    }
}
