package com.himaya.agent

import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.graphics.Bitmap
import android.graphics.PixelFormat
import android.hardware.display.DisplayManager
import android.hardware.display.VirtualDisplay
import android.media.Image
import android.media.ImageReader
import android.media.projection.MediaProjection
import android.media.projection.MediaProjectionManager
import android.os.Build
import android.os.Handler
import android.os.HandlerThread
import android.os.IBinder
import java.io.ByteArrayOutputStream
import java.util.concurrent.atomic.AtomicBoolean

/**
 * Takes ONE screenshot after the child tapped "Allow" in Android's own screen-capture dialog, sends it to the
 * hub and stops. Android shows its own indicator while a capture is running, and this service keeps a visible
 * notification too.
 *
 * Fixed compared to the first version:
 *  - the image buffer's row padding was ignored (`rowStride`), which produced sheared / crashing screenshots;
 *  - the image listener was never removed, so every frame for five seconds was converted and uploaded (dozens
 *    of uploads); now exactly one frame is used;
 *  - Android 14 requires a MediaProjection.Callback to be registered before creating the virtual display;
 *  - the foreground service now declares the mediaProjection type explicitly.
 */
class ScreenShareService : Service() {

    companion object {
        private const val EXTRA_RESULT_CODE = "result_code"
        private const val EXTRA_DATA = "data"
        private const val MAX_LONG_SIDE = 1280

        fun start(context: Context, resultCode: Int, data: Intent) {
            context.startForegroundService(
                Intent(context, ScreenShareService::class.java)
                    .putExtra(EXTRA_RESULT_CODE, resultCode)
                    .putExtra(EXTRA_DATA, data),
            )
        }

        /** Scale so the longest side is at most [maxLongSide], keeping the aspect ratio. */
        fun scaledSize(width: Int, height: Int, maxLongSide: Int = MAX_LONG_SIDE): Pair<Int, Int> {
            val longSide = maxOf(width, height)
            if (longSide <= maxLongSide) return Pair(width, height)
            val scale = maxLongSide.toFloat() / longSide
            return Pair(maxOf(1, (width * scale).toInt()), maxOf(1, (height * scale).toInt()))
        }
    }

    private var projection: MediaProjection? = null
    private var display: VirtualDisplay? = null
    private var reader: ImageReader? = null
    private var thread: HandlerThread? = null
    private val finished = AtomicBoolean(false)

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        Notifications.ensureChannels(this)
        val notification = Notifications.status(this, "Sharing your screen with your parent, once.", "Himaya is capturing your screen")
        if (Build.VERSION.SDK_INT >= 29) {
            startForeground(Notifications.ID_CAPTURE, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION)
        } else {
            startForeground(Notifications.ID_CAPTURE, notification)
        }
        val resultCode = intent?.getIntExtra(EXTRA_RESULT_CODE, 0) ?: 0
        @Suppress("DEPRECATION")
        val data = intent?.getParcelableExtra<Intent>(EXTRA_DATA)
        if (data == null || resultCode == 0) {
            finish()
            return START_NOT_STICKY
        }
        Notifications.cancelRequest(this)
        try {
            capture(resultCode, data)
        } catch (e: Exception) {
            android.util.Log.w("Himaya", "screen capture failed", e)
            finish()
        }
        return START_NOT_STICKY
    }

    private fun capture(resultCode: Int, data: Intent) {
        val manager = getSystemService(MediaProjectionManager::class.java)
        val mediaProjection = manager.getMediaProjection(resultCode, data) ?: run {
            finish()
            return
        }
        projection = mediaProjection

        val metrics = resources.displayMetrics
        val (width, height) = scaledSize(metrics.widthPixels, metrics.heightPixels)
        val handlerThread = HandlerThread("himaya-capture").also { it.start() }
        thread = handlerThread
        val handler = Handler(handlerThread.looper)

        // Required on Android 14+ before createVirtualDisplay().
        mediaProjection.registerCallback(object : MediaProjection.Callback() {
            override fun onStop() {
                finish()
            }
        }, handler)

        val imageReader = ImageReader.newInstance(width, height, PixelFormat.RGBA_8888, 2)
        reader = imageReader
        imageReader.setOnImageAvailableListener({ source ->
            val image = source.acquireLatestImage() ?: return@setOnImageAvailableListener
            if (finished.get() || !oneShot.compareAndSet(false, true)) {
                image.close()
                return@setOnImageAvailableListener
            }
            try {
                val jpeg = toJpeg(image, width, height)
                upload(jpeg)
            } finally {
                image.close()
                finish()
            }
        }, handler)

        display = mediaProjection.createVirtualDisplay(
            "himaya-capture", width, height, metrics.densityDpi,
            DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR, imageReader.surface, null, handler,
        )
        handler.postDelayed({ finish() }, 8000) // safety net if no frame ever arrives
    }

    private val oneShot = AtomicBoolean(false)

    /** Convert an RGBA_8888 [Image] to JPEG. The row stride can be wider than the picture, so the padding is cropped away. */
    private fun toJpeg(image: Image, width: Int, height: Int): ByteArray {
        val plane = image.planes[0]
        val pixelStride = plane.pixelStride
        val rowPadding = plane.rowStride - pixelStride * width
        val padded = Bitmap.createBitmap(width + rowPadding / pixelStride, height, Bitmap.Config.ARGB_8888)
        padded.copyPixelsFromBuffer(plane.buffer)
        val cropped = Bitmap.createBitmap(padded, 0, 0, width, height)
        val out = ByteArrayOutputStream()
        cropped.compress(Bitmap.CompressFormat.JPEG, 60, out)
        if (cropped !== padded) padded.recycle()
        cropped.recycle()
        return out.toByteArray()
    }

    private fun upload(jpeg: ByteArray) {
        val client = HubClient(OkHttpTransport(), PreferenceManager.hubUrl(this), PreferenceManager.agentKey(this))
        try {
            client.uploadScreenshot(PreferenceManager.deviceId(this), jpeg)
        } catch (e: AuthRejectedException) {
            // the hub removed this phone; AgentService handles that on its next heartbeat
        }
    }

    private fun finish() {
        if (!finished.compareAndSet(false, true)) return
        try {
            reader?.setOnImageAvailableListener(null, null)
            display?.release()
            reader?.close()
            projection?.stop()
        } catch (e: Exception) {
            // best effort
        }
        display = null
        reader = null
        projection = null
        thread?.quitSafely()
        thread = null
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    override fun onDestroy() {
        finish()
        super.onDestroy()
    }
}
