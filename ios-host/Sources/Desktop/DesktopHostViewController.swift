import UIKit

/// Root ViewController hosting the 1920x1080 DeX canvas, TCP stream server, and VideoToolbox/JPEG encoder.
final class DesktopHostViewController: UIViewController {
    private let statusLabel = UILabel()
    private let canvasContainer = UIView()
    private let desktopCanvas = DesktopCanvasView(frame: CGRect(origin: .zero, size: DesktopCanvasView.canvasSize))

    private let tcpServer = DexTCPServer(port: DexProtocol.defaultPort)
    private let encoder = VideoEncoder(width: 1920, height: 1080, fps: 30)

    private var streamTimer: DispatchSourceTimer?
    private var frameSeq: UInt32 = 0
    private var activeCodec: DexProtocol.Codec = .jpeg

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = UIColor(red: 0.03, green: 0.04, blue: 0.07, alpha: 1.0)
        setupLayout()
        wireServerCallbacks()
        startServer()
    }

    override func viewDidLayoutSubviews() {
        super.viewDidLayoutSubviews()
        layoutCanvasPreview()
    }

    private func setupLayout() {
        statusLabel.translatesAutoresizingMaskIntoConstraints = false
        statusLabel.font = .monospacedSystemFont(ofSize: 13, weight: .semibold)
        statusLabel.textColor = .white
        statusLabel.backgroundColor = UIColor.white.withAlphaComponent(0.1)
        statusLabel.layer.cornerRadius = 8
        statusLabel.clipsToBounds = true
        statusLabel.textAlignment = .center
        statusLabel.text = "  Starting iPhone DeX TCP Server on :29480...  "
        view.addSubview(statusLabel)

        canvasContainer.translatesAutoresizingMaskIntoConstraints = false
        canvasContainer.clipsToBounds = true
        canvasContainer.layer.cornerRadius = 10
        canvasContainer.layer.borderWidth = 1
        canvasContainer.layer.borderColor = UIColor.white.withAlphaComponent(0.2).cgColor
        view.addSubview(canvasContainer)

        canvasContainer.addSubview(desktopCanvas)

        NSLayoutConstraint.activate([
            statusLabel.topAnchor.constraint(equalTo: view.safeAreaLayoutGuide.topAnchor, constant: 10),
            statusLabel.leadingAnchor.constraint(equalTo: view.safeAreaLayoutGuide.leadingAnchor, constant: 16),
            statusLabel.trailingAnchor.constraint(equalTo: view.safeAreaLayoutGuide.trailingAnchor, constant: -16),
            statusLabel.heightAnchor.constraint(equalToConstant: 36),

            canvasContainer.topAnchor.constraint(equalTo: statusLabel.bottomAnchor, constant: 12),
            canvasContainer.leadingAnchor.constraint(equalTo: view.safeAreaLayoutGuide.leadingAnchor, constant: 12),
            canvasContainer.trailingAnchor.constraint(equalTo: view.safeAreaLayoutGuide.trailingAnchor, constant: -12),
            canvasContainer.bottomAnchor.constraint(equalTo: view.safeAreaLayoutGuide.bottomAnchor, constant: -12)
        ])
    }

    private func layoutCanvasPreview() {
        let containerSize = canvasContainer.bounds.size
        guard containerSize.width > 0, containerSize.height > 0 else { return }

        let targetW = DesktopCanvasView.canvasSize.width
        let targetH = DesktopCanvasView.canvasSize.height
        let scale = min(containerSize.width / targetW, containerSize.height / targetH)

        desktopCanvas.transform = CGAffineTransform(scaleX: scale, y: scale)
        desktopCanvas.center = CGPoint(x: containerSize.width / 2.0, y: containerSize.height / 2.0)
    }

    private func wireServerCallbacks() {
        encoder.onEncodedH264Frame = { [weak self] annexB, isKeyframe, timestampUs in
            guard let self else { return }
            let seq = self.frameSeq
            self.frameSeq &+= 1
            self.tcpServer.sendVideoFrame(
                frameSeq: seq,
                timestampUs: timestampUs,
                codec: .h264AnnexB,
                width: 1920,
                height: 1080,
                isKeyframe: isKeyframe,
                frameData: annexB
            )
        }

        tcpServer.onClientConnected = { [weak self] endpoint, codec, fps in
            guard let self else { return }
            self.activeCodec = codec
            self.frameSeq = 0
            let codecName = codec == .h264AnnexB ? "H264" : "JPEG"
            self.statusLabel.text = "Connected: \(endpoint) | 1920x1080 @ \(fps)fps [\(codecName)]"
            self.statusLabel.backgroundColor = UIColor.systemGreen.withAlphaComponent(0.32)

            if codec == .h264AnnexB {
                _ = self.encoder.startH264Session()
            } else {
                self.encoder.stopH264Session()
            }
            self.startStreaming(fps: Int(fps))
        }

        tcpServer.onClientDisconnected = { [weak self] in
            guard let self else { return }
            self.stopStreaming()
            self.encoder.stopH264Session()
            self.statusLabel.text = "Listening on :\(DexProtocol.defaultPort) (Waiting for Windows Client...)"
            self.statusLabel.backgroundColor = UIColor.white.withAlphaComponent(0.1)
        }

        tcpServer.onMouseMove = { [weak self] x, y in
            self?.desktopCanvas.injectMouseMove(normX: x, normY: y)
        }

        tcpServer.onMouseButton = { [weak self] x, y, btn, isDown in
            self?.desktopCanvas.injectMouseButton(normX: x, normY: y, button: btn, isDown: isDown)
        }

        tcpServer.onKeyEvent = { [weak self] keyCode, action, _, unicodeChar in
            self?.desktopCanvas.injectKey(keyCode: keyCode, unicodeChar: unicodeChar, isDown: action == 1)
        }
    }

    private func startServer() {
        do {
            try tcpServer.start()
            statusLabel.text = "Listening on :\(DexProtocol.defaultPort) (Waiting for Windows Client...)"
        } catch {
            statusLabel.text = "Server Error: \(error.localizedDescription)"
            statusLabel.backgroundColor = UIColor.systemRed.withAlphaComponent(0.4)
        }
    }

    private func startStreaming(fps: Int) {
        stopStreaming()
        let intervalNs = UInt64(1_000_000_000 / max(1, fps))
        let timer = DispatchSource.makeTimerSource(queue: .main)
        timer.schedule(deadline: .now(), repeating: .nanoseconds(Int(intervalNs)))
        timer.setEventHandler { [weak self] in
            self?.captureAndSendFrame()
        }
        timer.resume()
        streamTimer = timer
    }

    private func stopStreaming() {
        streamTimer?.cancel()
        streamTimer = nil
    }

    private func captureAndSendFrame() {
        guard tcpServer.isHandshakeComplete else { return }
        let snapshot = desktopCanvas.renderSnapshot()
        let nowUs = UInt64(Date().timeIntervalSince1970 * 1_000_000)

        switch activeCodec {
        case .jpeg:
            guard let jpeg = encoder.encodeJPEG(snapshot, quality: 0.72) else { return }
            let seq = frameSeq
            frameSeq &+= 1
            tcpServer.sendVideoFrame(
                frameSeq: seq,
                timestampUs: nowUs,
                codec: .jpeg,
                width: 1920,
                height: 1080,
                isKeyframe: true,
                frameData: jpeg
            )
        case .h264AnnexB:
            encoder.encodeH264(image: snapshot, timestampUs: nowUs, forceKeyframe: frameSeq % 60 == 0)
        }
    }
}
