package com.himaya.agent

/**
 * Pure-Kotlin DNS / IPv4 / UDP helpers for the website filter.
 *
 * The VPN tunnel only carries DNS (the tunnel's route table contains a single fake DNS address), so
 * every packet read from the tunnel is an IPv4 UDP datagram to port 53. This object parses those,
 * builds the matching reply packets, and can fabricate DNS answers locally ("sinkhole" for a paused
 * phone, SERVFAIL when nothing answers).
 *
 * No Android classes are used on purpose: it is unit-tested on a plain JVM.
 */
object DnsPacket {
    private const val PROTO_UDP = 17
    const val TYPE_A = 1
    const val TYPE_AAAA = 28

    class UdpQuery(
        val srcIp: ByteArray,
        val dstIp: ByteArray,
        val srcPort: Int,
        val dstPort: Int,
        val dns: ByteArray,
    )

    private fun u8(b: ByteArray, i: Int): Int = b[i].toInt() and 0xFF
    private fun u16(b: ByteArray, i: Int): Int = (u8(b, i) shl 8) or u8(b, i + 1)
    private fun put16(b: ByteArray, i: Int, v: Int) {
        b[i] = (v shr 8).toByte()
        b[i + 1] = v.toByte()
    }

    /** Parse an IPv4 packet read from the tunnel. Returns null for anything that is not a plain DNS query. */
    fun parseUdpQuery(packet: ByteArray, length: Int): UdpQuery? {
        if (length < 28 || length > packet.size) return null
        val first = u8(packet, 0)
        if (first shr 4 != 4) return null // IPv6 and others are not routed into the tunnel
        val ihl = (first and 0x0F) * 4
        if (ihl < 20 || length < ihl + 8) return null
        val totalLength = u16(packet, 2)
        if (totalLength < ihl + 8 || totalLength > length) return null
        if (u8(packet, 9) != PROTO_UDP) return null
        if ((u16(packet, 6) and 0x3FFF) != 0) return null // fragmented: more-fragments flag or a fragment offset
        val srcPort = u16(packet, ihl)
        val dstPort = u16(packet, ihl + 2)
        if (dstPort != 53) return null
        val udpLength = u16(packet, ihl + 4)
        if (udpLength < 8 || ihl + udpLength > totalLength) return null
        val dns = packet.copyOfRange(ihl + 8, ihl + udpLength)
        if (dns.size < 12) return null
        return UdpQuery(packet.copyOfRange(12, 16), packet.copyOfRange(16, 20), srcPort, dstPort, dns)
    }

    /** Wrap a DNS reply in an IPv4/UDP packet that goes back to whoever asked. */
    fun buildUdpResponse(query: UdpQuery, dnsResponse: ByteArray): ByteArray {
        val total = 20 + 8 + dnsResponse.size
        require(total <= 65535) { "DNS reply too large" }
        val out = ByteArray(total)
        out[0] = 0x45
        put16(out, 2, total)
        put16(out, 6, 0x4000) // don't fragment
        out[8] = 64 // TTL
        out[9] = PROTO_UDP.toByte()
        System.arraycopy(query.dstIp, 0, out, 12, 4) // the reply comes from the address that was asked
        System.arraycopy(query.srcIp, 0, out, 16, 4)
        put16(out, 10, checksum(out, 0, 20))
        put16(out, 20, query.dstPort)
        put16(out, 22, query.srcPort)
        put16(out, 24, 8 + dnsResponse.size)
        // UDP checksum 0 = "not computed", which is legal for IPv4
        System.arraycopy(dnsResponse, 0, out, 28, dnsResponse.size)
        return out
    }

    /** Standard Internet checksum (RFC 1071). Over a header that already contains its checksum the result is 0. */
    fun checksum(data: ByteArray, offset: Int, length: Int): Int {
        var sum = 0L
        var i = offset
        val end = offset + length
        while (i + 1 < end) {
            sum += ((data[i].toInt() and 0xFF) shl 8) or (data[i + 1].toInt() and 0xFF)
            i += 2
        }
        if (i < end) sum += (data[i].toInt() and 0xFF) shl 8
        while (sum shr 16 != 0L) sum = (sum and 0xFFFF) + (sum shr 16)
        return (sum.inv() and 0xFFFF).toInt()
    }

    class Question(val name: String, val type: Int, val endOffset: Int)

    /** First question of a DNS message (compression pointers are not valid there and are rejected). */
    fun question(dns: ByteArray): Question? {
        if (dns.size < 17) return null
        if (u16(dns, 4) < 1) return null
        val labels = ArrayList<String>()
        var pos = 12
        var total = 0
        while (true) {
            if (pos >= dns.size) return null
            val len = u8(dns, pos)
            pos++
            if (len == 0) break
            if (len and 0xC0 != 0 || len > 63) return null
            if (pos + len > dns.size) return null
            labels.add(String(dns, pos, len, Charsets.ISO_8859_1))
            pos += len
            total += len + 1
            if (total > 253) return null
        }
        if (pos + 4 > dns.size) return null
        return Question(labels.joinToString(".").lowercase(), u16(dns, pos), pos + 4)
    }

    private fun header(query: ByteArray, flags: Int, answers: Int): ByteArray {
        val h = ByteArray(12)
        h[0] = query[0]
        h[1] = query[1]
        put16(h, 2, flags)
        put16(h, 4, 1)
        put16(h, 6, answers)
        return h
    }

    /** Answer for a blocked name: 0.0.0.0 for A, :: for AAAA, an empty NOERROR for every other type. */
    fun blockedResponse(query: ByteArray, ttl: Int = 60): ByteArray? {
        val q = question(query) ?: return null
        val recursionDesired = u8(query, 2) and 0x01
        val flags = 0x8000 or (recursionDesired shl 8) or 0x0080 // QR, RD echoed, RA, RCODE 0
        val questionBytes = query.copyOfRange(12, q.endOffset)
        val answer: ByteArray = when (q.type) {
            TYPE_A -> sinkholeRecord(TYPE_A, ttl, 4)
            TYPE_AAAA -> sinkholeRecord(TYPE_AAAA, ttl, 16)
            else -> ByteArray(0)
        }
        return header(query, flags, if (answer.isEmpty()) 0 else 1) + questionBytes + answer
    }

    private fun sinkholeRecord(type: Int, ttl: Int, addressBytes: Int): ByteArray {
        val record = ByteArray(2 + 10 + addressBytes)
        record[0] = 0xC0.toByte() // pointer to the name in the question
        record[1] = 0x0C
        put16(record, 2, type)
        put16(record, 4, 1) // class IN
        record[6] = (ttl shr 24).toByte()
        record[7] = (ttl shr 16).toByte()
        record[8] = (ttl shr 8).toByte()
        record[9] = ttl.toByte()
        put16(record, 10, addressBytes)
        return record // the address bytes stay 0 = 0.0.0.0 / ::
    }

    /** SERVFAIL, so the app moves on at once instead of waiting for its own timeout. */
    fun servFail(query: ByteArray): ByteArray? {
        val q = question(query) ?: return null
        val recursionDesired = u8(query, 2) and 0x01
        val flags = 0x8000 or (recursionDesired shl 8) or 0x0080 or 0x0002
        return header(query, flags, 0) + query.copyOfRange(12, q.endOffset)
    }
}
