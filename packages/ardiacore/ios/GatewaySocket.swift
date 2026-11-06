import Foundation
import Network

final class GatewaySocket {
  static let maxMessage = 16 << 20
  static let maxControl = 125

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
    var offset = 0
    defer {
      if offset > 0 { buffer.removeFirst(min(offset, buffer.count)) }
    }
    while !closed, buffer.count - offset >= 2 {
      let first = buffer[offset]
      let second = buffer[offset + 1]
      let fin = first & 0x80 != 0
      let opcode = first & 0x0f
      guard second & 0x80 != 0, first & 0x70 == 0 else { return close(code: 1002) }
      var length = Int(second & 0x7f)
      var header = 2
      if length == 126 {
        guard buffer.count - offset >= 4 else { return }
        length = Int(buffer[offset + 2]) << 8 | Int(buffer[offset + 3])
        header = 4
      } else if length == 127 {
        guard buffer.count - offset >= 10 else { return }
        var long: UInt64 = 0
        for i in 2..<10 { long = long << 8 | UInt64(buffer[offset + i]) }
        guard long <= UInt64(Self.maxMessage) else { return close(code: 1009) }
        length = Int(long)
        header = 10
      }
      if opcode & 0x8 != 0, !fin || length > Self.maxControl { return close(code: 1002) }
      guard length <= Self.maxMessage else { return close(code: 1009) }
      let total = header + 4 + length
      guard buffer.count - offset >= total else { return }
      let maskAt = offset + header
      var payload = Array(buffer[(maskAt + 4)..<(offset + total)])
      for i in payload.indices { payload[i] ^= buffer[maskAt + (i & 3)] }
      offset += total
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
