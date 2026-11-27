import UIKit

/// Virtual 1920x1080 (16:9) desktop surface rendered on iOS and streamed to Windows.
final class DesktopCanvasView: UIView {
    static let canvasSize = CGSize(width: 1920, height: 1080)

    private let backgroundLayer = CAGradientLayer()
    private let floatingWindow = FloatingWindowView(frame: CGRect(x: 420, y: 180, width: 1080, height: 580))
    private let taskbarView = UIView()
    private let startPill = UILabel()
    private let telemetryLabel = UILabel()
    private let clockLabel = UILabel()
    private let cursorView = UIView()
    private let rippleLayer = CAShapeLayer()

    private var totalRemoteClicks = 0
    private var lastPointerCanvasPos = CGPoint(x: 960, y: 540)
    private var clockTimer: Timer?

    override init(frame: CGRect) {
        super.init(frame: CGRect(origin: .zero, size: Self.canvasSize))
        setupDesktop()
    }

    required init?(coder: NSCoder) {
        fatalError("init(coder:) has not been implemented")
    }

    deinit {
        clockTimer?.invalidate()
    }

    private func setupDesktop() {
        backgroundLayer.frame = bounds
        backgroundLayer.colors = [
            UIColor(red: 0.05, green: 0.09, blue: 0.16, alpha: 1.0).cgColor,
            UIColor(red: 0.09, green: 0.16, blue: 0.28, alpha: 1.0).cgColor,
            UIColor(red: 0.04, green: 0.07, blue: 0.13, alpha: 1.0).cgColor
        ]
        backgroundLayer.startPoint = CGPoint(x: 0, y: 0)
        backgroundLayer.endPoint = CGPoint(x: 1, y: 1)
        layer.addSublayer(backgroundLayer)

        let watermark = UILabel(frame: CGRect(x: 48, y: 38, width: 900, height: 48))
        watermark.text = "iPhone DeX Desktop (1920x1080) — Phase 1 PoC"
        watermark.font = .systemFont(ofSize: 24, weight: .semibold)
        watermark.textColor = UIColor.white.withAlphaComponent(0.35)
        addSubview(watermark)

        addSubview(floatingWindow)

        taskbarView.frame = CGRect(x: 0, y: bounds.height - 64, width: bounds.width, height: 64)
        taskbarView.backgroundColor = UIColor(red: 0.04, green: 0.06, blue: 0.10, alpha: 0.94)
        let topBorder = UIView(frame: CGRect(x: 0, y: 0, width: bounds.width, height: 1))
        topBorder.backgroundColor = UIColor.white.withAlphaComponent(0.14)
        taskbarView.addSubview(topBorder)
        addSubview(taskbarView)

        startPill.frame = CGRect(x: 24, y: 12, width: 170, height: 40)
        startPill.text = "  iPhone DeX"
        startPill.font = .systemFont(ofSize: 20, weight: .bold)
        startPill.textColor = .white
        startPill.backgroundColor = UIColor(red: 0.18, green: 0.52, blue: 0.98, alpha: 1.0)
        startPill.layer.cornerRadius = 10
        startPill.clipsToBounds = true
        taskbarView.addSubview(startPill)

        telemetryLabel.frame = CGRect(x: 220, y: 12, width: 960, height: 40)
        telemetryLabel.font = .monospacedSystemFont(ofSize: 20, weight: .medium)
        telemetryLabel.textColor = UIColor(white: 0.85, alpha: 1.0)
        telemetryLabel.text = "Remote Clicks: 0 | Cursor: (960, 540)"
        taskbarView.addSubview(telemetryLabel)

        clockLabel.frame = CGRect(x: bounds.width - 220, y: 12, width: 196, height: 40)
        clockLabel.font = .monospacedDigitSystemFont(ofSize: 22, weight: .semibold)
        clockLabel.textAlignment = .right
        clockLabel.textColor = .white
        taskbarView.addSubview(clockLabel)

        rippleLayer.fillColor = UIColor.clear.cgColor
        rippleLayer.strokeColor = UIColor.systemCyan.cgColor
        rippleLayer.lineWidth = 4
        rippleLayer.opacity = 0
        layer.addSublayer(rippleLayer)

        cursorView.frame = CGRect(x: 960, y: 540, width: 22, height: 22)
        cursorView.backgroundColor = .white
        cursorView.layer.cornerRadius = 11
        cursorView.layer.borderWidth = 3
        cursorView.layer.borderColor = UIColor.black.cgColor
        addSubview(cursorView)

        updateClock()
        clockTimer = Timer.scheduledTimer(withTimeInterval: 1.0, repeats: true) { [weak self] _ in
            self?.updateClock()
        }
    }

    private func updateClock() {
        let formatter = DateFormatter()
        formatter.dateFormat = "HH:mm:ss"
        clockLabel.text = formatter.string(from: Date())
    }

    private func canvasPoint(normX: Float32, normY: Float32) -> CGPoint {
        let clampedX = min(max(CGFloat(normX), 0.0), 1.0)
        let clampedY = min(max(CGFloat(normY), 0.0), 1.0)
        return CGPoint(x: clampedX * bounds.width, y: clampedY * bounds.height)
    }

    func injectMouseMove(normX: Float32, normY: Float32) {
        let pt = canvasPoint(normX: normX, normY: normY)
        lastPointerCanvasPos = pt
        cursorView.center = pt
        floatingWindow.handlePointerMove(to: pt)
        updateTelemetry()
    }

    func injectMouseButton(normX: Float32, normY: Float32, button: UInt8, isDown: Bool) {
        let pt = canvasPoint(normX: normX, normY: normY)
        lastPointerCanvasPos = pt
        cursorView.center = pt

        if isDown {
            totalRemoteClicks += 1
            showClickRipple(at: pt)
            _ = floatingWindow.handlePointerDown(at: pt)
        } else {
            floatingWindow.handlePointerUp(at: pt)
        }
        updateTelemetry()
    }

    func injectKey(keyCode: UInt32, unicodeChar: UInt16, isDown: Bool) {
        floatingWindow.handleKey(keyCode: keyCode, unicodeChar: unicodeChar, isDown: isDown)
    }

    private func updateTelemetry() {
        telemetryLabel.text = String(
            format: "Remote Clicks: %d | Cursor: (%d, %d)",
            totalRemoteClicks,
            Int(lastPointerCanvasPos.x),
            Int(lastPointerCanvasPos.y)
        )
    }

    private func showClickRipple(at point: CGPoint) {
        let radius: CGFloat = 24
        rippleLayer.path = UIBezierPath(
            ovalIn: CGRect(x: point.x - radius, y: point.y - radius, width: radius * 2, height: radius * 2)
        ).cgPath
        rippleLayer.opacity = 0.95
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.14) { [weak self] in
            self?.rippleLayer.opacity = 0
        }
    }

    /// Captures the full 1920x1080 desktop view regardless of preview transform on the iPhone screen.
    func renderSnapshot() -> UIImage {
        let format = UIGraphicsImageRendererFormat()
        format.scale = 1.0
        format.opaque = true
        let renderer = UIGraphicsImageRenderer(size: Self.canvasSize, format: format)
        return renderer.image { ctx in
            layer.render(in: ctx.cgContext)
        }
    }
}
