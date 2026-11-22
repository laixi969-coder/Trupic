import Foundation
import Vision
import CoreImage
import AppKit

guard CommandLine.arguments.count == 3 else { exit(2) }
if #available(macOS 14, *) {
    let handler = VNImageRequestHandler(url: URL(fileURLWithPath: CommandLine.arguments[1]))
    do {
        let request = VNGenerateForegroundInstanceMaskRequest()
        try handler.perform([request])
        guard let result = request.results?.first, !result.allInstances.isEmpty else { exit(3) }
        let buffer = try result.generateMaskedImage(ofInstances: result.allInstances, from: handler, croppedToInstancesExtent: false)
        let image = CIImage(cvPixelBuffer: buffer)
        let context = CIContext()
        try context.writePNGRepresentation(of: image, to: URL(fileURLWithPath: CommandLine.arguments[2]), format: .RGBA8, colorSpace: CGColorSpaceCreateDeviceRGB())
    } catch { exit(4) }
} else { exit(5) }
