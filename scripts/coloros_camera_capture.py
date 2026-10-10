"""Use request orientation when the software APS path writes a JPEG.

NoneApsImpl otherwise drops EXIF entirely. Pack the request's rotation in
the upper half of the encoder's width argument; ordinary callers retain
rotation zero. The encoder uses the SDK's own EXIF writer. All code slots
and method IDs are pinned by the SDK checksum in the builder.
"""
import struct


def patch_capture_orientation(dex):
    offset, capacity = 0x2720e4, 88
    if struct.unpack_from('<HHHH', dex, offset) != (6, 5, 3, 1):
        raise RuntimeError('Unexpected NoneApsImpl capture method')
    # Sixteen registers: v11=this, v12=ApsCaptureParam, v13..15 unused.
    # v0=image, v1=frame, v2/3=dimensions, v4=rotation, v5=data.
    code = bytes.fromhex('''
        6e10 086d 0c00 0c00
        6e10 466e 0000 0c00
        6e10 116d 0c00 0c06
        3906 0400 1200 0f00
        1f06 5500
        6e10 1101 0600 0c06
        6207 4400
        6e20 0801 7600 0c06
        1204
        3806 0800
        1f06 fa0e
        6e10 0e8d 0600 0a04
        2201 a409
        7010 6970 0100
        54b6 bd51
        5b16 ac51
        6e10 5b01 0000 0a02
        5912 b051
        6e10 5801 0000 0a03
        5913 ae51
        1306 1100 1207
        7130 df6e 6007 0c05
        e004 0410
        b642
        7130 ba6e 2503 0c05
        5b15 ad51
        54b6 be51
        7220 5f8f 1600
        1200 0f00
    ''')
    # LinkedBlockingQueue.add is atomic; the original method has no other
    # queue operation to group with it. Remove its redundant monitor/handler.
    if len(code) > capacity * 2:
        raise RuntimeError('Capture orientation exceeds its DEX code slot')
    struct.pack_into('<HHHHII', dex, offset, 16, 5, 3, 0, 0, capacity)
    dex[offset + 16:offset + 16 + capacity * 2] = code + bytes(capacity * 2 - len(code))

    offset, capacity = 0x26ac28, 90
    if struct.unpack_from('<HHHH', dex, offset) != (11, 3, 6, 5):
        raise RuntimeError('Unexpected ApsUtils JPEG encoder')
    # Reuse the old encoder's exception table as code space. Its next code
    # item remains at 0x26acec. ByteArrayOutputStream owns no native resource.
    # v13=NV21, v14=width|(rotation<<16), v15=height.
    code = bytes.fromhex('''
        2200 c30e 7010 478c 0000
        2207 3b00 0771 07d2
        1303 1100 8ee4 01f5 1206
        7606 c100 0100
        2208 3700 1201
        7055 b100 1841
        1309 5f00
        6e40 c200 8709
        6e10 4b8c 0000 0c08
        2201 9705 7010 5655 0100
        e20a 0e10
        7110 7355 0a00 0a0a
        7110 168d 0a00 0c0a
        6003 6917
        6e30 5b55 310a 0c03
        6e20 ab55 3100
        2200 c30e 7010 478c 0000
        6e30 b655 8100
        6e10 4b8c 0000 0c00
        1100
    ''')
    if len(code) > capacity * 2:
        raise RuntimeError('EXIF encoder exceeds its DEX code slot')
    struct.pack_into('<HHHHII', dex, offset, 16, 3, 6, 0, 0, capacity)
    dex[offset + 16:offset + 16 + capacity * 2] = code + bytes(capacity * 2 - len(code))
