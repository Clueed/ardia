import Foundation
import Network

final class GatewaySocket {
  static let maxMessage = 64 << 20

  private let connection: NWConnection
  private var buffer: [UInt8]
  private var message: [UInt8] = []
  private var inMessage = false
  private var closed = false
  var onText: ((String) -> Void)?
  var onClose: (() -> Void)?

  init(connection: NWConnection, leftover: [UInt8]) {
    self.connection = connection
    self.buffer = leftover
  }

  func start() {
    parse()
    receive()
  }

  func send(_ text: String) {
    guard !closed else { return }
    write(opcode: 0x1, payload: Array(text.utf8))
  }

  func close(code: UInt16 = 1000) {
    guard !closed else { return }
    write(opcode: 0x8, payload: [UInt8(code >> 8), UInt8(code & 0xff)])
    finish()
  }

  private func receive() {
    connection.receive(minimumIncompleteLength: 1, maximumLength: 1 << 20) { [weak self] data, _, complete, error in
      guard let self, !self.closed else { return }
      if let data { self.buffer.append(contentsOf: data) }
      self.parse()
      if complete || error != nil { return self.finish() }
      if !self.closed { self.receive() }
    }
  }

  private func parse() {
    while !closed, buffer.count >= 2 {
      let fin = buffer[0] & 0x80 != 0
      let opcode = buffer[0] & 0x0f
      guard buffer[1] & 0x80 != 0, buffer[0] & 0x70 == 0 else { return close(code: 1002) }
      var length = Int(buffer[1] & 0x7f)
      var offset = 2
      if length == 126 {
        guard buffer.count >= 4 else { return }
        length = Int(buffer[2]) << 8 | Int(buffer[3])
        offset = 4
      } else if length == 127 {
        guard buffer.count >= 10 else { return }
        var long: UInt64 = 0
        for i in 2..<10 { long = long << 8 | UInt64(buffer[i]) }
        guard long <= UInt64(Self.maxMessage) else { return close(code: 1009) }
        length = Int(long)
        offset = 10
      }
      guard length <= Self.maxMessage else { return close(code: 1009) }
      let total = offset + 4 + length
      guard buffer.count >= total else { return }
      let mask = Array(buffer[offset..<offset + 4])
      var payload = Array(buffer[offset + 4..<total])
      for i in payload.indices { payload[i] ^= mask[i & 3] }
      buffer.removeFirst(total)
      handle(opcode: opcode, fin: fin, payload: payload)
    }
  }

  private func handle(opcode: UInt8, fin: Bool, payload: [UInt8]) {
    switch opcode {
    case 0x1, 0x2:
      guard !inMessage else { return close(code: 1002) }
      message = payload
      inMessage = !fin
    case 0x0:
      guard inMessage else { return close(code: 1002) }
      message.append(contentsOf: payload)
      guard message.count <= Self.maxMessage else { return close(code: 1009) }
      inMessage = !fin
    case 0x8:
      return close()
    case 0x9:
      return write(opcode: 0xA, payload: payload)
    case 0xA:
      return
    default:
      return close(code: 1002)
    }
    guard !inMessage else { return }
    let text = String(decoding: message, as: UTF8.self)
    message = []
    onText?(text)
  }

  private func write(opcode: UInt8, payload: [UInt8]) {
    var frame: [UInt8] = [0x80 | opcode]
    if payload.count < 126 {
      frame.append(UInt8(payload.count))
    } else if payload.count <= 0xffff {
      frame.append(126)
      frame.append(contentsOf: [UInt8(payload.count >> 8), UInt8(payload.count & 0xff)])
    } else {
      frame.append(127)
      for shift in stride(from: 56, through: 0, by: -8) { frame.append(UInt8((UInt64(payload.count) >> UInt64(shift)) & 0xff)) }
    }
    frame.append(contentsOf: payload)
    connection.send(content: Data(frame), completion: .contentProcessed { _ in })
  }

  private func finish() {
    guard !closed else { return }
    closed = true
    connection.send(content: nil, contentContext: .finalMessage, isComplete: true, completion: .contentProcessed { [connection] _ in connection.cancel() })
    let done = onClose
    onClose = nil
    onText = nil
    done?()
  }
}
