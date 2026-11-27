import Foundation

/// Binary communication contract matching PROTOCOL.md (IDEX v1, Big-Endian).
enum DexProtocol {
    static let magic: [UInt8] = [0x49, 0x44, 0x45, 0x58] // "IDEX"
    static let version: UInt8 = 0x01
    static let headerSize = 12
    static let maxPayloadLength: UInt32 = 16_777_216
    static let defaultPort: UInt16 = 29480

    enum MsgType: UInt8 {
        case hello = 0x01
        case helloAck = 0x02
        case videoFrame = 0x10
        case mouseMove = 0x20
        case mouseButton = 0x21
        case mouseScroll = 0x22
        case keyEvent = 0x23
        case ping = 0x30
        case pong = 0x31
    }

    enum Codec: UInt8 {
        case jpeg = 0x01
        case h264AnnexB = 0x02
    }

    enum Flags {
        static let none: UInt16 = 0x0000
        static let keyframe: UInt16 = 0x0001
    }

    struct HelloPayload {
        let clientWidth: UInt16
        let clientHeight: UInt16
        let targetFPS: UInt8
        let preferredCodec: Codec
        let reserved: UInt16
    }

    struct HelloAckPayload {
        let canvasWidth: UInt16
        let canvasHeight: UInt16
        let actualFPS: UInt8
        let activeCodec: Codec
        let status: UInt16
    }

    struct MouseMovePayload {
        let normX: Float32
        let normY: Float32
    }

    struct MouseButtonPayload {
        let normX: Float32
        let normY: Float32
        let button: UInt8
        let action: UInt8 // 0 = up, 1 = down
    }

    struct MouseScrollPayload {
        let normX: Float32
        let normY: Float32
        let deltaX: Float32
        let deltaY: Float32
    }

    struct KeyEventPayload {
        let keyCode: UInt32
        let action: UInt8 // 0 = up, 1 = down
        let modifiers: UInt8
        let unicodeChar: UInt16
    }

    struct Packet {
        let msgType: MsgType
        let flags: UInt16
        let payload: Data
    }

    static func encodePacket(msgType: MsgType, flags: UInt16 = Flags.none, payload: Data) -> Data {
        var out = Data(capacity: headerSize + payload.count)
        out.append(contentsOf: magic)
        out.append(version)
        out.append(msgType.rawValue)
        appendUInt16BE(&out, flags)
        appendUInt32BE(&out, UInt32(payload.count))
        out.append(payload)
        return out
    }

    static func encodeHelloAck(_ ack: HelloAckPayload) -> Data {
        var payload = Data(capacity: 8)
        appendUInt16BE(&payload, ack.canvasWidth)
        appendUInt16BE(&payload, ack.canvasHeight)
        payload.append(ack.actualFPS)
        payload.append(ack.activeCodec.rawValue)
        appendUInt16BE(&payload, ack.status)
        return encodePacket(msgType: .helloAck, payload: payload)
    }

    static func encodeVideoFrame(
        frameSeq: UInt32,
        timestampUs: UInt64,
        codec: Codec,
        width: UInt16,
        height: UInt16,
        isKeyframe: Bool,
        frameData: Data
    ) -> Data {
        var payload = Data(capacity: 18 + frameData.count)
        appendUInt32BE(&payload, frameSeq)
        appendUInt64BE(&payload, timestampUs)
        payload.append(codec.rawValue)
        payload.append(0x00) // reserved
        appendUInt16BE(&payload, width)
        appendUInt16BE(&payload, height)
        payload.append(frameData)
        return encodePacket(
            msgType: .videoFrame,
            flags: isKeyframe ? Flags.keyframe : Flags.none,
            payload: payload
        )
    }

    static func encodePong(timestampUs: UInt64) -> Data {
        var payload = Data(capacity: 8)
        appendUInt64BE(&payload, timestampUs)
        return encodePacket(msgType: .pong, payload: payload)
    }

    static func decodeHello(_ payload: Data) -> HelloPayload? {
        var reader = BigEndianReader(data: payload)
        guard
            let w = reader.readUInt16(),
            let h = reader.readUInt16(),
            let fps = reader.readUInt8(),
            let codecRaw = reader.readUInt8(),
            let reserved = reader.readUInt16(),
            let codec = Codec(rawValue: codecRaw)
        else { return nil }
        return HelloPayload(
            clientWidth: w,
            clientHeight: h,
            targetFPS: fps,
            preferredCodec: codec,
            reserved: reserved
        )
    }

    static func decodeMouseMove(_ payload: Data) -> MouseMovePayload? {
        var reader = BigEndianReader(data: payload)
        guard let x = reader.readFloat32(), let y = reader.readFloat32() else { return nil }
        return MouseMovePayload(normX: x, normY: y)
    }

    static func decodeMouseButton(_ payload: Data) -> MouseButtonPayload? {
        var reader = BigEndianReader(data: payload)
        guard
            let x = reader.readFloat32(),
            let y = reader.readFloat32(),
            let button = reader.readUInt8(),
            let action = reader.readUInt8()
        else { return nil }
        return MouseButtonPayload(normX: x, normY: y, button: button, action: action)
    }

    static func decodeMouseScroll(_ payload: Data) -> MouseScrollPayload? {
        var reader = BigEndianReader(data: payload)
        guard
            let x = reader.readFloat32(),
            let y = reader.readFloat32(),
            let dx = reader.readFloat32(),
            let dy = reader.readFloat32()
        else { return nil }
        return MouseScrollPayload(normX: x, normY: y, deltaX: dx, deltaY: dy)
    }

    static func decodeKeyEvent(_ payload: Data) -> KeyEventPayload? {
        var reader = BigEndianReader(data: payload)
        guard
            let keyCode = reader.readUInt32(),
            let action = reader.readUInt8(),
            let modifiers = reader.readUInt8(),
            let unicode = reader.readUInt16()
        else { return nil }
        return KeyEventPayload(keyCode: keyCode, action: action, modifiers: modifiers, unicodeChar: unicode)
    }

    static func decodePing(_ payload: Data) -> UInt64? {
        var reader = BigEndianReader(data: payload)
        return reader.readUInt64()
    }

    private static func appendUInt16BE(_ data: inout Data, _ value: UInt16) {
        var be = value.bigEndian
        withUnsafeBytes(of: &be) { data.append(contentsOf: $0) }
    }

    private static func appendUInt32BE(_ data: inout Data, _ value: UInt32) {
        var be = value.bigEndian
        withUnsafeBytes(of: &be) { data.append(contentsOf: $0) }
    }

    private static func appendUInt64BE(_ data: inout Data, _ value: UInt64) {
        var be = value.bigEndian
        withUnsafeBytes(of: &be) { data.append(contentsOf: $0) }
    }
}

/// Safe alignment-independent Big-Endian binary reader.
struct BigEndianReader {
    private let bytes: [UInt8]
    private var offset: Int = 0

    init(data: Data) {
        self.bytes = Array(data)
    }

    mutating func readUInt8() -> UInt8? {
        guard offset + 1 <= bytes.count else { return nil }
        let value = bytes[offset]
        offset += 1
        return value
    }

    mutating func readUInt16() -> UInt16? {
        guard offset + 2 <= bytes.count else { return nil }
        let value = (UInt16(bytes[offset]) << 8) | UInt16(bytes[offset + 1])
        offset += 2
        return value
    }

    mutating func readUInt32() -> UInt32? {
        guard offset + 4 <= bytes.count else { return nil }
        let value = (UInt32(bytes[offset]) << 24)
            | (UInt32(bytes[offset + 1]) << 16)
            | (UInt32(bytes[offset + 2]) << 8)
            | UInt32(bytes[offset + 3])
        offset += 4
        return value
    }

    mutating func readUInt64() -> UInt64? {
        guard offset + 8 <= bytes.count else { return nil }
        var value: UInt64 = 0
        for i in 0..<8 {
            value = (value << 8) | UInt64(bytes[offset + i])
        }
        offset += 8
        return value
    }

    mutating func readFloat32() -> Float32? {
        guard let bits = readUInt32() else { return nil }
        return Float32(bitPattern: bits)
    }
}

/// Incremental TCP stream framing parser for IDEX v1 packets.
final class DexPacketParser {
    enum ParseError: Error {
        case invalidMagic
        case unsupportedVersion(UInt8)
        case payloadTooLarge(UInt32)
        case unknownMessageType(UInt8)
    }

    private var buffer = Data()

    func append(_ chunk: Data) throws -> [DexProtocol.Packet] {
        buffer.append(chunk)
        var packets: [DexProtocol.Packet] = []

        while buffer.count >= DexProtocol.headerSize {
            let header = Array(buffer.prefix(DexProtocol.headerSize))
            guard header[0] == DexProtocol.magic[0],
                  header[1] == DexProtocol.magic[1],
                  header[2] == DexProtocol.magic[2],
                  header[3] == DexProtocol.magic[3] else {
                throw ParseError.invalidMagic
            }
            let version = header[4]
            guard version == DexProtocol.version else {
                throw ParseError.unsupportedVersion(version)
            }
            let msgTypeRaw = header[5]
            guard let msgType = DexProtocol.MsgType(rawValue: msgTypeRaw) else {
                throw ParseError.unknownMessageType(msgTypeRaw)
            }
            let flags = (UInt16(header[6]) << 8) | UInt16(header[7])
            let payloadLen = (UInt32(header[8]) << 24)
                | (UInt32(header[9]) << 16)
                | (UInt32(header[10]) << 8)
                | UInt32(header[11])

            guard payloadLen <= DexProtocol.maxPayloadLength else {
                throw ParseError.payloadTooLarge(payloadLen)
            }

            let totalLength = DexProtocol.headerSize + Int(payloadLen)
            guard buffer.count >= totalLength else {
                break
            }

            let payload = Data(buffer.subdata(in: DexProtocol.headerSize..<totalLength))
            buffer.removeFirst(totalLength)
            packets.append(DexProtocol.Packet(msgType: msgType, flags: flags, payload: payload))
        }

        return packets
    }

    func reset() {
        buffer.removeAll(keepingCapacity: false)
    }
}
