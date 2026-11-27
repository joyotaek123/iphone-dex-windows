import Foundation
import Network

/// TCP server listening on port 29480 (reachable over USB usbmuxd or Wi-Fi LAN).
final class DexTCPServer {
    private let port: UInt16
    private let networkQueue = DispatchQueue(label: "com.iphonedex.tcpserver", qos: .userInteractive)
    private var listener: NWListener?
    private var activeConnection: NWConnection?
    private let parser = DexPacketParser()

    private(set) var isHandshakeComplete = false
    private(set) var negotiatedCodec: DexProtocol.Codec = .jpeg
    private(set) var negotiatedFPS: UInt8 = 30

    var onClientConnected: ((_ endpoint: String, _ codec: DexProtocol.Codec, _ fps: UInt8) -> Void)?
    var onClientDisconnected: (() -> Void)?
    var onMouseMove: ((_ normX: Float32, _ normY: Float32) -> Void)?
    var onMouseButton: ((_ normX: Float32, _ normY: Float32, _ button: UInt8, _ isDown: Bool) -> Void)?
    var onMouseScroll: ((_ normX: Float32, _ normY: Float32, _ deltaX: Float32, _ deltaY: Float32) -> Void)?
    var onKeyEvent: ((_ keyCode: UInt32, _ action: UInt8, _ modifiers: UInt8, _ unicodeChar: UInt16) -> Void)?

    init(port: UInt16 = DexProtocol.defaultPort) {
        self.port = port
    }

    func start() throws {
        let tcpOptions = NWProtocolTCP.Options()
        tcpOptions.noDelay = true
        let params = NWParameters(tls: nil, tcp: tcpOptions)
        params.allowLocalEndpointReuse = true

        guard let nwPort = NWEndpoint.Port(rawValue: port) else {
            throw NSError(domain: "DexTCPServer", code: -1, userInfo: [NSLocalizedDescriptionKey: "Invalid port \(port)"])
        }

        let newListener = try NWListener(using: params, on: nwPort)
        newListener.newConnectionHandler = { [weak self] connection in
            self?.acceptConnection(connection)
        }
        newListener.start(queue: networkQueue)
        self.listener = newListener
    }

    func stop() {
        activeConnection?.cancel()
        activeConnection = nil
        listener?.cancel()
        listener = nil
        isHandshakeComplete = false
    }

    func sendVideoFrame(
        frameSeq: UInt32,
        timestampUs: UInt64,
        codec: DexProtocol.Codec,
        width: UInt16,
        height: UInt16,
        isKeyframe: Bool,
        frameData: Data
    ) {
        guard isHandshakeComplete, let connection = activeConnection else { return }
        let packet = DexProtocol.encodeVideoFrame(
            frameSeq: frameSeq,
            timestampUs: timestampUs,
            codec: codec,
            width: width,
            height: height,
            isKeyframe: isKeyframe,
            frameData: frameData
        )
        sendRaw(packet, on: connection)
    }

    private func acceptConnection(_ connection: NWConnection) {
        activeConnection?.cancel()
        parser.reset()
        isHandshakeComplete = false
        activeConnection = connection

        connection.stateUpdateHandler = { [weak self] state in
            guard let self else { return }
            switch state {
            case .failed, .cancelled:
                if self.activeConnection === connection {
                    self.activeConnection = nil
                    self.isHandshakeComplete = false
                    DispatchQueue.main.async {
                        self.onClientDisconnected?()
                    }
                }
            default:
                break
            }
        }

        connection.start(queue: networkQueue)
        receiveLoop(on: connection)
    }

    private func receiveLoop(on connection: NWConnection) {
        connection.receive(minimumIncompleteLength: 1, maximumLength: 65536) { [weak self] data, _, isComplete, error in
            guard let self else { return }

            if let data, !data.isEmpty {
                do {
                    let packets = try self.parser.append(data)
                    for packet in packets {
                        self.handlePacket(packet, on: connection)
                    }
                } catch {
                    connection.cancel()
                    return
                }
            }

            if isComplete || error != nil {
                connection.cancel()
                return
            }

            self.receiveLoop(on: connection)
        }
    }

    private func handlePacket(_ packet: DexProtocol.Packet, on connection: NWConnection) {
        switch packet.msgType {
        case .hello:
            guard let hello = DexProtocol.decodeHello(packet.payload) else { return }
            let fps = max(UInt8(1), min(hello.targetFPS, UInt8(60)))
            let codec = hello.preferredCodec
            self.negotiatedCodec = codec
            self.negotiatedFPS = fps
            self.isHandshakeComplete = true

            let ack = DexProtocol.HelloAckPayload(
                canvasWidth: 1920,
                canvasHeight: 1080,
                actualFPS: fps,
                activeCodec: codec,
                status: 0
            )
            sendRaw(DexProtocol.encodeHelloAck(ack), on: connection)
            let endpointDesc = "\(connection.endpoint)"
            DispatchQueue.main.async {
                self.onClientConnected?(endpointDesc, codec, fps)
            }

        case .mouseMove:
            guard let move = DexProtocol.decodeMouseMove(packet.payload) else { return }
            DispatchQueue.main.async {
                self.onMouseMove?(move.normX, move.normY)
            }

        case .mouseButton:
            guard let btn = DexProtocol.decodeMouseButton(packet.payload) else { return }
            let isDown = btn.action == 1
            DispatchQueue.main.async {
                self.onMouseButton?(btn.normX, btn.normY, btn.button, isDown)
            }

        case .mouseScroll:
            guard let scroll = DexProtocol.decodeMouseScroll(packet.payload) else { return }
            DispatchQueue.main.async {
                self.onMouseScroll?(scroll.normX, scroll.normY, scroll.deltaX, scroll.deltaY)
            }

        case .keyEvent:
            guard let key = DexProtocol.decodeKeyEvent(packet.payload) else { return }
            DispatchQueue.main.async {
                self.onKeyEvent?(key.keyCode, key.action, key.modifiers, key.unicodeChar)
            }

        case .ping:
            if let ts = DexProtocol.decodePing(packet.payload) {
                sendRaw(DexProtocol.encodePong(timestampUs: ts), on: connection)
            }

        case .helloAck, .videoFrame, .pong:
            break
        }
    }

    private func sendRaw(_ data: Data, on connection: NWConnection) {
        connection.send(content: data, completion: .contentProcessed { _ in })
    }
}
