import struct
import zlib


PNG = b'\x89PNG\r\n\x1a\n'


def paeth(left, above, corner):
    estimate = left + above - corner
    dl, da, dc = abs(estimate - left), abs(estimate - above), abs(estimate - corner)
    if dl <= da and dl <= dc:
        return left
    return above if da <= dc else corner


def png_chunk(tag, payload):
    return struct.pack('>I', len(payload)) + tag + payload + struct.pack('>I', zlib.crc32(tag + payload))


def convert_apple_png(data, header, width, height):
    depth, color_type, compression, filtering, interlace = header[8:]
    if depth != 8 or color_type not in (2, 6) or compression or filtering or interlace:
        return b''
    channels = 4 if color_type == 6 else 3
    offset = len(PNG)
    compressed = bytearray()
    while offset + 12 <= len(data):
        length, tag = struct.unpack_from('>I4s', data, offset)
        end = offset + 12 + length
        if end > len(data):
            return b''
        if tag == b'IDAT':
            compressed.extend(data[offset + 8:end - 4])
        if tag == b'IEND':
            break
        offset = end

    stride = width * channels
    expected = (stride + 1) * height
    stream = zlib.decompressobj(wbits=-15)
    rows = stream.decompress(compressed, expected + 1)
    if len(rows) != expected or not stream.eof:
        return b''
    previous = bytearray(stride)
    output = bytearray()
    for start in range(0, len(rows), stride + 1):
        mode = rows[start]
        if mode > 4:
            return b''
        row = bytearray(rows[start + 1:start + stride + 1])
        if mode:
            for index, value in enumerate(row):
                left = row[index - channels] if index >= channels else 0
                above = previous[index]
                if mode == 1:
                    predictor = left
                elif mode == 2:
                    predictor = above
                elif mode == 3:
                    predictor = (left + above) // 2
                else:
                    corner = previous[index - channels] if index >= channels else 0
                    predictor = paeth(left, above, corner)
                row[index] = (value + predictor) & 255
        previous = row
        output.append(0)
        for index in range(0, stride, channels):
            blue, green, red = row[index:index + 3]
            if channels == 3:
                output.extend((red, green, blue))
                continue
            alpha = row[index + 3]
            if alpha:
                output.extend(min(255, (color * 255 + alpha // 2) // alpha) for color in (red, green, blue))
            else:
                output.extend((0, 0, 0))
            output.append(alpha)
    return PNG + png_chunk(b'IHDR', header) + png_chunk(b'IDAT', zlib.compress(output)) + png_chunk(b'IEND', b'')


def display_png(data):
    if not data.startswith(PNG):
        return 0, b''
    offset = len(PNG)
    apple = data[offset + 4:offset + 8] == b'CgBI'
    if apple:
        offset += 12 + int.from_bytes(data[offset:offset + 4], 'big')
    if data[offset:offset + 8] != b'\x00\x00\x00\x0dIHDR':
        return 0, b''
    header = data[offset + 8:offset + 21]
    if len(header) != 13:
        return 0, b''
    width, height = struct.unpack_from('>II', header)
    pixels = width * height
    if not 0 < pixels <= 1024 * 1024:
        return 0, b''
    if apple:
        try:
            data = convert_apple_png(data, header, width, height)
        except zlib.error:
            return 0, b''
    return pixels, data
