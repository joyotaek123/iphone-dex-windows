import AVFoundation
import CoreMedia
import CoreVideo
import Foundation
import UIKit
import VideoToolbox

/// Encodes 1920x1080 desktop frames to JPEG (Phase 1 PoC) or hardware H.264 Annex-B (VideoToolbox).
final class VideoEncoder {
    typealias H264FrameCallback = (_ annexBData: Data, _ isKeyframe: Bool, _ timestampUs: UInt64) -> Void

    private var session: VTCompressionSession?
    private let width: Int32
    private let height: Int32
    private let fps: Int32
    private let encodeQueue = DispatchQueue(label: "com.iphonedex.videoencoder", qos: .userInteractive)

    var onEncodedH264Frame: H264FrameCallback?

    init(width: Int32 = 1920, height: Int32 = 1080, fps: Int32 = 60) {
        self.width = width
        self.height = height
        self.fps = fps
    }

    deinit {
        stopH264Session()
    }

    func encodeJPEG(_ image: UIImage, quality: CGFloat = 0.72) -> Data? {
        return image.jpegData(compressionQuality: quality)
    }

    func startH264Session(bitrateBps: Int = 8_000_000) -> Bool {
        stopH264Session()

        let encoderSpec: [String: Any] = [:]
        let sourceAttrs: [String: Any] = [
            kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA,
            kCVPixelBufferWidthKey as String: width,
            kCVPixelBufferHeightKey as String: height
        ]

        var newSession: VTCompressionSession?
        let refcon = Unmanaged.passUnretained(self).toOpaque()
        let status = VTCompressionSessionCreate(
            allocator: kCFAllocatorDefault,
            width: width,
            height: height,
            codecType: kCMVideoCodecType_H264,
            encoderSpecification: encoderSpec as CFDictionary,
            imageBufferAttributes: sourceAttrs as CFDictionary,
            compressedDataAllocator: nil,
            outputCallback: h264OutputCallback,
            refcon: refcon,
            compressionSessionOut: &newSession
        )

        guard status == noErr, let created = newSession else {
            return false
        }

        VTSessionSetProperty(created, key: kVTCompressionPropertyKey_RealTime, value: kCFBooleanTrue)
        VTSessionSetProperty(created, key: kVTCompressionPropertyKey_ProfileLevel, value: kVTProfileLevel_H264_Main_AutoLevel)
        VTSessionSetProperty(created, key: kVTCompressionPropertyKey_AllowFrameReordering, value: kCFBooleanFalse)
        VTSessionSetProperty(created, key: kVTCompressionPropertyKey_ExpectedFrameRate, value: NSNumber(value: fps))
        VTSessionSetProperty(created, key: kVTCompressionPropertyKey_MaxKeyFrameInterval, value: NSNumber(value: fps * 2))
        VTSessionSetProperty(created, key: kVTCompressionPropertyKey_AverageBitRate, value: NSNumber(value: bitrateBps))
        VTCompressionSessionPrepareToEncodeFrames(created)

        self.session = created
        return true
    }

    func stopH264Session() {
        if let active = session {
            VTCompressionSessionCompleteFrames(active, untilPresentationTimeStamp: .invalid)
            VTCompressionSessionInvalidate(active)
            session = nil
        }
    }

    func encodeH264(image: UIImage, timestampUs: UInt64, forceKeyframe: Bool = false) {
        guard let pixelBuffer = Self.createPixelBuffer(from: image, width: Int(width), height: Int(height)) else {
            return
        }
        encodeQueue.async { [weak self] in
            guard let self, let activeSession = self.session else { return }
            let pts = CMTime(value: Int64(timestampUs), timescale: 1_000_000)
            let frameProps: [String: Any]? = forceKeyframe
                ? [kVTEncodeFrameOptionKey_ForceKeyFrame as String: true]
                : nil

            VTCompressionSessionEncodeFrame(
                activeSession,
                imageBuffer: pixelBuffer,
                presentationTimeStamp: pts,
                duration: CMTime(value: 1, timescale: self.fps),
                frameProperties: frameProps as CFDictionary?,
                sourceFrameRefcon: nil,
                infoFlagsOut: nil
            )
        }
    }

    fileprivate func handleEncodedSampleBuffer(_ sampleBuffer: CMSampleBuffer) {
        guard CMSampleBufferDataIsReady(sampleBuffer) else { return }

        var isKeyframe = true
        if let attachments = CMSampleBufferGetSampleAttachmentsArray(sampleBuffer, createIfNecessary: false) as? [[CFString: Any]],
           let first = attachments.first,
           let notSync = first[kCMSampleAttachmentKey_NotSync] as? Bool {
            isKeyframe = !notSync
        }

        var annexB = Data()
        let startCode: [UInt8] = [0x00, 0x00, 0x00, 0x01]

        if isKeyframe, let formatDesc = CMSampleBufferGetFormatDescription(sampleBuffer) {
            var spsPointer: UnsafePointer<UInt8>?
            var spsSize = 0
            var spsCount = 0
            if CMVideoFormatDescriptionGetH264ParameterSetAtIndex(
                formatDesc,
                parameterSetIndex: 0,
                parameterSetPointerOut: &spsPointer,
                parameterSetSizeOut: &spsSize,
                parameterSetCountOut: &spsCount,
                nalUnitHeaderLengthOut: nil
            ) == noErr, let spsPointer {
                annexB.append(contentsOf: startCode)
                annexB.append(spsPointer, count: spsSize)
            }

            var ppsPointer: UnsafePointer<UInt8>?
            var ppsSize = 0
            if CMVideoFormatDescriptionGetH264ParameterSetAtIndex(
                formatDesc,
                parameterSetIndex: 1,
                parameterSetPointerOut: &ppsPointer,
                parameterSetSizeOut: &ppsSize,
                parameterSetCountOut: nil,
                nalUnitHeaderLengthOut: nil
            ) == noErr, let ppsPointer {
                annexB.append(contentsOf: startCode)
                annexB.append(ppsPointer, count: ppsSize)
            }
        }

        guard let blockBuffer = CMSampleBufferGetDataBuffer(sampleBuffer) else { return }
        var totalLength = 0
        var dataPointer: UnsafeMutablePointer<Int8>?
        let status = CMBlockBufferGetDataPointer(
            blockBuffer,
            atOffset: 0,
            lengthAtOffsetOut: nil,
            totalLengthOut: &totalLength,
            dataPointerOut: &dataPointer
        )
        guard status == kCMBlockBufferNoErr, let dataPointer else { return }

        var offset = 0
        let naluHeaderLength = 4
        while offset + naluHeaderLength <= totalLength {
            var naluLengthBE: UInt32 = 0
            memcpy(&naluLengthBE, dataPointer.advanced(by: offset), naluHeaderLength)
            let naluLength = Int(UInt32(bigEndian: naluLengthBE))
            offset += naluHeaderLength
            guard naluLength > 0, offset + naluLength <= totalLength else { break }

            annexB.append(contentsOf: startCode)
            let rawPtr = UnsafeRawPointer(dataPointer.advanced(by: offset)).assumingMemoryBound(to: UInt8.self)
            annexB.append(rawPtr, count: naluLength)
            offset += naluLength
        }

        let pts = CMSampleBufferGetPresentationTimeStamp(sampleBuffer)
        let timestampUs = UInt64(max(0, CMTimeGetSeconds(pts) * 1_000_000.0))
        onEncodedH264Frame?(annexB, isKeyframe, timestampUs)
    }

    private static func createPixelBuffer(from image: UIImage, width: Int, height: Int) -> CVPixelBuffer? {
        guard let cgImage = image.cgImage else { return nil }
        var pixelBuffer: CVPixelBuffer?
        let attrs: [String: Any] = [
            kCVPixelBufferCGImageCompatibilityKey as String: true,
            kCVPixelBufferCGBitmapContextCompatibilityKey as String: true
        ]
        let status = CVPixelBufferCreate(
            kCFAllocatorDefault,
            width,
            height,
            kCVPixelFormatType_32BGRA,
            attrs as CFDictionary,
            &pixelBuffer
        )
        guard status == kCVReturnSuccess, let buffer = pixelBuffer else { return nil }

        CVPixelBufferLockBaseAddress(buffer, [])
        defer { CVPixelBufferUnlockBaseAddress(buffer, []) }

        guard let baseAddress = CVPixelBufferGetBaseAddress(buffer) else { return nil }
        let colorSpace = CGColorSpaceCreateDeviceRGB()
        let bitmapInfo = CGBitmapInfo.byteOrder32Little.rawValue | CGImageAlphaInfo.premultipliedFirst.rawValue

        guard let context = CGContext(
            data: baseAddress,
            width: width,
            height: height,
            bitsPerComponent: 8,
            bytesPerRow: CVPixelBufferGetBytesPerRow(buffer),
            space: colorSpace,
            bitmapInfo: bitmapInfo
        ) else {
            return nil
        }

        context.draw(cgImage, in: CGRect(x: 0, y: 0, width: width, height: height))
        return buffer
    }
}

private let h264OutputCallback: VTCompressionOutputCallback = { refcon, _, status, _, sampleBuffer in
    guard status == noErr, let refcon, let sampleBuffer else { return }
    let encoder = Unmanaged<VideoEncoder>.fromOpaque(refcon).takeUnretainedValue()
    encoder.handleEncodedSampleBuffer(sampleBuffer)
}
