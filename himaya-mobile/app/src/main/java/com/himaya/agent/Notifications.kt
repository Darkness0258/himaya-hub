package com.himaya.agent

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent

/**
 * All notifications in one place.
 *
 * The persistent "Himaya is active" notification is the agent's visible indicator (project rule: visible,
 * not hidden). Messages from the parent use a separate HIGH-importance channel; the first version sent them
 * on the quiet status channel, where a "high priority" flag does nothing on Android 8+.
 */
object Notifications {
    const val CHANNEL_STATUS = "himaya_status"
    const val CHANNEL_MESSAGES = "himaya_messages"
    const val CHANNEL_REQUESTS = "himaya_requests"

    const val ID_STATUS = 1001
    const val ID_CAPTURE = 1002
    const val ID_MESSAGE = 2002
    const val ID_REQUEST = 2003

    const val ACTION_SCREEN_SHARE = "com.himaya.agent.SCREEN_SHARE_REQUEST"

    fun ensureChannels(context: Context) {
        val manager = context.getSystemService(NotificationManager::class.java) ?: return
        manager.createNotificationChannel(
            NotificationChannel(CHANNEL_STATUS, "Himaya is active", NotificationManager.IMPORTANCE_LOW).apply {
                description = "Shows that Himaya is running on this phone."
                setShowBadge(false)
            },
        )
        manager.createNotificationChannel(
            NotificationChannel(CHANNEL_MESSAGES, "Messages from your parent", NotificationManager.IMPORTANCE_HIGH).apply {
                description = "Short messages your parent sends to this phone."
            },
        )
        manager.createNotificationChannel(
            NotificationChannel(CHANNEL_REQUESTS, "Screen requests", NotificationManager.IMPORTANCE_HIGH).apply {
                description = "When your parent asks to see your screen, you are asked to allow it."
            },
        )
    }

    private fun openApp(context: Context, action: String? = null): PendingIntent {
        val intent = Intent(context, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP
            if (action != null) this.action = action
        }
        return PendingIntent.getActivity(context, if (action == null) 0 else 1, intent, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
    }

    /** The persistent notification of the foreground service. */
    fun status(context: Context, text: String, title: String = "Himaya is active"): Notification =
        Notification.Builder(context, CHANNEL_STATUS)
            .setSmallIcon(R.drawable.ic_stat_himaya)
            .setContentTitle(title)
            .setContentText(text)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setCategory(Notification.CATEGORY_SERVICE)
            .setContentIntent(openApp(context))
            .build()

    fun message(context: Context, text: String) {
        val manager = context.getSystemService(NotificationManager::class.java) ?: return
        manager.notify(
            ID_MESSAGE,
            Notification.Builder(context, CHANNEL_MESSAGES)
                .setSmallIcon(R.drawable.ic_stat_himaya)
                .setContentTitle("Message from your parent")
                .setContentText(text)
                .setStyle(Notification.BigTextStyle().bigText(text))
                .setAutoCancel(true)
                .setCategory(Notification.CATEGORY_MESSAGE)
                .setContentIntent(openApp(context))
                .build(),
        )
    }

    /** Asks the child to approve a screen capture. Android needs a person to tap the system dialog, so this is a notification, not a silent action. */
    fun screenRequest(context: Context) {
        val manager = context.getSystemService(NotificationManager::class.java) ?: return
        manager.notify(
            ID_REQUEST,
            Notification.Builder(context, CHANNEL_REQUESTS)
                .setSmallIcon(R.drawable.ic_stat_himaya)
                .setContentTitle("Your parent asked to see your screen")
                .setContentText("Tap to choose whether to allow it.")
                .setAutoCancel(true)
                .setCategory(Notification.CATEGORY_CALL)
                .setContentIntent(openApp(context, ACTION_SCREEN_SHARE))
                .build(),
        )
    }

    fun cancelRequest(context: Context) {
        context.getSystemService(NotificationManager::class.java)?.cancel(ID_REQUEST)
    }
}
