package com.himaya.agent

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class KeysTest {
    @Test
    fun adminAndDeviceKeysAreRecognised() {
        assertTrue(looksLikeKey("hma_EXAMPLE-not-a-real-key-000000000000000000"))
        assertTrue(looksLikeKey("  hag_abc123  "))
        assertTrue(looksLikeKey("hma_x"))
    }

    @Test
    fun realHubAddressesAreNotKeys() {
        assertFalse(looksLikeKey("192.168.1.20:8000"))
        assertFalse(looksLikeKey("https://hub.example.com"))
        assertFalse(looksLikeKey("http://hma.example.com")) // a host that merely starts with "hma"
        assertFalse(looksLikeKey(""))
    }
}
