package com.himaya.agent

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class DnsPacketTest {

    /** Bytes from 0..255 values (Kotlin Bytes are signed, so 222 needs an explicit conversion). */
    private fun ip(vararg octets: Int): ByteArray = ByteArray(octets.size) { octets[it].toByte() }

    private fun dnsQuery(name: String, type: Int, id: Int = 0x1234): ByteArray {
        val out = java.io.ByteArrayOutputStream()
        out.write(byteArrayOf((id shr 8).toByte(), id.toByte(), 0x01, 0x00, 0, 1, 0, 0, 0, 0, 0, 0)) // RD set, one question
        for (label in name.split('.')) {
            out.write(label.length)
            out.write(label.toByteArray(Charsets.ISO_8859_1))
        }
        out.write(0)
        out.write(byteArrayOf((type shr 8).toByte(), type.toByte(), 0, 1))
        return out.toByteArray()
    }

    private fun ipUdp(
        dns: ByteArray,
        src: IntArray = intArrayOf(10, 111, 222, 1),
        dst: IntArray = intArrayOf(10, 111, 222, 2),
        srcPort: Int = 40000,
        dstPort: Int = 53,
        fragmentField: Int = 0x4000,
        protocol: Int = 17,
    ): ByteArray {
        val total = 20 + 8 + dns.size
        val p = ByteArray(total)
        p[0] = 0x45
        p[2] = (total shr 8).toByte(); p[3] = total.toByte()
        p[6] = (fragmentField shr 8).toByte(); p[7] = fragmentField.toByte()
        p[8] = 64
        p[9] = protocol.toByte()
        for (i in 0..3) { p[12 + i] = src[i].toByte(); p[16 + i] = dst[i].toByte() }
        val sum = DnsPacket.checksum(p, 0, 20)
        p[10] = (sum shr 8).toByte(); p[11] = sum.toByte()
        p[20] = (srcPort shr 8).toByte(); p[21] = srcPort.toByte()
        p[22] = (dstPort shr 8).toByte(); p[23] = dstPort.toByte()
        val udp = 8 + dns.size
        p[24] = (udp shr 8).toByte(); p[25] = udp.toByte()
        System.arraycopy(dns, 0, p, 28, dns.size)
        return p
    }

    @Test
    fun checksumMatchesAKnownIpv4HeaderVector() {
        val header = byteArrayOf(
            0x45, 0x00, 0x00, 0x73, 0x00, 0x00, 0x40, 0x00, 0x40, 0x11, 0x00, 0x00,
            0xc0.toByte(), 0xa8.toByte(), 0x00, 0x01, 0xc0.toByte(), 0xa8.toByte(), 0x00, 0xc7.toByte(),
        )
        assertEquals(0xb861, DnsPacket.checksum(header, 0, 20))
    }

    @Test
    fun parsesAWellFormedDnsQuery() {
        val packet = ipUdp(dnsQuery("www.TikTok.com", DnsPacket.TYPE_A))
        val query = DnsPacket.parseUdpQuery(packet, packet.size)
        assertNotNull(query)
        assertEquals(40000, query!!.srcPort)
        assertEquals(53, query.dstPort)
        assertArrayEquals(ip(10, 111, 222, 1), query.srcIp)
        val q = DnsPacket.question(query.dns)
        assertEquals("www.tiktok.com", q!!.name)
        assertEquals(DnsPacket.TYPE_A, q.type)
    }

    @Test
    fun ignoresEverythingThatIsNotAPlainDnsQuery() {
        val dns = dnsQuery("example.com", DnsPacket.TYPE_A)
        val notDns = ipUdp(dns, dstPort = 443)
        val tcp = ipUdp(dns, protocol = 6)
        val fragment = ipUdp(dns, fragmentField = 0x2000)
        val ipv6 = ipUdp(dns).also { it[0] = 0x65 }
        for (packet in listOf(notDns, tcp, fragment, ipv6)) assertNull(DnsPacket.parseUdpQuery(packet, packet.size))
        assertNull(DnsPacket.parseUdpQuery(ByteArray(10), 10))
        val good = ipUdp(dns)
        assertNull(DnsPacket.parseUdpQuery(good, good.size - 3)) // truncated read
    }

    @Test
    fun theResponsePacketComesBackFromTheAskedAddressWithAValidChecksum() {
        val packet = ipUdp(dnsQuery("example.com", DnsPacket.TYPE_A))
        val query = DnsPacket.parseUdpQuery(packet, packet.size)!!
        val dnsReply = DnsPacket.blockedResponse(query.dns)!!
        val reply = DnsPacket.buildUdpResponse(query, dnsReply)
        assertEquals(0, DnsPacket.checksum(reply, 0, 20)) // a correct header sums to zero
        assertArrayEquals(ip(10, 111, 222, 2), reply.copyOfRange(12, 16)) // source = the fake DNS address
        assertArrayEquals(ip(10, 111, 222, 1), reply.copyOfRange(16, 20)) // destination = the asker
        assertEquals(53, ((reply[20].toInt() and 0xFF) shl 8) or (reply[21].toInt() and 0xFF))
        assertEquals(40000, ((reply[22].toInt() and 0xFF) shl 8) or (reply[23].toInt() and 0xFF))
        assertEquals(reply.size, ((reply[2].toInt() and 0xFF) shl 8) or (reply[3].toInt() and 0xFF))
        assertArrayEquals(dnsReply, reply.copyOfRange(28, reply.size))
    }

    @Test
    fun blockedAQueryGetsAZeroAddress() {
        val reply = DnsPacket.blockedResponse(dnsQuery("tiktok.com", DnsPacket.TYPE_A, id = 0xBEEF))!!
        assertEquals(0xBE, reply[0].toInt() and 0xFF)
        assertEquals(0xEF, reply[1].toInt() and 0xFF)
        assertEquals(0x81, reply[2].toInt() and 0xFF) // QR + RD
        assertEquals(0x80, reply[3].toInt() and 0xFF) // RA, RCODE 0
        assertEquals(1, reply[7].toInt()) // one answer
        assertEquals(4, reply[reply.size - 5].toInt()) // RDLENGTH
        assertTrue(reply.takeLast(4).all { it.toInt() == 0 })
    }

    @Test
    fun blockedAaaaGetsColonColonAndOtherTypesGetAnEmptyAnswer() {
        val aaaa = DnsPacket.blockedResponse(dnsQuery("tiktok.com", DnsPacket.TYPE_AAAA))!!
        assertEquals(1, aaaa[7].toInt())
        assertEquals(16, aaaa[aaaa.size - 17].toInt())
        val https = DnsPacket.blockedResponse(dnsQuery("tiktok.com", 65))!!
        assertEquals(0, https[7].toInt())
        assertEquals(0x80, https[3].toInt() and 0xFF)
    }

    @Test
    fun servFailHasRcode2AndKeepsTheQuestion() {
        val query = dnsQuery("example.com", DnsPacket.TYPE_A)
        val reply = DnsPacket.servFail(query)!!
        assertEquals(2, reply[3].toInt() and 0x0F)
        assertEquals(0, reply[7].toInt())
        assertArrayEquals(query.copyOfRange(12, query.size), reply.copyOfRange(12, reply.size))
    }

    @Test
    fun malformedQuestionsAreRejectedNotCrashed() {
        assertNull(DnsPacket.question(ByteArray(0)))
        assertNull(DnsPacket.question(ByteArray(12)))
        val pointer = dnsQuery("a.com", 1).also { it[12] = 0xC0.toByte() } // compression pointer in a question
        assertNull(DnsPacket.question(pointer))
        val tooLong = dnsQuery("a.com", 1).also { it[12] = 60 } // label longer than the packet
        assertNull(DnsPacket.question(tooLong))
        assertNull(DnsPacket.blockedResponse(ByteArray(5)))
        assertNull(DnsPacket.servFail(ByteArray(5)))
    }
}
