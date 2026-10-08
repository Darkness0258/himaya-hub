package com.himaya.agent

import android.app.Activity
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.ContentResolver
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.ImageFormat
import android.graphics.PixelFormat
import android.hardware.display.DisplayManager
import android.hardware.display.VirtualDisplay
import android.media.Image
import android.media.ImageReader
import android.media.projection.MediaProjection
import android.media.projection.MediaProjectionManager
import android.os.Build
import android.os.Environment
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.util.DisplayMetrics
import android.util.Log
import androidx.core.app.NotificationCompat
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import java.io.File
import java.io.FileOutputStream
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.TimeUnit

/**
 * Screen Share Service — captures on-demand screenshots via MediaProjection
 * and uploads them to the Himaya Hub.
 *
 * Flow:
 *  1. Hub sends "snapshot" command to agent via command queue
 *  2. AgentService receives command and starts this service with MediaProjection permission
 *  3. User consents to screen capture via system dialog
 *  4. VirtualDisplay + ImageReader captures frame
 *  5. Bitmap encoded to JPEG, uploaded to Hub /agents/{device_id}/snapshot
 *  6. Service stops, notification dismissed
 */
class ScreenShareService : Service() {

    private val TAG = "ScreenShareService"
    private val serviceJob = Job()
    private val serviceScope = CoroutineScope(Dispatchers.IO + serviceJob)

    private var mediaProjection: MediaProjection? = null
    private var virtualDisplay: VirtualDisplay? = null
    private var imageReader: ImageReader? = null
    private var mediaProjectionManager: MediaProjectionManager? = null
    private var screenCaptureCallback: ((Bitmap) -> Unit)? = null
    private var pendingResultIntent: Intent? = null
    private var pendingResultCode: Int = 0
    private var deviceId: String = ""
    private var hubUrl: String = ""
    private val hubClient = HubClient()

    companion object {
        const val CHANNEL_ID = "himaya_screenshare_channel"
        const val NOTIFICATION_ID = 3001
        const val EXTRA_HUB_URL = "hub_url"
        const val EXTRA_DEVICE_ID = "device_id"
        const val EXTRA_MEDIA_PROJECTION_DATA = "media_projection_data"
        const val EXTRA_MEDIA_PROJECTION_RESULT_CODE = "media_projection_result_code"
        private const val MEDIA_PROJECTION_REQUEST_CODE = 1003

        fun startCapture(context: Context, hubUrl: String, deviceId: String, resultCode: Int, data: Intent) {
            val intent = Intent(context, ScreenShareService::class.java).apply {
                putExtra(EXTRA_HUB_URL, hubUrl)
                putExtra(EXTRA_DEVICE_ID, deviceId)
                putExtra(EXTRA_MEDIA_PROJECTION_RESULT_CODE, resultCode)
                putExtra(EXTRA_MEDIA_PROJECTION_DATA, data)
            }
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                context.startForegroundService(intent)
            } else {
                context.startService(intent)
            }
        }

        /** Call this from MainActivity.onActivityResult when user grants MediaProjection permission */
        fun onMediaProjectionResult(context: Context, requestCode: Int, resultCode: Int, data: Intent?) {
            if (requestCode == MEDIA_PROJECTION_REQUEST_CODE && resultCode == Activity.RESULT_OK && data != null) {
                val hubUrl = PreferenceManager.getString(context, "hub_url", "")
                val deviceId = PreferenceManager.getString(context, "device_id", "")
                if (hubUrl.isNotEmpty() && deviceId.isNotEmpty()) {
                    startCapture(context, hubUrl, deviceId, resultCode, data)
                }
            }
        }

        /** Request MediaProjection permission from MainActivity */
        fun requestMediaProjection(activity: Activity) {
            val mpm = activity.getSystemService(Context.MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
            activity.startActivityForResult(mpm.createScreenCaptureIntent(), MEDIA_PROJECTION_REQUEST_CODE)
        }
    }

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()
        mediaProjectionManager = getSystemService(Context.MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        intent?.getStringExtra(EXTRA_HUB_URL)?.let { if (it.isNotEmpty()) hubUrl = it }
        intent?.getStringExtra(EXTRA_DEVICE_ID)?.let { if (it.isNotEmpty()) deviceId = it }
        intent?.getIntExtra(EXTRA_MEDIA_PROJECTION_RESULT_CODE, 0)?.let { pendingResultCode = it }
        intent?.getParcelableExtra<Intent>(EXTRA_MEDIA_PROJECTION_DATA)?.let { pendingResultIntent = it }

        hubClient.hubUrl = hubUrl

        if (deviceId.isEmpty() || hubUrl.isEmpty()) {
            Log.w(TAG, "Missing hub URL or device ID, stopping")
            stopSelf()
            return START_NOT_STICKY
        }

        // Start foreground with capturing notification
        val notification = buildCapturingNotification()
        startForeground(NOTIFICATION_ID, notification)

        // Initialize MediaProjection from the consent intent
        if (pendingResultIntent != null && pendingResultCode == Activity.RESULT_OK) {
            mediaProjection = mediaProjectionManager?.getMediaProjection(pendingResultCode, pendingResultIntent)
            if (mediaProjection != null) {
                startCapture()
            } else {
                Log.e(TAG, "Failed to create MediaProjection")
                stopSelf()
            }
        } else {
            Log.w(TAG, "No valid MediaProjection consent, stopping")
            stopSelf()
        }

        return START_NOT_STICKY
    }

    private fun startCapture() {
        serviceScope.launch {
            try {
                captureScreen { bitmap ->
                    uploadScreenshot(bitmap)
                }
                // Wait for capture to complete
                delay(5000)
            } catch (e: Exception) {
                Log.e(TAG, "Capture error: ${e.message}")
            } finally {
                cleanup()
                stopForeground(true)
                stopSelf()
            }
        }
    }

    /**
     * Captures a single screen frame using VirtualDisplay + ImageReader
     */
    private fun captureScreen(onCapture: (Bitmap) -> Unit) {
        val projection = mediaProjection ?: return

        val metrics = DisplayMetrics()
        val displayManager = getSystemService(Context.DISPLAY_SERVICE) as DisplayManager
        displayManager.getDisplay(0)?.getRealMetrics(metrics)

        val width = metrics.widthPixels
        val height = metrics.heightPixels
        val density = metrics.densityDpi

        // Create ImageReader for RGBA_8888 format
        imageReader = ImageReader.newInstance(width, height, PixelFormat.RGBA_8888, 2)

        imageReader?.setOnImageAvailableListener({ reader ->
            val image = reader.acquireLatestImage() ?: return@setOnImageAvailableListener
            try {
                val bitmap = imageToBitmap(image)
                onCapture(bitmap)
            } finally {
                image.close()
            }
        }, Handler(Looper.getMainLooper()))

        // Create VirtualDisplay to mirror screen content to ImageReader
        virtualDisplay = projection.createVirtualDisplay(
            "HimayaScreenCapture",
            width,
            height,
            density,
            DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR,
            imageReader?.surface,
            null,
            Handler(Looper.getMainLooper())
        )

        // Timeout fallback
        Handler(Looper.getMainLooper()).postDelayed({
            if (virtualDisplay != null) {
                Log.w(TAG, "Capture timeout, forcing cleanup")
                cleanup()
                stopForeground(true)
                stopSelf()
            }
        }, 5000)
    }

    private fun imageToBitmap(image: Image): Bitmap {
        val planes = image.planes
        val buffer = planes[0].buffer
        val pixelStride = planes[0].pixelStride
        val rowStride = planes[0].rowStride
        val width = image.width
        val height = image.height

        val bitmap = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888)
        bitmap.copyPixelsFromBuffer(buffer)
        return bitmap
    }

    private fun uploadScreenshot(bitmap: Bitmap) {
        serviceScope.launch {
            try {
                // Save to temporary file
                val file = createTempImageFile(bitmap)

                // Upload to hub
                val ok = hubClient.uploadSnapshot(deviceId, file)

                if (ok) {
                    Log.i(TAG, "Screenshot uploaded successfully")
                    // Notify user
                    showCompletionNotification("Screenshot captured and uploaded")
                } else {
                    Log.e(TAG, "Screenshot upload failed")
                    showCompletionNotification("Screenshot upload failed")
                }

                file.delete()
            } catch (e: Exception) {
                Log.e(TAG, "Upload error: ${e.message}")
                showCompletionNotification("Screenshot upload error")
            }
        }
    }

    private fun createTempImageFile(bitmap: Bitmap): File {
        val timeStamp = SimpleDateFormat("yyyyMMdd_HHmmss", Locale.getDefault()).format(Date())
        val imageFileName = "Himaya_${timeStamp}_"
        val storageDir = getExternalFilesDir(Environment.DIRECTORY_PICTURES) ?: filesDir
        val file = File.createTempFile(imageFileName, ".jpg", storageDir)

        FileOutputStream(file).use { out ->
            bitmap.compress(Bitmap.CompressFormat.JPEG, 85, out)
        }
        return file
    }

    private fun showCompletionNotification(message: String) {
        val manager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        val notification = NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("Himaya Screen Share")
            .setContentText(message)
            .setSmallIcon(android.R.drawable.ic_menu_camera)
            .setPriority(NotificationCompat.PRIORITY_DEFAULT)
            .setAutoCancel(true)
            .build()
        manager.notify(NOTIFICATION_ID + 1, notification)
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                "Himaya Screen Capture",
                NotificationManager.IMPORTANCE_LOW
            ).apply {
                description = "On-demand screen capture for family safety"
                setShowBadge(false)
            }
            val manager = getSystemService(NotificationManager::class.java)
            manager.createNotificationChannel(channel)
        }
    }

    private fun buildCapturingNotification(): Notification {
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("Himaya Screen Capture")
            .setContentText("Capturing screen...")
            .setSmallIcon(android.R.drawable.ic_media_play)
            .setOngoing(true)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .setProgress(0, 0, true)
            .build()
    }

    private fun cleanup() {
        virtualDisplay?.release()
        virtualDisplay = null
        imageReader?.close()
        imageReader = null
        mediaProjection?.stop()
        mediaProjection = null
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        serviceJob.cancel()
        cleanup()
        super.onDestroy()
    }
}