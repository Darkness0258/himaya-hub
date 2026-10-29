package com.himaya.agent

/**
 * Himaya keys are secrets: `hma_...` is the parent's admin key and `hag_...` is one device's own key.
 * They must never be typed into the hub address box. There the app would treat the key as a host name,
 * and the lookup would send it to the network's DNS server.
 */
fun looksLikeKey(input: String): Boolean {
    val text = input.trim()
    return text.startsWith("hma_") || text.startsWith("hag_")
}
