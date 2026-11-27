import UIKit

/// Interactive Phase 1 floating app window hosted inside the 1920x1080 DeX canvas.
final class FloatingWindowView: UIView {
    private let titleBar = UIView()
    private let titleLabel = UILabel()
    private let bodyLabel = UILabel()
    private let counterLabel = UILabel()
    private let typedLabel = UILabel()
    private let incrementButton = UIButton(type: .system)
    private let colorButton = UIButton(type: .system)

    private var clickCount = 0
    private var accentIndex = 0
    private var typedText = ""
    private var isDraggingTitleBar = false
    private var dragOffsetInSuperview = CGPoint.zero

    private let accentColors: [UIColor] = [
        UIColor(red: 0.18, green: 0.52, blue: 0.98, alpha: 1.0),
        UIColor(red: 0.08, green: 0.72, blue: 0.56, alpha: 1.0),
        UIColor(red: 0.91, green: 0.42, blue: 0.24, alpha: 1.0),
        UIColor(red: 0.62, green: 0.36, blue: 0.96, alpha: 1.0)
    ]

    override init(frame: CGRect) {
        super.init(frame: frame)
        setupUI()
    }

    required init?(coder: NSCoder) {
        fatalError("init(coder:) has not been implemented")
    }

    private func setupUI() {
        backgroundColor = UIColor(red: 0.11, green: 0.13, blue: 0.18, alpha: 0.97)
        layer.cornerRadius = 16
        layer.borderWidth = 1.5
        layer.borderColor = UIColor.white.withAlphaComponent(0.18).cgColor
        layer.shadowColor = UIColor.black.cgColor
        layer.shadowOpacity = 0.45
        layer.shadowRadius = 24
        layer.shadowOffset = CGSize(width: 0, height: 12)
        clipsToBounds = false

        titleBar.frame = CGRect(x: 0, y: 0, width: bounds.width, height: 56)
        titleBar.backgroundColor = accentColors[0]
        titleBar.layer.cornerRadius = 16
        titleBar.layer.maskedCorners = [.layerMinXMinYCorner, .layerMaxXMinYCorner]
        titleBar.autoresizingMask = [.flexibleWidth]
        addSubview(titleBar)

        let dotColors: [UIColor] = [.systemRed, .systemYellow, .systemGreen]
        for (idx, color) in dotColors.enumerated() {
            let dot = UIView(frame: CGRect(x: 20 + idx * 24, y: 21, width: 14, height: 14))
            dot.backgroundColor = color
            dot.layer.cornerRadius = 7
            titleBar.addSubview(dot)
        }

        titleLabel.frame = CGRect(x: 108, y: 12, width: bounds.width - 130, height: 32)
        titleLabel.text = "PoC App — DeX Counter & Notes"
        titleLabel.font = .systemFont(ofSize: 22, weight: .semibold)
        titleLabel.textColor = .white
        titleLabel.autoresizingMask = [.flexibleWidth]
        titleBar.addSubview(titleLabel)

        bodyLabel.frame = CGRect(x: 36, y: 84, width: bounds.width - 72, height: 64)
        bodyLabel.text = "Drag titlebar from Windows mouse, click buttons below, or type on your PC keyboard."
        bodyLabel.font = .systemFont(ofSize: 22, weight: .regular)
        bodyLabel.textColor = UIColor(white: 0.82, alpha: 1.0)
        bodyLabel.numberOfLines = 2
        addSubview(bodyLabel)

        counterLabel.frame = CGRect(x: 36, y: 170, width: bounds.width - 72, height: 76)
        counterLabel.text = "Button Clicks: 0"
        counterLabel.font = .monospacedDigitSystemFont(ofSize: 44, weight: .bold)
        counterLabel.textColor = .white
        addSubview(counterLabel)

        incrementButton.frame = CGRect(x: 36, y: 274, width: 290, height: 72)
        incrementButton.setTitle("+1 Counter", for: .normal)
        incrementButton.titleLabel?.font = .systemFont(ofSize: 26, weight: .bold)
        incrementButton.setTitleColor(.white, for: .normal)
        incrementButton.backgroundColor = accentColors[0]
        incrementButton.layer.cornerRadius = 12
        addSubview(incrementButton)

        colorButton.frame = CGRect(x: 350, y: 274, width: 290, height: 72)
        colorButton.setTitle("Switch Color", for: .normal)
        colorButton.titleLabel?.font = .systemFont(ofSize: 26, weight: .semibold)
        colorButton.setTitleColor(.white, for: .normal)
        colorButton.backgroundColor = UIColor(white: 0.24, alpha: 1.0)
        colorButton.layer.cornerRadius = 12
        addSubview(colorButton)

        typedLabel.frame = CGRect(x: 36, y: 382, width: bounds.width - 72, height: 140)
        typedLabel.backgroundColor = UIColor(red: 0.06, green: 0.08, blue: 0.12, alpha: 1.0)
        typedLabel.layer.cornerRadius = 12
        typedLabel.layer.borderWidth = 1
        typedLabel.layer.borderColor = UIColor.white.withAlphaComponent(0.14).cgColor
        typedLabel.clipsToBounds = true
        typedLabel.font = .monospacedSystemFont(ofSize: 22, weight: .medium)
        typedLabel.textColor = UIColor(red: 0.56, green: 0.92, blue: 0.68, alpha: 1.0)
        typedLabel.numberOfLines = 4
        typedLabel.text = "  Typed from PC: (waiting for keyboard input...)"
        addSubview(typedLabel)
    }

    func handlePointerDown(at canvasPoint: CGPoint) -> Bool {
        guard frame.contains(canvasPoint), let superview else { return false }
        let local = convert(canvasPoint, from: superview)

        if titleBar.frame.contains(local) {
            isDraggingTitleBar = true
            dragOffsetInSuperview = CGPoint(x: canvasPoint.x - frame.origin.x, y: canvasPoint.y - frame.origin.y)
            return true
        }

        if incrementButton.frame.contains(local) {
            clickCount += 1
            counterLabel.text = "Button Clicks: \(clickCount)"
            incrementButton.alpha = 0.75
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.08) {
                self.incrementButton.alpha = 1.0
            }
            return true
        }

        if colorButton.frame.contains(local) {
            accentIndex = (accentIndex + 1) % accentColors.count
            let nextColor = accentColors[accentIndex]
            titleBar.backgroundColor = nextColor
            incrementButton.backgroundColor = nextColor
            return true
        }

        return true
    }

    func handlePointerMove(to canvasPoint: CGPoint) {
        guard isDraggingTitleBar, let superview else { return }
        let maxX = max(0, superview.bounds.width - frame.width)
        let maxY = max(0, superview.bounds.height - 64 - frame.height)
        let newX = min(max(0, canvasPoint.x - dragOffsetInSuperview.x), maxX)
        let newY = min(max(0, canvasPoint.y - dragOffsetInSuperview.y), maxY)
        frame.origin = CGPoint(x: newX, y: newY)
    }

    func handlePointerUp(at canvasPoint: CGPoint) {
        isDraggingTitleBar = false
    }

    func handleKey(keyCode: UInt32, unicodeChar: UInt16, isDown: Bool) {
        guard isDown else { return }
        if keyCode == 8 || unicodeChar == 8 { // Backspace
            if !typedText.isEmpty {
                typedText.removeLast()
            }
        } else if keyCode == 13 || unicodeChar == 13 { // Enter
            typedText.append("\n")
        } else if unicodeChar >= 32, let scalar = UnicodeScalar(unicodeChar) {
            typedText.append(Character(scalar))
            if typedText.count > 140 {
                typedText = String(typedText.suffix(140))
            }
        }
        typedLabel.text = typedText.isEmpty
            ? "  Typed from PC: (waiting for keyboard input...)"
            : "  Typed from PC: \(typedText)"
    }
}
